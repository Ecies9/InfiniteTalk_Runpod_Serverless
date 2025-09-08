# InfiniteTalk on Runpod Serverless — Architecture

This document defines the end-to-end plan for deploying InfiniteTalk as a Runpod Serverless worker with a companion Gradio Web UI. It is specific to InfiniteTalk and draws only structural inspiration from the Multitalk template.

References to source functions:
- Pipeline orchestration: [Python.class InfiniteTalkPipeline()](InfiniteTalk-main/wan/multitalk.py:108)
- Core generation: [Python.function generate_infinitetalk()](InfiniteTalk-main/wan/multitalk.py:376)
- CLI runner and preprocessing: [Python.function generate()](InfiniteTalk-main/generate_infinitetalk.py:453)
- Audio embedding: [Python.function get_embedding()](InfiniteTalk-main/generate_infinitetalk.py:323)
- Gradio app: [Python.function run_graio_demo()](InfiniteTalk-main/app.py:431)
- Video muxing: [Python.function save_video_ffmpeg](InfiniteTalk-main/wan/utils/multitalk_utils.py:1)

Runpod worker SDK references:
- Start worker: [Python.function runpod.serverless.start()](runpod-python-main/runpod/serverless/__init__.py:136)
- Progress updates: [Python.function runpod.serverless.progress_update()](runpod-python-main/runpod/serverless/__init__.py:19)
- Validator: [Python.function rp_validator.validate()](runpod-python-main/runpod/serverless/utils/rp_validator.py:1)
- Download helpers: [Python.function rp_download.file()](runpod-python-main/runpod/serverless/utils/rp_download.py:108)
- Upload helpers (S3/bucket): [Python.function rp_upload.upload_file_to_bucket()](runpod-python-main/runpod/serverless/utils/rp_upload.py:215)


## 1) System Overview and Data Flow

Components
- Runpod Serverless Endpoint
  - Hosts a container with a worker that loads InfiniteTalk once and serves asynchronous jobs.
- Worker (Python)
  - On cold start: loads model weights and audio encoder; subsequent jobs reuse memory.
  - For each job: validates input, downloads inputs, computes audio embeddings if needed, runs [Python.function generate_infinitetalk()](InfiniteTalk-main/wan/multitalk.py:376), muxes audio, uploads artifacts, returns JSON result.
- Object Storage (S3-compatible or Runpod Network Volume)
  - Inputs may be user URLs; outputs are uploaded as artifacts. Prefer presigned URLs for client retrieval.
- Gradio Web UI
  - Collects API key + Endpoint ID, uploads media, sets parameters, submits jobs via /run, polls /status, previews results, allows download.

High-level sequence
1) Client (Gradio) submits job to Runpod /run with validated input payload.
2) Worker receives job, allocates per-job temp dir, downloads inputs.
3) Worker optionally computes audio embeddings (wav2vec2) for provided audio/TTS.
4) Worker calls [Python.function generate_infinitetalk()](InfiniteTalk-main/wan/multitalk.py:376) iteratively (clip or streaming) with progress updates.
5) Worker writes MP4 to /tmp and uploads artifact to S3/bucket; returns JSON with URLs, metadata, and logs.
6) Client polls until COMPLETED or FAILED and then renders the video inline.

Note on long videos
- Use mode=streaming with sliding windows; ensure endpoint execution timeout is sufficient. Prefer async jobs with polling over synchronous runs for stability.


## 2) Worker Design

Planned files
- Worker entry: [Python.file handler.py](InfiniteTalk_Runpod_Serverless/worker/handler.py)
- Validator schema: [Python.file schema.py](InfiniteTalk_Runpod_Serverless/worker/schema.py)
- Utilities: [Python.file io_utils.py](InfiniteTalk_Runpod_Serverless/worker/io_utils.py), [Python.file logging_utils.py](InfiniteTalk_Runpod_Serverless/worker/logging_utils.py)
- Requirements: [Python.file requirements.txt](InfiniteTalk_Runpod_Serverless/builder/requirements.txt)
- Dockerfile: [Dockerfile Dockerfile](InfiniteTalk_Runpod_Serverless/Dockerfile)

