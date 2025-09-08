from __future__ import annotations

import os
import io
import json
import time
import base64
import tempfile
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

import gradio as gr
from dotenv import load_dotenv

# Support running both as a package module and as a standalone script
try:
    from .runpod_client import submit_job, get_status, extract_progress
    from .param_widgets import build_param_widgets, collect_params_from_widgets
except Exception:
    from runpod_client import submit_job, get_status, extract_progress  # type: ignore
    from param_widgets import build_param_widgets, collect_params_from_widgets  # type: ignore

APP_TITLE = "InfiniteTalk — Runpod Serverless UI"
APP_DESC = "Submit jobs to your Runpod Serverless endpoint for InfiniteTalk generation. Monitor progress, view logs, and download results."

# Lightweight local config
# Persist under ~/.config/infiniteTalk_ui/config.json (preferred) or fallback to ./.ui_config.json
CONFIG_DIR_CANDIDATES = [
    os.path.join(os.path.expanduser("~"), ".config", "infiniteTalk_ui"),
]
CONFIG_BASENAME = "config.json"
ENV_VARS = ["RUNPOD_API_KEY", "RUNPOD_ENDPOINT_ID"]

# Polling cadence
POLL_INIT_SEC = 2.0
POLL_MAX_SEC = 6.0
POLL_BACKOFF_AFTER_S = 120.0  # gradually increase interval after 2 minutes


@dataclass
class UIConfig:
    api_key: str = ""
    endpoint_id: str = ""

    @staticmethod
    def _ensure_path() -> Optional[str]:
        for d in CONFIG_DIR_CANDIDATES:
            try:
                os.makedirs(d, exist_ok=True)
                return os.path.join(d, CONFIG_BASENAME)
            except Exception:
                continue
        # Fallback to project-local JSON file per spec
        return os.path.join(os.getcwd(), ".ui_config.json")

    @classmethod
    def load(cls) -> "UIConfig":
        # Load from .env (optional)
        load_dotenv(override=False)
        env_api = os.getenv("RUNPOD_API_KEY", "")
        env_ep = os.getenv("RUNPOD_ENDPOINT_ID", "")

        path = cls._ensure_path()
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return UIConfig(
                    api_key=data.get("api_key") or env_api,
                    endpoint_id=data.get("endpoint_id") or env_ep,
                )
            except Exception:
                pass
        return UIConfig(api_key=env_api, endpoint_id=env_ep)

    def save(self):
        path = self._ensure_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"api_key": self.api_key, "endpoint_id": self.endpoint_id}, f, indent=2)
        except Exception:
            # Best-effort; ignore failures
            pass


# -------------- Helpers for inputs --------------


