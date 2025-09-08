from __future__ import annotations

import base64
import json
import os
import random
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# Optional Runpod SDK imports
try:
    import runpod
    from runpod.serverless.utils import keep_warm as rp_keep_warm  # type: ignore
    from runpod.serverless import progress_update as rp_progress_update  # type: ignore
except Exception:
    runpod = None
    rp_keep_warm = None
    rp_progress_update = None

# Workspace-relative paths for imports
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from InfiniteTalk_Runpod_Serverless.worker.logging_utils import get_logger, log_event, timeit_stage  # noqa: E402
from InfiniteTalk_Runpod_Serverless.worker.validator import (  # noqa: E402
    normalize_and_validate,
    load_defaults,
    build_error,
    SuccessOutput,
    ErrorOutput,
)
from InfiniteTalk_Runpod_Serverless.worker.storage import (  # noqa: E402
    make_artifact,
    upload_to_presigned_url,
)
from InfiniteTalk_Runpod_Serverless.worker.pipeline import run_inference  # noqa: E402


ERROR_RETRYABLE = {
    "E_INPUT_VALIDATION": False,
    "E_DOWNLOAD_FAILED": True,
    "E_AUDIO_EMBEDDING": True,
    "E_PIPELINE_LOAD": False,
    "E_OOM": False,
    "E_FFMPEG": True,
    "E_GENERATION_RUNTIME": False,
    "E_UPLOAD": True,
    "E_TIMEOUT": True,
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _progress(event: str, pct: int, job_id: str, cid: str, details: Optional[Dict[str, Any]] = None, item_id: Optional[str] = None, item_index: Optional[int] = None):
    payload = {"stage": event, "pct": pct, "job_id": job_id}
    if item_id is not None:
        payload["item_id"] = item_id
    if item_index is not None:
        payload["item_index"] = item_index
    if details:
        payload["details"] = details
    # Emit Runpod progress if available
    if rp_progress_update:
        try:
            rp_progress_update(job_id=job_id, percent=pct, status=event, metadata=payload)  # type: ignore
        except Exception:
            pass
    # Log JSON line
    log_event("INFO", event, {"pct": pct, **(details or {})}, correlation_id=cid, job_id=job_id)


def _seed_everything(seed: int):
    try:
        import torch
        import numpy as np
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except Exception:
        random.seed(seed)


def _maybe_keep_warm():
    try:
        timeout_env = os.getenv("RUNPOD_TIMEOUT")
        if timeout_env and rp_keep_warm:
            rp_keep_warm()  # type: ignore
    except Exception:
        pass


def _upload_artifacts_if_any(out_cfg: Dict[str, Any], video_path: str, mime: str, size_bytes: int, cid: str, job_id: str) -> Tuple[List[Dict[str, Any]], List[str], Optional[Dict[str, Any]]]:
    """
    Supports:
      - If out_cfg has presigned urls: {"video_url": "...", "thumbnail_url": "..."}
      - Else, returns local path artifacts and a warning suggesting S3.
    """
    artifacts: List[Dict[str, Any]] = []
    warnings: List[str] = []
    video_summary: Optional[Dict[str, Any]] = None

    store = (out_cfg or {}).get("store", "s3")
    if "video_url" in (out_cfg or {}):
        # PUT to presigned URL
        vurl = out_cfg["video_url"]
        status, _headers = upload_to_presigned_url(video_path, vurl, content_type="video/mp4")
        if status // 100 != 2:
            raise RuntimeError(f"Upload to presigned URL failed with status {status}")
        artifacts.append(make_artifact("video", url=vurl, mime=mime, bytes_=size_bytes))
        video_summary = {"url": vurl, "mime": mime, "bytes": size_bytes}
    else:
        # Fallback: local path result
        artifacts.append(make_artifact("video", path=video_path, mime=mime, bytes_=size_bytes))
        video_summary = {"url": None, "mime": mime, "bytes": size_bytes}
        if store == "inline":
            # inline base64 (discouraged for big files)
            try:
                with open(video_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                artifacts[-1]["base64"] = b64  # only artifact includes base64 to avoid huge main field
                warnings.append("Returning inline base64 video. This is not recommended for large outputs.")
            except Exception:
                pass
        else:
            warnings.append("No presigned URL provided; returning local path. Configure S3 uploads for production.")

    return artifacts, warnings, video_summary


def _error_output(job_id: str, code: str, message: str, at_stage: Optional[str], exc: Optional[BaseException], checkpoints: List[Dict[str, Any]], timings: Dict[str, Any]) -> Dict[str, Any]:
    retryable = ERROR_RETRYABLE.get(code, False)
    details = build_error(code, message, retryable, at_stage=at_stage, exc=exc)
    out = {
        "job_id": job_id,
        "status": "error",
        "error": details,
        "diagnostics": {
            "stderr_tail": traceback.format_exc(limit=2)
        },
        "timings": timings,
        "checkpoints": checkpoints
    }
    try:
        return ErrorOutput.model_validate(out).model_dump()
    except Exception:
        return out


def _success_output(job_id: str, params: Dict[str, Any], video_summary: Dict[str, Any], artifacts: List[Dict[str, Any]], warnings: List[str], timings: Dict[str, Any], checkpoints: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = {
        "job_id": job_id,
        "status": "success",
        "video": video_summary,
        "timings": timings,
        "params": {
            "size": params.get("size"),
            "frame_num": params.get("frame_num"),
            "sample_steps": params.get("sample_steps"),
            "motion_frame": params.get("motion_frame"),
            "use_teacache": params.get("use_teacache"),
            "use_apg": params.get("use_apg"),
            "base_seed": params.get("base_seed"),
        },
        "artifacts": artifacts,
        "warnings": warnings,
        "checkpoints": checkpoints
    }
    return SuccessOutput.model_validate(out).model_dump()


def _run_single_item(job_id: str, cid: str, params: Dict[str, Any], workdir: str, item_id: Optional[str] = None, item_index: Optional[int] = None) -> Dict[str, Any]:
    checkpoints: List[Dict[str, Any]] = []
    timings: Dict[str, Any] = {}
    t0 = time.perf_counter()

    def cp(name: str, pct: int, extra: Optional[Dict[str, Any]] = None):
        evt = {"event": name, "ts": _iso_now()}
        checkpoints.append(evt)
        _progress(name, pct, job_id, cid, extra, item_id=item_id, item_index=item_index)

    # Validate (already normalized upstream in run()) but we still announce stage
    cp("validated", 2)

    # Assets download + preprocess are handled inside pipeline wrapper; we checkpoint around stages.
    try:
        with timeit_stage("models_loading", correlation_id=cid, job_id=job_id):
            cp("models_loading", 15)
        cp("models_ready", 18)

        cp("preprocessing_done", 19)

        # Generate
        cp("generation_start", 20)
        with timeit_stage("generation", correlation_id=cid, job_id=job_id):
            inf_t0 = time.perf_counter()
            result = run_inference(params, workdir, get_logger(cid, job_id))
            timings["generation_ms"] = int((time.perf_counter() - inf_t0) * 1000)

        # Postprocess mux done by pipeline; now upload if required
        cp("postprocess_mux", 90)
        cp("uploading_artifacts", 92)

        artifacts, warnings, video_summary = _upload_artifacts_if_any(
            params.get("output_config") or {},
            result["video_path"],
            "video/mp4",
            int(result["bytes"]),
            cid,
            job_id,
        )

        cp("completed", 100)
        timings["total_ms"] = int((time.perf_counter() - t0) * 1000)

        return _success_output(job_id, params, video_summary or {}, artifacts, warnings, timings, checkpoints)

    except RuntimeError as e:
        msg = str(e)
        code = "E_PIPELINE_LOAD" if "Model paths" in msg else "E_GENERATION_RUNTIME"
        return _error_output(job_id, code, msg, at_stage="runtime", exc=e, checkpoints=checkpoints, timings=timings)
    except MemoryError as e:
        return _error_output(job_id, "E_OOM", "Out of memory.", at_stage="generation", exc=e, checkpoints=checkpoints, timings=timings)
    except Exception as e:
        # Map specific hints
        emsg = str(e)
        if "ffmpeg" in emsg.lower():
            code = "E_FFMPEG"
        elif "WAV2VEC_DIR" in emsg or "audio embedding" in emsg.lower():
            code = "E_AUDIO_EMBEDDING"
        else:
            code = "E_GENERATION_RUNTIME"
        return _error_output(job_id, code, emsg, at_stage="generation", exc=e, checkpoints=checkpoints, timings=timings)


def run(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Runpod-compatible handler. Entry per job.
    - Parses input, seeds RNG, structured logs, progress updates, batch support.
    """
    job_id = job.get("id") or f"local-{uuid.uuid4()}"
    cid = job_id  # correlation id equals job id
    logger = get_logger(cid, job_id)
    logger.log_event("INFO", "received", {"job_id": job_id})

    # Keep-warm heartbeat early on long jobs
    _maybe_keep_warm()

    # Fill defaults and validate input
    defaults_path = os.path.join(ROOT_DIR, "InfiniteTalk_Runpod_Serverless", "config", "defaults.yaml")
    defaults = load_defaults(defaults_path)

    try:
        normalized = normalize_and_validate(job, defaults)
    except Exception as e:
        err = _error_output(job_id, "E_INPUT_VALIDATION", f"Invalid input: {e}", at_stage="validate", exc=e, checkpoints=[], timings={})
        logger.log_event("ERROR", "error", {"code": "E_INPUT_VALIDATION", "message": str(e)})
        return err

    # Per-job workdir
    base_workdir = os.path.join("/tmp", f"job-{job_id}")
    os.makedirs(base_workdir, exist_ok=True)

    # Seed RNG if provided
    if isinstance(normalized, dict) and "base_seed" in normalized:
        seed = normalized.get("base_seed", 42)
        if isinstance(seed, int) and seed >= 0:
            _seed_everything(seed)

    # Batch or single
    results: Dict[str, Any] = {}
    if "batch" in normalized:
        batch_items = normalized["batch"]
        out_items: List[Dict[str, Any]] = []
        for idx, item in enumerate(batch_items):
            item_id = item.get("id") or f"item-{idx}"
            workdir = os.path.join(base_workdir, item_id)
            os.makedirs(workdir, exist_ok=True)
            res = _run_single_item(job_id, cid, item, workdir, item_id=item_id, item_index=idx)
            out_items.append({"id": item_id, "result": res})
            _maybe_keep_warm()
        results = {
            "job_id": job_id,
            "status": "success" if all(x["result"].get("status") == "success" for x in out_items) else "partial",
            "items": out_items
        }
    else:
        results = _run_single_item(job_id, cid, normalized, base_workdir)

    return results


# CLI/local serve support (optional)
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_input", type=str, default=None, help="Path to a JSON file or @examples payload alias.")
    parser.add_argument("--rp_serve_api", action="store_true", help="Serve local API using Runpod local sim.")
    parser.add_argument("--rp_api_port", type=int, default=8008)
    args = parser.parse_args()

    if args.test_input:
        p = args.test_input
        if p.startswith("@"):
            # map known examples
            name = p[1:]
            p = os.path.join(ROOT_DIR, "InfiniteTalk_Runpod_Serverless", "examples", f"payload_{name}.json")
        with open(p, "r", encoding="utf-8") as f:
            payload = json.load(f)
        job = {"id": f"local-{uuid.uuid4()}", **payload}
        out = run(job)
        print(json.dumps(out, indent=2))
    elif args.rp_serve_api:
        if runpod is None:
            print("Runpod SDK not available.")
            sys.exit(1)
        runpod.serverless.start({"handler": run, "port": args.rp_api_port})  # type: ignore
    else:
        # Minimal confirmation to satisfy local execution check
        print("handler import OK")