Lifecycle
- Init (module import)
  - Set up structured logger (JSON lines).
  - Resolve/prepare model cache paths.
  - Load InfiniteTalk pipeline once to GPU:
    - [Python.class InfiniteTalkPipeline()](InfiniteTalk-main/wan/multitalk.py:108) with args from environment variables.
  - Load wav2vec2 feature extractor and encoder: [Python.function custom_init()](InfiniteTalk-main/generate_infinitetalk.py:277)
  - Optional warm-up: tiny dummy forward to trigger kernels.
- Handler
  - Accepts job dict with input payload.
  - Correlation id: job["id"] echoed into all logs and artifact paths.
  - Validate input with rp_validator against schema.
  - Create /tmp/job-{id} and perform downloads/decoding:
    - cond_video (image or video) via URL/Base64/path support.
    - cond_audio per person via URL/Base64/path; or TTS text to audio using Kokoro (optional).
  - Compute wav2vec2 embeddings (if raw audio was provided) using [Python.function get_embedding()](InfiniteTalk-main/generate_infinitetalk.py:323).
  - Build input dict for [Python.function generate_infinitetalk()](InfiniteTalk-main/wan/multitalk.py:376) including .pt embedding paths and mux audio path.
  - Run generation; stream progress checkpoints (see below).
  - Save MP4 and upload artifact to S3/bucket with job-scoped prefix.
  - Return JSON with result URLs and metadata.
  - Cleanup temp directory using rp_cleanup.
- Concurrency
  - Default concurrency=1 per GPU. InfiniteTalk 14B is large; enabling in-worker concurrency is not recommended.
  - Optionally expose a concurrency_modifier that returns 1 if VRAM>= requirement met, otherwise 0 (pause), but default fixed 1.
- Progress updates (granular)
  - validation_started / validation_ok
  - downloads_started / downloads_ok
  - embeddings_started / embeddings_ok
  - pipeline_warm_started / pipeline_warm_ok
  - generation_started
    - stage: chunk_{k}_preprocess
    - stage: chunk_{k}_sampling_{pct}
    - stage: chunk_{k}_decode
  - muxing_started / muxing_ok
  - upload_started / upload_ok
  - completed
- Error handling taxonomy (see section 6)

Logging format (JSON Lines)
- Each log line: {"ts": "...ISO8601...", "level": "INFO|WARN|ERROR", "job_id": "...", "event": "string", "details": {...}, "lat_ms": 123}
- Provide correlation across job_id, and include key timings for cold vs warm segments.

Artifacts/results
- Primary: MP4 H.264 in MP4 container at 25 fps.
- Secondary: Thumbnail JPG (first frame), JSON metadata (params used, timings).
- Storage strategy (preferred): rp_upload to S3 or Runpod Network Volume with presigned URLs returned in final response.


## 3) Input and Output Schemas

Types
- String: non-empty UTF-8.
- URL: https/http link to a reachable resource.
- Base64: "data:*;base64,..." or plain base64 string.
- File path: absolute or /runpod-volume/ path.
- Enum sets and ranges as listed below.

Single job input schema (top-level "input")
- prompt: string (required)
- cond_video: string (required) — URL, base64 image/video, or file path (image or video). Frames extracted internally.
- cond_audio:
  - Either:
    - { "person1": string } (URL/base64/path), single speaker
    - { "person1": string, "person2": string } (URL/base64/path), two speakers
  - Or TTS path:
    - tts_audio: { text: string, human1_voice?: string, human2_voice?: string }
