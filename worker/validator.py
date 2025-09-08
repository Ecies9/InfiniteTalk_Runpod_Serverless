from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, HttpUrl, ValidationError, field_validator, model_validator

# Validation and schema models for worker input/output.
# Follows the plan in ARCHITECTURE.md section 3 and 4.

SIZE_ENUM = Literal["infinitetalk-480", "infinitetalk-720"]
MODE_ENUM = Literal["clip", "streaming"]
AUDIO_MODE_ENUM = Literal["para", "add"]
STORE_ENUM = Literal["s3", "volume", "inline"]
QUANT_ENUM = Optional[Literal["int8", "fp8"]]


class OutputConfig(BaseModel):
    store: STORE_ENUM = Field(default="s3")
    bucket: Optional[str] = None
    region: Optional[str] = None
    prefix: Optional[str] = None
    # For inline results, base64-embed result (small only)
    # For S3 or volume, worker will upload or write to path.


class TtsAudio(BaseModel):
    text: str = Field(min_length=1)
    human1_voice: Optional[str] = None
    human2_voice: Optional[str] = None


class CondAudio(BaseModel):
    # URLs/Base64/path accepted; raw strings validated downstream
    person1: Optional[str] = None
    person2: Optional[str] = None


class SingleInput(BaseModel):
    prompt: str = Field(min_length=1)
    cond_video: str  # URL/base64/path; image or video

    # Either cond_audio or tts_audio must be provided
    cond_audio: Optional[CondAudio] = None
    tts_audio: Optional[TtsAudio] = None

    audio_type: Optional[AUDIO_MODE_ENUM] = None  # only applies to two speakers
    bbox: Optional[List[int]] = None  # [x1,y1,x2,y2]

    # Generation params
    size: SIZE_ENUM = "infinitetalk-480"
    mode: MODE_ENUM = "clip"
    frame_num: int = 81
    max_frame_num: int = 1000
    sample_steps: int = 40
    sample_text_guide_scale: float = 5.0
    sample_audio_guide_scale: float = 4.0
    motion_frame: int = 9
    color_correction_strength: float = 1.0
    use_teacache: bool = False
    teacache_thresh: float = 0.2
    use_apg: bool = False
    apg_momentum: float = -0.75
    apg_norm_threshold: float = 55.0
    base_seed: int = 42
    num_persistent_param_in_dit: Optional[int] = None
    offload_model: Optional[bool] = None
    quant: QUANT_ENUM = None
    quant_dir: Optional[str] = None

    # Derived/advanced
    n_prompt: Optional[str] = None  # accepted but not required

    output_config: OutputConfig = Field(default_factory=OutputConfig)

    @field_validator("frame_num")
    @classmethod
    def validate_frame_num_4n_plus_1(cls, v: int) -> int:
        if v <= 0 or (v - 1) % 4 != 0:
            raise ValueError("frame_num must be 4n+1 and positive")
        return v

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is None:
            return v
        if len(v) != 4 or any(type(x) is not int for x in v):
            raise ValueError("bbox must be an array of 4 integers [x1,y1,x2,y2]")
        return v

    @model_validator(mode="after")
    def validate_audio_refs(self):
        # Require at least one of cond_audio or tts_audio
        if self.cond_audio is None and self.tts_audio is None:
            raise ValueError("Either cond_audio or tts_audio must be provided.")

        # If two speakers, audio_type must be set
        if self.cond_audio is not None:
            p1 = self.cond_audio.person1
            p2 = self.cond_audio.person2
            if p2 is not None and self.audio_type is None:
                raise ValueError("audio_type is required when two speakers are provided (person1 & person2).")

        # Quant requires quant_dir
        if self.quant is not None and not self.quant_dir:
            raise ValueError("quant_dir must be provided when quant is set.")

        return self


