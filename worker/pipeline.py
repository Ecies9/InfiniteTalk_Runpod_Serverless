from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple

import torch
import numpy as np
from PIL import Image

# Ensure upstream repo is on sys.path (idempotent, before importing upstream modules)
import sys
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
UPSTREAM_DIR = os.path.join(ROOT_DIR, "InfiniteTalk-main")
if UPSTREAM_DIR not in sys.path:
    sys.path.insert(0, UPSTREAM_DIR)

# Upstream imports (do not modify upstream repo)
import wan
from wan.configs import WAN_CONFIGS
from wan.utils.utils import is_video
from wan.utils.multitalk_utils import save_video_ffmpeg

# Reuse utilities from upstream generator
from generate_infinitetalk import (
    custom_init,
    get_embedding,
    audio_prepare_single,
    audio_prepare_multi,
)

# Local helpers
from .storage import download_from_url, save_temp
from .logging_utils import JsonLogger


def _env(key: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(key, default)
    return v


def _resolve_model_paths() -> Dict[str, Optional[str]]:
    return {
        "ckpt_dir": _env("CKPT_DIR"),
        "infinitetalk_dir": _env("INFINITETALK_DIR"),
        "wav2vec_dir": _env("WAV2VEC_DIR"),
        "quant_dir": _env("QUANT_DIR"),
        "dit_path": _env("DIT_PATH"),
    }


def _prepare_inputs(params: Dict[str, Any], workdir: str, logger: JsonLogger) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Downloads/decodes inputs and prepares:
    - input_data to feed generate_infinitetalk (embeddings paths, audio mux path, cond_video path)
    - meta summary (bytes, mime info)
    """
    meta: Dict[str, Any] = {"downloads": {}}
    input_data: Dict[str, Any] = {
        "prompt": params["prompt"],
    }

    # cond_video may be image or video; save locally
    vid_res = download_from_url(params["cond_video"], workdir, filename="cond_video")
    input_data["cond_video"] = vid_res.path
    meta["downloads"]["cond_video"] = {"bytes": vid_res.bytes, "mime": vid_res.mime}

    # Audio selection: tts or local files; this wrapper handles only local files in this worker,
    # TTS to be precomputed externally or handled via upstream Kokoro if desired later.
    # Here we support:
    # - cond_audio.person1 [+ person2], with optional audio_type = "para" | "add"
    cond_audio = params.get("cond_audio")
    tts_audio = params.get("tts_audio")
    audio_type = params.get("audio_type")

    audio_save_dir = os.path.join(workdir, "audio")
    os.makedirs(audio_save_dir, exist_ok=True)

    # Prepare wav2vec feature extractor and encoder (CPU per upstream)
    model_paths = _resolve_model_paths()
    if not model_paths["wav2vec_dir"]:
        raise RuntimeError("WAV2VEC_DIR env var is required for audio embedding.")
    wav2vec_feature_extractor, audio_encoder = custom_init("cpu", model_paths["wav2vec_dir"])

    if cond_audio and cond_audio.get("person1"):
        # Single or multi speaker local/URL/base64
        if cond_audio.get("person2") is not None:
            # Two speakers
            # Download inputs first
            p1 = download_from_url(cond_audio["person1"], workdir, filename="p1")
            p2 = download_from_url(cond_audio["person2"], workdir, filename="p2")
            meta["downloads"]["person1"] = {"bytes": p1.bytes, "mime": p1.mime}
            meta["downloads"]["person2"] = {"bytes": p2.bytes, "mime": p2.mime}

            # Prepare arrays
            s1, s2, sum_arr = audio_prepare_multi(p1.path, p2.path, audio_type or "para")
            # Embeddings
            emb1 = get_embedding(s1, wav2vec_feature_extractor, audio_encoder)
            emb2 = get_embedding(s2, wav2vec_feature_extractor, audio_encoder)
            emb1_path = os.path.join(audio_save_dir, "1.pt")
            emb2_path = os.path.join(audio_save_dir, "2.pt")
            torch.save(emb1, emb1_path)
            torch.save(emb2, emb2_path)

            # Save sum audio for mux
            sum_audio = os.path.join(audio_save_dir, "sum.wav")
            import soundfile as sf  # local dep
            sf.write(sum_audio, sum_arr, 16000)

            input_data["cond_audio"] = {"person1": emb1_path, "person2": emb2_path}
            input_data["audio_type"] = audio_type or "para"
            input_data["video_audio"] = sum_audio
        else:
            # Single speaker
            p1 = download_from_url(cond_audio["person1"], workdir, filename="p1")
            meta["downloads"]["person1"] = {"bytes": p1.bytes, "mime": p1.mime}
            s1 = audio_prepare_single(p1.path)
            emb1 = get_embedding(s1, wav2vec_feature_extractor, audio_encoder)
            emb1_path = os.path.join(audio_save_dir, "1.pt")
            torch.save(emb1, emb1_path)
            # Save sum audio (original speech) for mux
            sum_audio = os.path.join(audio_save_dir, "sum.wav")
            import soundfile as sf
            sf.write(sum_audio, s1, 16000)

            input_data["cond_audio"] = {"person1": emb1_path}
            input_data["video_audio"] = sum_audio
    elif tts_audio and tts_audio.get("text"):
        # Not implementing Kokoro flow inside worker in this version to keep footprint low.
        # Expect caller to provide pre-generated audio URLs if using TTS.
        raise NotImplementedError("tts_audio is not supported in this worker build. Provide cond_audio instead.")
    else:
        raise ValueError("cond_audio or tts_audio must be provided.")

    if "bbox" in params:
        input_data["bbox"] = params["bbox"]

    return input_data, meta


def _build_pipeline(params: Dict[str, Any], logger: JsonLogger):
    cfg = WAN_CONFIGS["infinitetalk-14B"]
    model_paths = _resolve_model_paths()
    if not model_paths["ckpt_dir"] or not model_paths["infinitetalk_dir"]:
        raise RuntimeError("Model paths CKPT_DIR and INFINITETALK_DIR must be set in environment.")

    # Device selection
    local_rank = int(os.getenv("LOCAL_RANK", "0"))
    device_id = local_rank

    wan_i2v = wan.InfiniteTalkPipeline(
        config=cfg,
        checkpoint_dir=model_paths["ckpt_dir"],
        quant_dir=model_paths["quant_dir"],
        device_id=device_id,
        rank=int(os.getenv("RANK", "0")),
        t5_fsdp=False,
        dit_fsdp=False,
        use_usp=False,
        t5_cpu=False,
        lora_dir=None,
        lora_scales=None,
        quant=os.getenv("QUANT", None),
        dit_path=model_paths["dit_path"],
        infinitetalk_dir=model_paths["infinitetalk_dir"],
    )
    # VRAM mgmt from params if provided
    if params.get("num_persistent_param_in_dit") is not None:
        wan_i2v.vram_management = True
        wan_i2v.enable_vram_management(
            num_persistent_param_in_dit=params["num_persistent_param_in_dit"]
        )
    return wan_i2v


def _run_generate(wan_i2v, input_data: Dict[str, Any], params: Dict[str, Any], logger: JsonLogger):
    # Map params to upstream API
    size_buckget = params["size"]
    motion_frame = params.get("motion_frame", 9)
    frame_num = params.get("frame_num", 81)
    shift = 7 if size_buckget == "infinitetalk-480" else 11
    sampling_steps = params.get("sample_steps", 40)
    text_guide_scale = params.get("sample_text_guide_scale", 5.0)
    audio_guide_scale = params.get("sample_audio_guide_scale", 4.0)
    seed = params.get("base_seed", 42)
    offload_model = params.get("offload_model", True)
    max_frames_num = frame_num if params.get("mode", "clip") == "clip" else params.get("max_frame_num", 1000)
    color_correction_strength = params.get("color_correction_strength", 1.0)

    video = wan_i2v.generate_infinitetalk(
        input_data,
        size_buckget=size_buckget,
        motion_frame=motion_frame,
        frame_num=frame_num,
        shift=shift,
        sampling_steps=sampling_steps,
        text_guide_scale=text_guide_scale,
        audio_guide_scale=audio_guide_scale,
        seed=seed,
        offload_model=offload_model,
        max_frames_num=max_frames_num,
        color_correction_strength=color_correction_strength,
        extra_args=None,
    )
    return video


def run_inference(params: Dict[str, Any], workdir: str, logger: JsonLogger) -> Dict[str, Any]:
    """
    Executes the full inference:
    - download/preprocess
    - build/load models
    - generation
    - mux and save mp4
    Returns:
      {
        "video_path": "...mp4",
        "thumbnail_path": Optional[str],
        "bytes": int,
        "meta": {...}
      }
    """
    os.makedirs(workdir, exist_ok=True)

    # Preprocess
    input_data, meta = _prepare_inputs(params, workdir, logger)

    # Load models
    wan_i2v = _build_pipeline(params, logger)

    # Generate
    try:
        video = _run_generate(wan_i2v, input_data, params, logger)
    except torch.cuda.OutOfMemoryError as e:
        # Retry once with reduced settings
        reduce = params.copy()
        reduce["size"] = "infinitetalk-480"
        reduce["sample_steps"] = min(8, int(params.get("sample_steps", 40)))
        logger.warn("oom_retry", {"size": reduce["size"], "sample_steps": reduce["sample_steps"]})
        wan_i2v = _build_pipeline(reduce, logger)
        video = _run_generate(wan_i2v, input_data, reduce, logger)
    # Save mp4 via ffmpeg
    save_name = f"infitalk_{params.get('size','infinitetalk-480')}_{params.get('sample_steps',40)}_seed{params.get('base_seed',42)}"
    save_path_noext = os.path.join(workdir, save_name)
    save_video_ffmpeg(video, save_path_noext, [input_data["video_audio"]], high_quality_save=False)
    mp4_path = save_path_noext + ".mp4"

    # Thumbnail (first frame) optional - upstream util may have, else skip
    thumb_path: Optional[str] = None
    try:
        # Simple lightweight grabs via torchvision.io is heavy; skip by default
        pass
    except Exception:
        thumb_path = None

    bytes_len = os.path.getsize(mp4_path)
    return {
        "video_path": mp4_path,
        "thumbnail_path": thumb_path,
        "bytes": bytes_len,
        "meta": meta,
    }