from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

import yaml  # pyyaml
import gradio as gr

# Parameter widgets consistent with config/defaults.yaml and worker/validator.py
# Exposes:
# - build_param_widgets()
# - collect_params_from_widgets(widgets)


DEFAULTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "defaults.yaml"
)


def _load_defaults() -> Dict[str, Any]:
    try:
        if os.path.exists(DEFAULTS_PATH):
            with open(DEFAULTS_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    # Fallback sane defaults mirroring validator defaults
    return {
        "generation": {
            "size": "infinitetalk-480",
            "mode": "clip",
            "frame_num": 81,
            "max_frame_num": 1000,
            "sample_steps": 40,
            "sample_text_guide_scale": 5.0,
            "sample_audio_guide_scale": 4.0,
            "motion_frame": 9,
            "color_correction_strength": 1.0,
            "use_teacache": False,
            "teacache_thresh": 0.2,
            "use_apg": False,
            "apg_momentum": -0.75,
            "apg_norm_threshold": 55.0,
            "base_seed": 42,
            "num_persistent_param_in_dit": None,
            "offload_model": True,
            "quant": None,
            "quant_dir": None,
        },
        "output": {
            "store": "s3",
        },
    }


def _multiple_of_8(v: int) -> bool:
    return v % 8 == 0


def build_param_widgets() -> Tuple[Dict[str, gr.components.Component], gr.Group]:
    """
    Create Gradio widgets for parameters and return:
    (widgets_dict, container_group)
    """
    defaults = _load_defaults()
    g = defaults.get("generation", {})
    # Enums
    SIZE_OPTS = ["infinitetalk-480", "infinitetalk-720"]
    MODE_OPTS = ["clip", "streaming"]
    STORE_OPTS = ["s3", "volume", "inline"]
    QUANT_OPTS = [None, "int8", "fp8"]

    with gr.Group() as params_group:
        with gr.Row():
            size = gr.Dropdown(
                label="Size",
                choices=SIZE_OPTS,
                value=g.get("size", "infinitetalk-480"),
                info="Resolution preset",
            )
            mode = gr.Radio(
                label="Mode",
                choices=MODE_OPTS,
                value=g.get("mode", "clip"),
                info="clip for short fixed length; streaming for longer",
            )
            sample_steps = gr.Slider(
                label="Sampling Steps",
                minimum=1,
                maximum=1000,
                step=1,
                value=int(g.get("sample_steps", 40)),
            )
        with gr.Row():
            frame_num = gr.Number(
                label="Frame Num (4n+1)",
                value=int(g.get("frame_num", 81)),
                precision=0,
                info="Must be 4n+1 and positive",
            )
            max_frame_num = gr.Number(
                label="Max Frame Num (streaming)",
                value=int(g.get("max_frame_num", 1000)),
                precision=0,
            )
            motion_frame = gr.Number(
                label="Motion Frame",
                value=int(g.get("motion_frame", 9)),
                precision=0,
            )

        with gr.Row():
            sample_text_guide_scale = gr.Slider(
                label="Text Guidance Scale",
                minimum=0.0,
                maximum=20.0,
                step=0.1,
                value=float(g.get("sample_text_guide_scale", 5.0)),
            )
            sample_audio_guide_scale = gr.Slider(
                label="Audio Guidance Scale",
                minimum=0.0,
                maximum=20.0,
                step=0.1,
                value=float(g.get("sample_audio_guide_scale", 4.0)),
            )
            color_correction_strength = gr.Slider(
                label="Color Correction Strength",
                minimum=0.0,
                maximum=1.0,
                step=0.05,
                value=float(g.get("color_correction_strength", 1.0)),
            )

        with gr.Row():
            use_teacache = gr.Checkbox(
                label="Use TeaCache",
                value=bool(g.get("use_teacache", False)),
            )
            teacache_thresh = gr.Slider(
                label="TeaCache Threshold",
                minimum=0.0,
                maximum=1.0,
                step=0.05,
                value=float(g.get("teacache_thresh", 0.2)),
            )
            use_apg = gr.Checkbox(
                label="Use APG",
                value=bool(g.get("use_apg", False)),
            )
        with gr.Row():
            apg_momentum = gr.Slider(
                label="APG Momentum",
                minimum=-2.0,
                maximum=2.0,
                step=0.05,
                value=float(g.get("apg_momentum", -0.75)),
            )
            apg_norm_threshold = gr.Number(
                label="APG Norm Threshold",
                value=float(g.get("apg_norm_threshold", 55.0)),
            )
            base_seed = gr.Number(
                label="Base Seed (-1 for random)",
                value=int(g.get("base_seed", 42)),
                precision=0,
            )

        with gr.Accordion("Advanced VRAM/Quantization", open=False):
            num_persistent_param_in_dit = gr.Number(
                label="num_persistent_param_in_dit",
                value=(g.get("num_persistent_param_in_dit") if g.get("num_persistent_param_in_dit") is not None else 0),
                precision=0,
                info="Set 0 to enable VRAM management on constrained GPUs",
            )
            offload_model = gr.Checkbox(
                label="Offload Model (single GPU default)",
                value=bool(g.get("offload_model", True)),
            )
            quant = gr.Dropdown(
                label="Quantization",
                choices=[str(x) if x is not None else "none" for x in QUANT_OPTS],
                value=("none" if g.get("quant") in (None, "None") else g.get("quant")),
            )
            quant_dir = gr.Textbox(
                label="Quant Dir (required if quant set)",
                value=g.get("quant_dir") or "",
            )

        with gr.Accordion("Output Config", open=False):
            store = gr.Radio(
                label="Output Store",
                choices=STORE_OPTS,
                value=(defaults.get("output", {}).get("store", "s3")),
            )
            bucket = gr.Textbox(label="Bucket (if using S3)", value="")
            region = gr.Textbox(label="Region (if using S3)", value="")
            prefix = gr.Textbox(label="Prefix (optional)", value="")

    widgets: Dict[str, gr.components.Component] = {
        "size": size,
        "mode": mode,
        "frame_num": frame_num,
        "max_frame_num": max_frame_num,
        "sample_steps": sample_steps,
        "sample_text_guide_scale": sample_text_guide_scale,
        "sample_audio_guide_scale": sample_audio_guide_scale,
        "motion_frame": motion_frame,
        "color_correction_strength": color_correction_strength,
        "use_teacache": use_teacache,
        "teacache_thresh": teacache_thresh,
        "use_apg": use_apg,
        "apg_momentum": apg_momentum,
        "apg_norm_threshold": apg_norm_threshold,
        "base_seed": base_seed,
        "num_persistent_param_in_dit": num_persistent_param_in_dit,
        "offload_model": offload_model,
        "quant": quant,
        "quant_dir": quant_dir,
        "output.store": store,
        "output.bucket": bucket,
        "output.region": region,
        "output.prefix": prefix,
    }

    return widgets, params_group


def _sanitize_quant(val: Any) -> Any:
    if isinstance(val, str) and val.lower() == "none":
        return None
    return val


def _validate_ranges(payload: Dict[str, Any]) -> Tuple[bool, str]:
    # Minimal sanity checks: frame_num 4n+1, fps range not directly set here, sample_steps bounds, seed int, etc.
    frame_num = int(payload.get("frame_num", 81))
    if frame_num <= 0 or (frame_num - 1) % 4 != 0:
        return False, "frame_num must be 4n+1 and positive."

    steps = int(payload.get("sample_steps", 40))
    if not (1 <= steps <= 1000):
        return False, "sample_steps must be within [1, 1000]."

    cc = float(payload.get("color_correction_strength", 1.0))
    if not (0.0 <= cc <= 1.0):
        return False, "color_correction_strength must be within [0.0, 1.0]."

    # Quant dependency
    if payload.get("quant") is not None and not payload.get("quant_dir"):
        return False, "quant_dir must be provided when quant is set."

    return True, ""


def collect_params_from_widgets(widgets: Dict[str, gr.components.Component]) -> Dict[str, Any]:
    """
    Read widget values and return dict ready for payload.
    """
    values = {k: (w.value if hasattr(w, "value") else None) for k, w in widgets.items()}

    payload: Dict[str, Any] = {
        "size": values.get("size"),
        "mode": values.get("mode"),
        "frame_num": int(values.get("frame_num") or 81),
        "max_frame_num": int(values.get("max_frame_num") or 1000),
        "sample_steps": int(values.get("sample_steps") or 40),
        "sample_text_guide_scale": float(values.get("sample_text_guide_scale") or 5.0),
        "sample_audio_guide_scale": float(values.get("sample_audio_guide_scale") or 4.0),
        "motion_frame": int(values.get("motion_frame") or 9),
        "color_correction_strength": float(values.get("color_correction_strength") or 1.0),
        "use_teacache": bool(values.get("use_teacache")),
        "teacache_thresh": float(values.get("teacache_thresh") or 0.2),
        "use_apg": bool(values.get("use_apg")),
        "apg_momentum": float(values.get("apg_momentum") or -0.75),
        "apg_norm_threshold": float(values.get("apg_norm_threshold") or 55.0),
        "base_seed": int(values.get("base_seed") or 42),
        "num_persistent_param_in_dit": int(values.get("num_persistent_param_in_dit") or 0),
        "offload_model": bool(values.get("offload_model")),
        "quant": _sanitize_quant(values.get("quant")),
        "quant_dir": (values.get("quant_dir") or None),
        "output_config": {
            "store": values.get("output.store"),
            "bucket": values.get("output.bucket") or None,
            "region": values.get("output.region") or None,
            "prefix": values.get("output.prefix") or None,
        },
    }

    ok, msg = _validate_ranges(payload)
    if not ok:
        raise ValueError(msg)

    return payload