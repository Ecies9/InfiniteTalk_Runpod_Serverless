# Repository Structure — InfiniteTalk Runpod Serverless

This document specifies the planned directory layout, key files, and purposes for the InfiniteTalk Serverless worker and Gradio UI.

Primary references:
- Architecture and schemas: [ARCHITECTURE.md](ARCHITECTURE.md)
- InfiniteTalk generation entry: `generate_infinitetalk.py`
- Pipeline class: `Python.class InfiniteTalkPipeline()`
- Runpod worker start: `Python.function runpod.serverless.start()`


## Top-level

- [README.md](README.md) — Summary, features, prerequisites, quickstart, links.
- [ARCHITECTURE.md](ARCHITECTURE.md) — System design, worker lifecycle, schemas, progress, logging, storage, performance.
- [GUIDE.md](GUIDE.md) — Step-by-step setup, UI usage, troubleshooting, FAQs.
- [REPO_STRUCTURE.md](REPO_STRUCTURE.md) — This file.
- [EXAMPLES.md](EXAMPLES.md) — Curated payloads for single, multi-speaker, TTS, batch.
- [Dockerfile](Dockerfile) — Worker image build (as planned in architecture).
- [LICENSE](LICENSE) — Optional license for this packaging (not included yet).


## worker/ (Serverless worker)

- [handler.py](worker/handler.py) — Runpod worker entry:
  - Registers handler via `Python.function runpod.serverless.start()`
  - Global model init (InfiniteTalk pipeline, wav2vec2) at import-time
  - Job validation, downloads, embedding compute, generation, muxing, upload, progress updates, structured logs, error taxonomy
- [schema.py](worker/schema.py) — rp_validator schema for request validation
- [io_utils.py](worker/io_utils.py) — URL/Base64-to-file, tmpdir management, thumbnail extraction, S3/volume path helpers
- [logging_utils.py](worker/logging_utils.py) — JSONL logger, correlation id helpers, checkpoint timer utilities
- [constants.py](worker/constants.py) — Error codes, default parameter values, env var keys, MIME allowlists
- [__init__.py](worker/__init__.py) — Package init


## ui/ (Gradio client for Runpod endpoint)

- [app.py](ui/app.py) — Gradio UI:
  - Runpod API key + Endpoint ID input
  - Upload image/video/audio or enter TTS text; parameter controls
  - Submit /run requests; poll /status; show progress and final video
- [client.py](ui/client.py) — Thin client for Runpod REST (submit, status, cancel) used by app.py
- [components.py](ui/components.py) — UI components and layout helpers
- [__init__.py](ui/__init__.py)


## builder/ (Build-time assets)

- [requirements.txt](builder/requirements.txt) — Full Python dependencies (InfiniteTalk + worker/UI + ffmpeg-python if used)
- [post_install.sh](builder/post_install.sh) — Optional script to fetch/bundle model assets into image layers (if baking weights)
- [__init__.py](builder/__init__.py)


## scripts/ (Local and CI helpers)

- [submit_async.py](scripts/submit_async.py) — Example async submitter and status poller
- [submit_sync.py](scripts/submit_sync.py) — Example synchronous request
- [create_endpoint.py](scripts/create_endpoint.py) — Optional script to create/update Runpod endpoint via API
- [make_payloads.py](scripts/make_payloads.py) — Generate example payload JSON from local files
- [__init__.py](scripts/__init__.py)


## examples/ (Payloads and sample assets)

- [single_image.json](examples/single_image.json) — Single-speaker, single image, clip mode
- [single_video.json](examples/single_video.json) — Single-speaker, video dubbing, clip mode
- [two_speakers_para.json](examples/two_speakers_para.json) — Two speakers (parallel)
- [two_speakers_add.json](examples/two_speakers_add.json) — Two speakers (add/concatenate)
- [tts_single.json](examples/tts_single.json) — Single-speaker TTS
- [tts_multi.json](examples/tts_multi.json) — Two-speaker TTS
- [batch.json](examples/batch.json) — Batch of heterogeneous jobs
- assets/ (optional) — Small sample media under permissive license (or referenced via remote URLs)


## docs/ (Optional extended docs)

- operational.md — Operating tips, metrics, cost guidance
- changelog.md — Version history of the serverless worker image and UI
- api.md — REST endpoints and response mapping used by the Gradio client


## configs/ (Optional environment templates)

- .env.example — Example environment variables for local sim (no secrets)
- runpod-env.json — Example endpoint settings JSON (gpu type, scaler, timeouts)


## Future code placements

- VLM/LLM prompt augmentation (if adopted) — under worker/ or a new module
- Multi-tenant API gateway — separate service; UI would call gateway instead of Runpod directly
- Streaming output support — an alternate handler using generator/async returns


## Cross-Links

- Inputs/outputs and payload schemas: [ARCHITECTURE.md](ARCHITECTURE.md)
- Example payloads and notes: [EXAMPLES.md](EXAMPLES.md)
- InfiniteTalk CLI and helpers:
  - `generate_infinitetalk.py`
  - `Python.function get_embedding()`
  - `Python.function save_video_ffmpeg`