- audio_type: string optional — "para" | "add" (only for two speakers). See [Python.function audio_prepare_multi()](InfiniteTalk-main/generate_infinitetalk.py:291)
- bbox: array[4] of int optional — for multi-person localization hints
- generation params (subset mapped to InfiniteTalk):
  - size: "infinitetalk-480" | "infinitetalk-720" (default "infinitetalk-480")
  - mode: "clip" | "streaming" (default "clip")
  - frame_num: int, default 81, must be 4n+1
  - max_frame_num: int, default 1000 (for streaming mode)
  - sample_steps: int, default 40
  - sample_text_guide_scale: float, default 5.0
  - sample_audio_guide_scale: float, default 4.0
  - motion_frame: int, default 9
  - color_correction_strength: float 0.0..1.0, default 1.0
  - use_teacache: bool, default false; teacache_thresh: float default 0.2
  - use_apg: bool default false; apg_momentum: float default -0.75; apg_norm_threshold: float default 55
  - base_seed: int default 42
  - num_persistent_param_in_dit: int optional (VRAM management)
  - quant: "int8" | "fp8" | null; quant_dir: string path if used
  - offload_model: bool default true on single GPU (see [Python.function generate()](InfiniteTalk-main/generate_infinitetalk.py:453))
- output_config:
  - store: "s3" | "volume" | "inline"
  - If "s3": bucket, region, prefix optional; else worker uses endpoint env vars.
  - If "inline": base64 result returned inline (only for small outputs; not recommended).

Example JSON (single speaker, image)
```json
{
  "input": {
    "prompt": "A woman sings in a studio",
    "cond_video": "https://example.com/image.jpg",
    "cond_audio": { "person1": "https://example.com/voice.wav" },
    "size": "infinitetalk-480",
    "mode": "clip",
    "frame_num": 81,
    "sample_steps": 8,
    "sample_text_guide_scale": 1.0,
    "sample_audio_guide_scale": 2.0,
    "motion_frame": 9,
    "base_seed": 42,
    "use_teacache": false,
    "use_apg": false,
    "color_correction_strength": 1.0,
    "output_config": { "store": "s3", "prefix": "infinitetalk/jobs" }
  }
}
```

Example JSON (two speakers, video, parallel audio, streaming)
```json
{
  "input": {
    "prompt": "Two people speaking in a newsroom",
    "cond_video": "https://example.com/input.mp4",
    "cond_audio": {
      "person1": "data:audio/wav;base64,AAA...",
      "person2": "/runpod-volume/incoming/s2.wav"
    },
    "audio_type": "para",
    "size": "infinitetalk-720",
    "mode": "streaming",
    "frame_num": 81,
    "max_frame_num": 1000,
    "sample_steps": 40,
    "sample_text_guide_scale": 5.0,
    "sample_audio_guide_scale": 4.0,
    "motion_frame": 11,
    "use_teacache": true,
    "teacache_thresh": 0.2,
    "use_apg": true,
    "apg_momentum": -0.75,
    "apg_norm_threshold": 55,
    "num_persistent_param_in_dit": 0,
    "output_config": { "store": "s3", "prefix": "infinitetalk/stream" }
  }
}
```

Batch job schema
- input is either an object (single) or:
  - batch: array of input objects (as above) with shared policy/output_config
  - Optional per-item id and webhook override
- The worker iterates items sequentially (no parallel GPU runs), emitting progress per item.

Example JSON (batch)
```json
{
  "input": {
    "batch": [
      {
        "id": "item-1",
        "prompt": "Speaker 1",
        "cond_video": "https://example.com/img1.jpg",
        "cond_audio": { "person1": "https://example.com/a1.wav" },
        "size": "infinitetalk-480"
      },
      {
        "id": "item-2",
        "prompt": "Speaker 2",
        "cond_video": "https://example.com/img2.jpg",
        "cond_audio": { "person1": "https://example.com/a2.wav" },
        "size": "infinitetalk-480",
        "sample_steps": 8
      }
    ],
    "output_config": { "store": "s3", "prefix": "infinitetalk/batch" }
  },
  "policy": { "executionTimeout": 1800, "ttl": 86400 }
}
```

Output schema (success)
- job_id: string
- status: "success"
- video:
  - url: string (presigned S3 or volume URL)
  - mime: "video/mp4"
  - bytes: int
  - thumbnail_url: string
- timings:
  - cold_start_ms, load_ms, preprocess_ms, embedding_ms, sampling_ms, decode_ms, mux_ms, upload_ms, total_ms
- params: echo of key generation params and sizes
- logs: optional compact array of checkpoint summaries

Output schema (error)
- job_id: string
- status: "error"
- error:
  - code: string (see taxonomy)
  - message: string
  - retryable: bool