def _file_to_data_url(file_path: str, kind_hint: str = "application/octet-stream") -> str:
    # Return a data URL "data:<mime>;base64,<payload>"
    # We don't rely on python-magic; use a simple mapping by extension.
    ext = (os.path.splitext(file_path)[1] or "").lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
    }.get(ext, kind_hint)
    with open(file_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _maybe_prepare_ref(value_upload, value_url: str, allow_base64: bool, kind_hint: str) -> Optional[str]:
    """
    Returns a string reference for cond_video or audio:
    - If URL provided, return it.
    - Else if local upload provided:
        - If allow_base64, return base64 data URL
        - Else, try to return a file path (Runpod worker will fetch path if volume path; otherwise base64 recommended)
    - Else None
    """
    if value_url and value_url.strip():
        return value_url.strip()
    if value_upload:
        path = getattr(value_upload, "name", None) or (value_upload if isinstance(value_upload, str) else None)
        if path and os.path.exists(path):
            if allow_base64:
                return _file_to_data_url(path, kind_hint=kind_hint)
            # Fallback to absolute path reference (works if worker can access it; usually not from local machine)
            return path
    return None


def _format_error_message(code: Optional[str], message: str) -> str:
    # Map E_* codes to friendly text with GUIDE links
    guide_link = "InfiniteTalk_Runpod_Serverless/GUIDE.md#troubleshooting"
    suggestions = {
        "E_INPUT_VALIDATION": "Check required fields and parameter ranges.",
        "E_DOWNLOAD_FAILED": "Ensure your URLs are reachable and under size limits.",
        "E_AUDIO_EMBEDDING": "Verify audio format (prefer WAV, 16kHz/mono).",
        "E_PIPELINE_LOAD": "Verify CKPT_DIR/INFINITETALK_DIR/WAV2VEC_DIR on the endpoint.",
        "E_OOM": "Reduce size to 480p and steps to 8–12; set offload_model=true.",
        "E_FFMPEG": "Ensure ffmpeg is installed and inputs are valid.",
        "E_UPLOAD": "Check S3 credentials/bucket/prefix.",
        "E_TIMEOUT": "Increase executionTimeout or reduce job complexity.",
    }
    base = f"{code}: {message}" if code else message
    tip = suggestions.get(code or "", "")
    if tip:
        base += f"\n\nTip: {tip}\nSee: {guide_link}"
    return base


# -------------- Submit + Poll logic --------------


def _build_payload(
    input_mode: str,
    prompt: str,
    video_file, video_url: str,
    image_file, image_url: str,
    person1_audio_file, person1_audio_url: str,
    person2_audio_file, person2_audio_url: str,
    use_tts: bool, tts_text: str, tts_voice1: str, tts_voice2: str,
    audio_type: str,
    params: Dict[str, Any],
    allow_base64: bool = True,
) -> Dict[str, Any]:
    """
    Construct envelope: { "input": { ... } } per worker schema.
    """
    input_obj: Dict[str, Any] = {}

    # Required
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("Prompt is required.")

    # cond_video: from image or video depending on mode
    if input_mode == "image → talking head":
        cond_video = _maybe_prepare_ref(image_file, image_url, allow_base64=allow_base64, kind_hint="image/jpeg")
    else:
        cond_video = _maybe_prepare_ref(video_file, video_url, allow_base64=allow_base64, kind_hint="video/mp4")
    if not cond_video:
        raise ValueError("A reference image or video is required.")

    # Audio: either cond_audio (person1 required) or tts_audio
    cond_audio: Optional[Dict[str, Any]] = None
    tts_audio: Optional[Dict[str, Any]] = None

    if use_tts:
        tt = (tts_text or "").strip()
        if not tt:
            raise ValueError("TTS text is required when TTS is enabled.")
        tts_audio = {"text": tt}
        if tts_voice1.strip():
            tts_audio["human1_voice"] = tts_voice1.strip()
        if tts_voice2.strip():
            tts_audio["human2_voice"] = tts_voice2.strip()
    else:
        p1 = _maybe_prepare_ref(person1_audio_file, person1_audio_url, allow_base64=allow_base64, kind_hint="audio/wav")
        p2 = _maybe_prepare_ref(person2_audio_file, person2_audio_url, allow_base64=allow_base64, kind_hint="audio/wav")
        if not p1 and not p2:
            raise ValueError("Provide at least one audio reference or enable TTS.")
        cond_audio = {}
        if p1:
            cond_audio["person1"] = p1
        if p2:
            cond_audio["person2"] = p2

    # Assemble
    input_obj.update({
        "prompt": prompt,
        "cond_video": cond_video,
    })
    if cond_audio:
        input_obj["cond_audio"] = cond_audio
        if "person2" in cond_audio and cond_audio["person2"]:
            # If 2 speakers, audio_type required
            input_obj["audio_type"] = (audio_type or "para")
    if tts_audio:
        input_obj["tts_audio"] = tts_audio

    # Merge generation params
    input_obj.update(params)

    return {"input": input_obj}


def _poll_status_stream(
    api_key: str,
    endpoint_id: str,
    job_id: str,
    progress_bar: gr.Progress,
    logbox: gr.Textbox,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Poll /status until terminal, updating UI.
    Returns (output_json, error_message)
    """
    start = time.time()
    interval = POLL_INIT_SEC
    last_log_tail = ""
    while True:
        try:
            status = get_status(api_key, endpoint_id, job_id)
        except Exception as e:
            return None, f"Status error: {str(e)}"

        percent, stage, checkpoints = extract_progress(status)
        elapsed = time.time() - start
        # adaptive backoff
        interval = min(POLL_MAX_SEC, POLL_INIT_SEC + (elapsed / POLL_BACKOFF_AFTER_S) * (POLL_MAX_SEC - POLL_INIT_SEC))

        # Update progress
        try:
            progress_bar(percent / 100.0, desc=f"{stage} ({percent}%)")
        except Exception:
            pass

        # Update logs
        log_lines: List[str] = []
        if isinstance(checkpoints, list):
            for item in checkpoints[-50:]:
                try:
                    log_lines.append(json.dumps(item, ensure_ascii=False))
                except Exception:
                    log_lines.append(str(item))
        # Also append any 'message' or status text
        if stage:
            log_lines.append(f"status: {stage}, percent={percent}")
        log_text = "\n".join(log_lines)
        if log_text != last_log_tail:
            last_log_tail = log_text
            try:
                logbox.update(value=log_text)
            except Exception:
                pass

        s = (status.get("status") or "").upper()
        if s in ("COMPLETED", "FAILED", "TIMEOUT"):
            if s == "COMPLETED":
                return status.get("output") or {}, None
            # Try to extract worker error payload
            output = status.get("output") or {}
            if isinstance(output, dict):
                err = output.get("error") or {}
                code = err.get("code")
                msg = err.get("message") or json.dumps(output)
                return None, _format_error_message(code, msg)
            return None, f"Job ended with status={s}"
        time.sleep(interval)


def _pick_video_result(output: Dict[str, Any]) -> Tuple[Optional[str], Optional[bytes], Optional[str]]:
    """
    Return one of:
    - (url, None, None) if video URL present
    - (None, bytes, 'video/mp4') if inline base64-like payload present
    """
    # SuccessOutput schema suggests output.video.url OR artifacts list.
    if not isinstance(output, dict):
        return None, None, None

    video = output.get("video")
    if isinstance(video, dict):
        url = video.get("url")
        if url:
            return url, None, video.get("mime") or "video/mp4"
        # Inline? Unlikely under "video", but check common fields.
        b64 = video.get("base64") or video.get("data")
        if b64:
            try:
                raw = base64.b64decode(b64.split(",")[-1])
                return None, raw, video.get("mime") or "video/mp4"
            except Exception:
                pass

    # Artifacts
    arts = output.get("artifacts")
    if isinstance(arts, list):
        for a in arts:
            if a.get("type") in ("video",) and (a.get("url") or a.get("path") or a.get("base64")):
                if a.get("url"):
                    return a["url"], None, a.get("mime") or "video/mp4"
                if a.get("base64"):
                    try:
                        raw = base64.b64decode(a["base64"].split(",")[-1])
                        return None, raw, a.get("mime") or "video/mp4"
                    except Exception:
                        continue
    return None, None, None


def _write_temp_video(data: bytes, suffix: str = ".mp4") -> str:
    fd, path = tempfile.mkstemp(prefix="infinitetalk_", suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


# -------------- Gradio UI wiring --------------


def build_ui():
    cfg = UIConfig.load()

    with gr.Blocks(title=APP_TITLE) as demo:
        gr.Markdown(f"# {APP_TITLE}\n{APP_DESC}")

        with gr.Tabs():
            with gr.TabItem("Inputs"):
                with gr.Row():
                    api_key = gr.Textbox(label="Runpod API Key", value=cfg.api_key, type="password")
                    endpoint_id = gr.Textbox(label="Runpod Endpoint ID", value=cfg.endpoint_id)

                input_mode = gr.Radio(
                    label="Input Type",
                    choices=["image → talking head", "video → dubbing/lip-sync"],
                    value="image → talking head",
                )

                prompt = gr.Textbox(label="Prompt (required)", placeholder="Describe the scene or speech context", value="A person speaking to camera")

                with gr.Row():
                    image_file = gr.Image(label="Reference Image (optional if using video)", type="filepath")
                    image_url = gr.Textbox(label="Reference Image URL", placeholder="https://...")

                with gr.Row():
                    video_file = gr.Video(label="Reference Video (optional if using image)")
                    video_url = gr.Textbox(label="Reference Video URL", placeholder="https://...")

                with gr.Row():
                    use_tts = gr.Checkbox(label="Use TTS instead of audio uploads", value=False)
                    audio_type = gr.Radio(
                        label="Two-speaker Audio Mode (if both provided)",
                        choices=["para", "add"],
                        value="para",
                    )

                with gr.Row(visible=True) as audio_upload_row:
                    person1_audio_file = gr.Audio(label="Audio — person1", type="filepath")
                    person1_audio_url = gr.Textbox(label="Audio URL — person1", placeholder="https://...")

                with gr.Row(visible=True) as audio_upload_row2:
                    person2_audio_file = gr.Audio(label="Audio — person2 (optional)", type="filepath")
                    person2_audio_url = gr.Textbox(label="Audio URL — person2", placeholder="https://...")

                with gr.Row(visible=False) as tts_row:
                    tts_text = gr.Textbox(label="TTS Text", placeholder="What should be said...")
                    tts_voice1 = gr.Textbox(label="TTS Voice for person1 (optional)")
                    tts_voice2 = gr.Textbox(label="TTS Voice for person2 (optional)")

                def _toggle_tts(tts: bool):
                    return (
                        gr.update(visible=not tts),
                        gr.update(visible=not tts),
                        gr.update(visible=tts),
                    )

                use_tts.change(_toggle_tts, inputs=[use_tts], outputs=[audio_upload_row, audio_upload_row2, tts_row])

            with gr.TabItem("Parameters"):
                param_widgets, params_group = build_param_widgets()
                params_container = params_group  # for layout reference

            with gr.TabItem("Progress / Logs"):
                progress_bar = gr.HTML("&nbsp;")
                logs = gr.Textbox(label="Logs", lines=16, interactive=False)

            with gr.TabItem("Output"):
                result_video = gr.Video(label="Result Video", autoplay=False)
                download_file = gr.File(label="Download Artifact", visible=False)
                artifacts_json = gr.JSON(label="Artifacts/Metadata", value={})

        with gr.Row():
            run_btn = gr.Button("Submit Job", variant="primary")
            stop_btn = gr.Button("Cancel Polling", variant="secondary")
            status_text = gr.Markdown("")

        # State
        job_state = gr.State({"job_id": None, "cancel": False})

        def _save_connection(api: str, ep: str):
            c = UIConfig(api_key=api.strip(), endpoint_id=ep.strip())
            c.save()
            return gr.update(value=api), gr.update(value=ep)

        api_key.blur(_save_connection, inputs=[api_key, endpoint_id], outputs=[api_key, endpoint_id])
        endpoint_id.blur(_save_connection, inputs=[api_key, endpoint_id], outputs=[api_key, endpoint_id])

        def _submit(
            api: str,
            ep: str,
            _input_mode: str,
            _prompt: str,
            _video_file, _video_url: str,
            _image_file, _image_url: str,
            _p1_file, _p1_url: str,
            _p2_file, _p2_url: str,
            _use_tts: bool, _tts_text: str, _tts_v1: str, _tts_v2: str,
            _audio_type: str,
            # Params (collected inside)
        ):
            if not api.strip() or not ep.strip():
                return (
                    {"job_id": None, "cancel": False},
                    gr.update(value="API Key and Endpoint ID are required."),
                    gr.update(value=""),
                    gr.update(value=None),  # video
                    gr.update(visible=False, value=None),  # file
                    gr.update(value={}),
                )

            # Collect params from widgets
            try:
                params = collect_params_from_widgets(param_widgets)
            except Exception as e:
                return (
                    {"job_id": None, "cancel": False},
                    gr.update(value=f"Parameter error: {str(e)}"),
                    gr.update(value=""),
                    gr.update(value=None),
                    gr.update(visible=False, value=None),
                    gr.update(value={}),
                )

            # Build payload
            try:
                payload = _build_payload(
                    input_mode=_input_mode,
                    prompt=_prompt,
                    video_file=_video_file, video_url=_video_url,
                    image_file=_image_file, image_url=_image_url,
                    person1_audio_file=_p1_file, person1_audio_url=_p1_url,
                    person2_audio_file=_p2_file, person2_audio_url=_p2_url,
                    use_tts=_use_tts, tts_text=_tts_text or "", tts_voice1=_tts_v1 or "", tts_voice2=_tts_v2 or "",
                    audio_type=_audio_type or "para",
                    params=params,
                    allow_base64=True,  # Prefer base64 for portability (watch payload size)
                )
            except Exception as e:
                return (
                    {"job_id": None, "cancel": False},
                    gr.update(value=f"Input error: {str(e)}"),
                    gr.update(value=""),
                    gr.update(value=None),
                    gr.update(visible=False, value=None),
                    gr.update(value={}),
                )

            # Submit
            try:
                submit_res = submit_job(api, ep, payload)
            except Exception as e:
                return (
                    {"job_id": None, "cancel": False},
                    gr.update(value=f"Submit error: {str(e)}"),
                    gr.update(value=""),
                    gr.update(value=None),
                    gr.update(visible=False, value=None),
                    gr.update(value={}),
                )

            # Runpod often returns {"id": "...", "status": "IN_QUEUE"}
            job_id = submit_res.get("id") or submit_res.get("jobId") or submit_res.get("job_id")
            if not job_id:
                # Fallback: show raw response
                return (
                    {"job_id": None, "cancel": False},
                    gr.update(value=f"Unexpected submit response: {json.dumps(submit_res)}"),
                    gr.update(value=""),
                    gr.update(value=None),
                    gr.update(visible=False, value=None),
                    gr.update(value={}),
                )

            return (
                {"job_id": job_id, "cancel": False},
                gr.update(value=f"Submitted job: {job_id}"),
                gr.update(value=""),
                gr.update(value=None),
                gr.update(visible=False, value=None),
                gr.update(value={}),
            )

        run_btn.click(
            _submit,
            inputs=[
                api_key, endpoint_id,
                input_mode, prompt,
                video_file, video_url,
                image_file, image_url,
                person1_audio_file, person1_audio_url,
                person2_audio_file, person2_audio_url,
                use_tts, tts_text, tts_voice1, tts_voice2,
                audio_type,
            ],
            outputs=[job_state, status_text, logs, result_video, download_file, artifacts_json],
        )

        def _cancel(curr: Dict[str, Any]):
            curr = dict(curr or {})
            curr["cancel"] = True
            return curr, gr.update(value="Polling cancelled by user.")

        stop_btn.click(_cancel, inputs=[job_state], outputs=[job_state, status_text])

        def _poll_and_render(curr: Dict[str, Any], api: str, ep: str):
            if not curr or not curr.get("job_id"):
                return gr.update(), gr.update(), gr.update(), gr.update()
            if curr.get("cancel"):
                return gr.update(), gr.update(), gr.update(), gr.update()

            job_id = curr["job_id"]
            pb = gr.Progress(track_tqdm=False)
            output, err = _poll_status_stream(api, ep, job_id, progress_bar=pb, logbox=logs)
            if err:
                return gr.update(value=f"Error: {err}"), gr.update(value=None), gr.update(visible=False, value=None), gr.update(value={})
            if not output:
                return gr.update(value="No output received."), gr.update(value=None), gr.update(visible=False, value=None), gr.update(value={})

            url, raw, mime = _pick_video_result(output)
            if url:
                # Serve remote URL directly in the player
                # Note: gr.Video can take a URL
                return gr.update(value=f"Completed job {job_id}"), gr.update(value=url), gr.update(visible=False, value=None), gr.update(value=output)
            if raw:
                tmp_path = _write_temp_video(raw, suffix=".mp4")
                return gr.update(value=f"Completed job {job_id}"), gr.update(value=tmp_path), gr.update(visible=True, value=tmp_path), gr.update(value=output)

            # If artifacts not found, still show JSON
            return gr.update(value=f"Completed job {job_id} (no video artifact detected)"), gr.update(value=None), gr.update(visible=False, value=None), gr.update(value=output)

        # Background polling: trigger after submit and also by a Timer until terminal or cancel
        poll_timer = gr.Timer(POLL_INIT_SEC, active=True)
        poll_timer.tick(_poll_and_render, inputs=[job_state, api_key, endpoint_id], outputs=[status_text, result_video, download_file, artifacts_json])

    return demo


def main():
    demo = build_ui()
    demo.queue().launch(server_name="0.0.0.0", server_port=7860, inbrowser=False, share=False)


if __name__ == "__main__":
    main()