class BatchInput(BaseModel):
    id: Optional[str] = None
    # Payload is identical to SingleInput except output_config can be on the batch envelope
    prompt: str
    cond_video: str
    cond_audio: Optional[CondAudio] = None
    tts_audio: Optional[TtsAudio] = None
    audio_type: Optional[AUDIO_MODE_ENUM] = None
    bbox: Optional[List[int]] = None
    size: SIZE_ENUM = "infinitetalk-480"
    mode: MODE_ENUM = "clip"
    frame_num: int = 81
    max_frame_num: int = 1000
    sample_steps: int = 40
    sample_text_guide_scale: float = 5.0
    sample_audio_guide_scale: float = 4.0
    motion_frame: int = 9
    color_correction_strength: float = 1.0
    use_teacache: bool = False
    teacache_thresh: float = 0.2
    use_apg: bool = False
    apg_momentum: float = -0.75
    apg_norm_threshold: float = 55.0
    base_seed: int = 42
    num_persistent_param_in_dit: Optional[int] = None
    offload_model: Optional[bool] = None
    quant: QUANT_ENUM = None
    quant_dir: Optional[str] = None
    n_prompt: Optional[str] = None

    @field_validator("frame_num")
    @classmethod
    def validate_frame_num_4n_plus_1(cls, v: int) -> int:
        if v <= 0 or (v - 1) % 4 != 0:
            raise ValueError("frame_num must be 4n+1 and positive")
        return v

    @model_validator(mode="after")
    def validate_audio_refs(self):
        if self.cond_audio is None and self.tts_audio is None:
            raise ValueError("Either cond_audio or tts_audio must be provided.")
        if self.cond_audio is not None and self.cond_audio.person2 is not None and self.audio_type is None:
            raise ValueError("audio_type is required when two speakers are provided (person1 & person2).")
        if self.quant is not None and not self.quant_dir:
            raise ValueError("quant_dir must be provided when quant is set.")
        return self


class EnvelopeInput(BaseModel):
    # Either "input" is a SingleInput-like object OR has "batch": [items...]
    input: Dict[str, Any]
    policy: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def check_single_or_batch(self):
        payload = self.input
        if "batch" in payload:
            # Validate each item as BatchInput; output_config may be on the envelope too
            items = payload["batch"]
            if not isinstance(items, list) or len(items) == 0:
                raise ValueError("batch must be a non-empty array of input objects.")
            for it in items:
                BatchInput.model_validate(it)
        else:
            # Validate as SingleInput
            SingleInput.model_validate(payload)
        return self


# Output schemas

class Artifact(BaseModel):
    type: Literal["video", "thumbnail", "metadata"]
    url: Optional[str] = None
    path: Optional[str] = None
    mime: Optional[str] = None
    bytes: Optional[int] = None


class SuccessOutput(BaseModel):
    job_id: str
    status: Literal["success"]
    video: Optional[Dict[str, Any]] = None  # primary video quick access
    timings: Dict[str, Any]
    params: Dict[str, Any]
    logs: Optional[List[Dict[str, Any]]] = None
    artifacts: List[Artifact] = Field(default_factory=list)
    warnings: Optional[List[str]] = None
    checkpoints: Optional[List[Dict[str, Any]]] = None


class ErrorDetails(BaseModel):
    code: str
    message: str
    retryable: bool
    at_stage: Optional[str] = None
    cause_class: Optional[str] = None
    cause_message: Optional[str] = None


class ErrorOutput(BaseModel):
    job_id: str
    status: Literal["error", "failed", "FAILED"]
    error: ErrorDetails
    diagnostics: Optional[Dict[str, Any]] = None
    timings: Optional[Dict[str, Any]] = None
    checkpoints: Optional[List[Dict[str, Any]]] = None


def load_defaults(path: str) -> Dict[str, Any]:
    # Minimal YAML loader to avoid hard dependency; simple subset
    try:
        import yaml  # type: ignore
    except Exception:
        return {}
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def apply_defaults_to_single(single: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    merged = {**defaults.get("generation", {}), **single}
    if "output_config" not in merged and "output" in defaults:
        merged["output_config"] = defaults["output"]
    return merged


def normalize_and_validate(envelope: Dict[str, Any], defaults: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    defaults = defaults or {}
    env = EnvelopeInput.model_validate(envelope)

    payload = env.input
    if "batch" in payload:
        items = payload["batch"]
        normalized_items: List[Dict[str, Any]] = []
        for it in items:
            norm = apply_defaults_to_single(it, defaults)
            BatchInput.model_validate(norm)
            normalized_items.append(norm)
        result = {"batch": normalized_items}
        # Carry envelope-level output_config override
        if "output_config" in payload:
            result["output_config"] = payload["output_config"]
        return result
    else:
        norm = apply_defaults_to_single(payload, defaults)
        SingleInput.model_validate(norm)
        return norm


def build_error(code: str, message: str, retryable: bool, at_stage: Optional[str] = None, exc: Optional[BaseException] = None) -> Dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "retryable": retryable,
        "at_stage": at_stage,
        "cause_class": type(exc).__name__ if exc else None,
        "cause_message": str(exc) if exc else None,
    }