- diagnostics:
  - stdout_tail: string optional
  - stderr_tail: string optional


## 4) Parameter Catalog (InfiniteTalk-specific)

Mapped from CLI and app:
- task: fixed to "infinitetalk-14B" internally; no external input required. See [Python.function generate()](InfiniteTalk-main/generate_infinitetalk.py:453)
- size: "infinitetalk-480" | "infinitetalk-720" (affects sample_shift default)
- frame_num: int, default 81, 4n+1
- max_frame_num: int, default 1000 (streaming)
- motion_frame: int, default 9 (use 11 for 720p in sample_shift mapping)
- sample_steps: int, default 40 (typical range 4–1000; practical 4–40)
- sample_shift: float; derived default 7 (480) / 11 (720)
- sample_text_guide_scale: float, default 5.0 (0..20)
- sample_audio_guide_scale: float, default 4.0 (0..20)
- base_seed: int, default 42; -1 means random
- mode: "clip" | "streaming"
- use_teacache: bool, default false; teacache_thresh: float default 0.2
- use_apg: bool, default false; apg_momentum: float default -0.75; apg_norm_threshold: float default 55
- color_correction_strength: float 0.0..1.0 default 1.0
- num_persistent_param_in_dit: int optional (enable VRAM management) See [Python.function enable_vram_management()](InfiniteTalk-main/generate_infinitetalk.py:541)
- offload_model: bool default True (single GPU)
- quant: "int8" | "fp8" optional; quant_dir path required if set
- wav2vec embeddings computed internally from raw audio via [Python.function get_embedding()](InfiniteTalk-main/generate_infinitetalk.py:323)

Audio modes
- Single speaker local file or TTS
- Two speakers with audio_type:
  - "para" (parallel) or "add" (concatenate) per [Python.function audio_prepare_multi()](InfiniteTalk-main/generate_infinitetalk.py:291)


## 5) Progress Checkpoints and Reporting

Use [Python.function runpod.serverless.progress_update()](runpod-python-main/runpod/serverless/__init__.py:19) with structured payloads:
```json
{
  "stage": "downloads_started",
  "pct": 5,
  "job_id": "RP-abc123",
  "details": { "bytes_total": 5321123 }
}
```

Recommended sequence (emit at least these):
- validation_started (0%), validation_ok (2%)
- downloads_started (3%), downloads_ok (8%)
- embeddings_started (9%), embeddings_ok (15%)
- pipeline_warm_started (15%), pipeline_warm_ok (18%)
- generation_started (20%)
  - chunk_k_pre (per chunk; 20% + k*X)
  - chunk_k_sampling_y% (fine-grained within a chunk)
  - chunk_k_decode
- muxing_started (85%), muxing_ok (90%)
- upload_started (92%), upload_ok (98%)
- completed (100%)

For batch: include item_id and item_index fields.


## 6) Error Handling and Taxonomy

Define deterministic codes for client UI and logs:
- E_INPUT_VALIDATION
  - Missing/invalid fields; bad enum; unsupported file type; oversized inputs
  - 4xx-equivalent; retryable=false (after correction)
- E_DOWNLOAD_FAILED
  - Network/HTTP error fetching input; retryable=true
- E_AUDIO_EMBEDDING
  - Wav2vec2 feature extraction or model failure; retryable=true if transient
- E_PIPELINE_LOAD
  - Model weights missing/paths wrong; retryable=false until fixed; surface which path is missing
- E_OOM
  - CUDA OOM during sampling/decoding; retryable=false; suggest lower size/steps or single concurrency
- E_FFMPEG
  - Muxing/extraction error; retryable=true if input codec/format transient
- E_GENERATION_RUNTIME
  - Other runtime exception in [Python.function generate_infinitetalk()](InfiniteTalk-main/wan/multitalk.py:376); retryable=depends
- E_UPLOAD
  - Artifact upload failed; retryable=true
- E_TIMEOUT
  - Exceeded executionTimeout; retry by increasing policy timeout

Error message pattern
- error: { code, message, retryable, at_stage, cause_class, cause_message }
- Log an ERROR line with the same code and include job_id and stack snippet tail.

Example error log (JSON line)
```json
{"ts":"2025-09-08T00:01:02.003Z","level":"ERROR","job_id":"RP-abc123","event":"error","details":{"code":"E_OOM","at_stage":"generation_sampling","gpu":"A100-80G","suggest":"use size=infinitetalk-480, sample_steps=8"}}
```


## 7) Storage and Artifact Strategy

Preferred: External S3-compatible storage
- Configure endpoint env vars: S3_ENDPOINT, S3_REGION, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET, S3_PUBLIC_BASE (optional).
- Worker uploads MP4 and thumbnail via [Python.function rp_upload.upload_file_to_bucket()](runpod-python-main/runpod/serverless/utils/rp_upload.py:215).
- Return presigned URLs in result. Large outputs never inline.

Alternative: Runpod Network Volume
- Mount a volume and write to /runpod-volume/infinitetalk/{job_id}/...
- If a reverse proxy serves the volume, return public URL; otherwise return path for out-of-band retrieval.

Inline (not recommended)
- Only for very short clips & testing; base64 in JSON response inflates payloads.

File naming
- Prefix with job_id and optionally item_id; include major params:
  - infitalk_{size}_{steps}_seed{seed}_{job_id}.mp4


## 8) Dockerfile Plan

Base image and CUDA
- Use NVIDIA CUDA 12.1 base with cuDNN compatible with PyTorch 2.4.1 and xformers 0.0.28 (per project setup). Example: nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04
- Install:
  - Python 3.10
  - ffmpeg (apt)
  - pip install from [Python.file requirements.txt](InfiniteTalk-main/requirements.txt) plus worker deps
- Cache layers
  - Copy only requirements first to leverage Docker layer caching.
  - Optionally bake model weights into image under /weights to reduce cold start.
- Environment variables
  - CKPT_DIR, INFINITETALK_DIR, WAV2VEC_DIR, QUANT_DIR (optional)
  - MODEL_CACHE=/models (if baking)
  - TORCH_CUDA_ARCH_LIST if needed
- Entrypoint
  - python -u /workspace/worker/handler.py
  - The handler calls [Python.function runpod.serverless.start()](runpod-python-main/runpod/serverless/__init__.py:136)
- Image platform: linux/amd64

FFmpeg
- Must be present for muxing and audio extraction paths (see [Python.function extract_audio_from_video()](InfiniteTalk-main/generate_infinitetalk.py:348)).

Model caching
- Prefer embedding checkpoints in image OR mounting a Network Volume with pre-fetched HF snapshots.
- Warm-up pass on start to compile kernels.

GPU and cost guidance
- GPU class: A100 80GB or L40S 48GB preferred. For 480p short clips, 24GB may suffice with offload and num_persistent_param_in_dit=0 at cost of latency.
- Concurrency: 1 per GPU.

Codec and container
- Output: H.264 in MP4, 25 fps to maximize compatibility.


## 9) Local Testing Strategy

No Docker needed (Runpod SDK Local Sim)
- Run the worker directly with test_input.json:
  - python worker/handler.py --test_input "@examples/single_image.json"
- Local API server:
  - python worker/handler.py --rp_serve_api --rp_api_port 8008
  - Then POST to http://localhost:8008/run with JSON payload.

Simple client scripts (planned in repo)
- [Python.file submit_async.py](InfiniteTalk_Runpod_Serverless/scripts/submit_async.py): sends /run and polls /status with backoff.
- [Python.file submit_sync.py](InfiniteTalk_Runpod_Serverless/scripts/submit_sync.py): sends /runsync for short jobs.
- [Python.file make_payloads.py](InfiniteTalk_Runpod_Serverless/examples/make_payloads.py): converts local files to sample JSON.

Example payloads are documented in [Markdown.file EXAMPLES.md](EXAMPLES.md).


## 10) Security, Validation, and Limits

Secrets
- Only from environment variables at the endpoint (never in code or image). Example: RUNPOD_API_KEY, S3 credentials.

Validation
- Use rp_validator to enforce:
  - Required fields: prompt, cond_video, cond_audio or tts_audio, size
  - Max file sizes: cond_video 200MB, audio 50MB per speaker
  - Allowed MIME types/extensions
  - Enum/range checks for all parameters

Rate limiting and retries
- UI implements exponential backoff on /status polling and respects 429s.
- Worker returns retryable=true when transient.

Execution policies
- Recommend executionTimeout: 1800s for streaming.
- TTL 24h.

Idempotency
- Use job_id in all artifact keys. If /retry, overwrite same keys to keep referential integrity.


## 11) Gradio UI Plan

Planned file: [Python.file app.py](InfiniteTalk_Runpod_Serverless/ui/app.py)

Capabilities
- Inputs
  - Runpod API key, Endpoint ID
  - cond_image or cond_video upload
  - cond_audio uploads for person1 and optional person2, or TTS text and voice selectors
  - All InfiniteTalk parameters surfaced with safe defaults
- Behavior
  - On submit: Uploads local files to temporary storage or directly sends as base64 (small) or pre-signed upload; then calls /run with JSON
  - Polls /status every 2s (backoff to 5s after 1 min), renders progress and latest logs
  - Displays final MP4 in a video component with download link
- Mapping to worker inputs
  - Mirrors schemas above; UI computes no embeddings; embeddings are computed in the worker for consistency
- Error display
  - Maps error.code to user-friendly message; shows stderr/stdout tails if provided
- Advanced
  - Batch mode: upload CSV/JSONL of jobs, submit sequentially

Polling cadence
- 0–60s: 2s interval; 60–600s: 5s interval; >600s: 10s interval
- Stop on terminal states or cancel request


## 12) Performance and Cost Considerations

- Cold start
  - Embed weights into image or attach Network Volume
  - Enable FlashBoot; keep small number of Active workers to minimize first-byte latency
- Steps and resolution
  - For demos: 480p, sample_steps 8–12 yields faster results
- VRAM
  - Use offload_model=true and num_persistent_param_in_dit=0 when constrained; expect longer runtime
- Throughput
  - Concurrency=1 for stability; scale horizontally via endpoint Max workers
- Storage cost
  - Short TTL for artifacts; prefix by date/job_id to simplify lifecycle policies


## 13) Example Structured Logs

Progress
```json
{"ts":"2025-09-08T00:00:01Z","level":"INFO","job_id":"RP-abc123","event":"validation_ok","details":{"size":"infinitetalk-480"}}
{"ts":"2025-09-08T00:00:03Z","level":"INFO","job_id":"RP-abc123","event":"downloads_ok","details":{"video_bytes":1450021,"audio_bytes":880112}}
{"ts":"2025-09-08T00:01:10Z","level":"INFO","job_id":"RP-abc123","event":"generation_sampling","details":{"chunk":0,"pct":60}}
{"ts":"2025-09-08T00:02:12Z","level":"INFO","job_id":"RP-abc123","event":"upload_ok","details":{"video_url":"https://s3/prefix/RP-abc123.mp4"}}
{"ts":"2025-09-08T00:02:13Z","level":"INFO","job_id":"RP-abc123","event":"completed","lat_ms":133000}
```

Error
```json
{"ts":"2025-09-08T00:00:05Z","level":"ERROR","job_id":"RP-xyz","event":"error","details":{"code":"E_INPUT_VALIDATION","message":"cond_audio missing","retryable":false}}
```


## 14) Repository Cross-References

- Source capabilities and CLI flags: [Markdown.file infinitetalk.md](infinitetalk.md)
- Runpod serverless playbook: [Markdown.file rpserverless.md](rpserverless.md)
- InfiniteTalk entrypoints:
  - [Python.file generate_infinitetalk.py](InfiniteTalk-main/generate_infinitetalk.py)
  - [Python.file app.py](InfiniteTalk-main/app.py)


## 15) Sequence Diagram (textual description)

- Gradio UI → Runpod /run: submit job with payload
- Runpod enqueues → Worker starts (cold/warm)
- Worker:
  - validate → download → embeddings → warm → generate (chunks) → mux → upload → respond
- Gradio UI polls /status → on COMPLETE: GET video URL → display and allow download