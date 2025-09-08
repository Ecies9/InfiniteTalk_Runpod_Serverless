# Repository Structure — InfiniteTalk Runpod Serverless

This document specifies the planned directory layout, key files, and purposes for the InfiniteTalk Serverless worker and Gradio UI.

Primary references:
- Architecture and schemas: [ARCHITECTURE.md](InfiniteTalk_Runpod_Serverless/ARCHITECTURE.md)
- InfiniteTalk generation entry: [generate_infinitetalk.py](InfiniteTalk-main/generate_infinitetalk.py)
- Pipeline class: [Python.class InfiniteTalkPipeline()](InfiniteTalk-main/wan/multitalk.py:108)
- Runpod worker start: [Python.function runpod.serverless.start()](runpod-python-main/runpod/serverless/__init__.py:136)


## Top-level

- [README.md](InfiniteTalk_Runpod_Serverless/README.md) — Summary, features, prerequisites, quickstart, links.
- [ARCHITECTURE.md](InfiniteTalk_Runpod_Serverless/ARCHITECTURE.md) — System design, worker lifecycle, schemas, progress, logging, storage, performance.
- [GUIDE.md](InfiniteTalk_Runpod_Serverless/GUIDE.md) — Step-by-step setup, UI usage, troubleshooting, FAQs.
- [REPO_STRUCTURE.md](InfiniteTalk_Runpod_Serverless/REPO_STRUCTURE.md) — This file.
- [EXAMPLES.md](InfiniteTalk_Runpod_Serverless/EXAMPLES.md) — Curated payloads for single, multi-speaker, TTS, batch.
- [Dockerfile](InfiniteTalk_Runpod_Serverless/Dockerfile) — Worker image build (as planned in architecture).
- [LICENSE](InfiniteTalk_Runpod_Serverless/LICENSE) — Optional license for this packaging (not included yet).


## worker/ (Serverless worker)

- [handler.py](InfiniteTalk_Runpod_Serverless/worker/handler.py) — Runpod worker entry:
  - Registers handler via [Python.function runpod.serverless.start()](runpod-python-main/runpod/serverless/__init__.py:136)
  - Global model init (InfiniteTalk pipeline, wav2vec2) at import-time
  - Job validation, downloads, embedding compute, generation, muxing, upload, progress updates, structured logs, error taxonomy
- [schema.py](InfiniteTalk_Runpod_Serverless/worker/schema.py) — rp_validator schema for request validation
- [io_utils.py](InfiniteTalk_Runpod_Serverless/worker/io_utils.py) — URL/Base64-to-file, tmpdir management, thumbnail extraction, S3/volume path helpers
- [logging_utils.py](InfiniteTalk_Runpod_Serverless/worker/logging_utils.py) — JSONL logger, correlation id helpers, checkpoint timer utilities
- [constants.py](InfiniteTalk_Runpod_Serverless/worker/constants.py) — Error codes, default parameter values, env var keys, MIME allowlists
- [__init__.py](InfiniteTalk_Runpod_Serverless/worker/__init__.py) — Package init


## ui/ (Gradio client for Runpod endpoint)

- [app.py](InfiniteTalk_Runpod_Serverless/ui/app.py) — Gradio UI:
  - Runpod API key + Endpoint ID input
  - Upload image/video/audio or enter TTS text; parameter controls
  - Submit /run requests; poll /status; show progress and final video
- [client.py](InfiniteTalk_Runpod_Serverless/ui/client.py) — Thin client for Runpod REST (submit, status, cancel) used by app.py
- [components.py](InfiniteTalk_Runpod_Serverless/ui/components.py) — UI components and layout helpers
- [__init__.py](InfiniteTalk_Runpod_Serverless/ui/__init__.py)


## builder/ (Build-time assets)

- [requirements.txt](InfiniteTalk_Runpod_Serverless/builder/requirements.txt) — Full Python dependencies (InfiniteTalk + worker/UI + ffmpeg-python if used)
- [post_install.sh](InfiniteTalk_Runpod_Serverless/builder/post_install.sh) — Optional script to fetch/bundle model assets into image layers (if baking weights)
- [__init__.py](InfiniteTalk_Runpod_Serverless/builder/__init__.py)


## scripts/ (Local and CI helpers)

- [submit_async.py](InfiniteTalk_Runpod_Serverless/scripts/submit_async.py) — Example async submitter and status poller
- [submit_sync.py](InfiniteTalk_Runpod_Serverless/scripts/submit_sync.py) — Example synchronous request
- [create_endpoint.py](InfiniteTalk_Runpod_Serverless/scripts/create_endpoint.py) — Optional script to create/update Runpod endpoint via API
- [make_payloads.py](InfiniteTalk_Runpod_Serverless/scripts/make_payloads.py) — Generate example payload JSON from local files
- [__init__.py](InfiniteTalk_Runpod_Serverless/scripts/__init__.py)


## examples/ (Payloads and sample assets)

- [single_image.json](InfiniteTalk_Runpod_Serverless/examples/single_image.json) — Single-speaker, single image, clip mode
- [single_video.json](InfiniteTalk_Runpod_Serverless/examples/single_video.json) — Single-speaker, video dubbing, clip mode
- [two_speakers_para.json](InfiniteTalk_Runpod_Serverless/examples/two_speakers_para.json) — Two speakers (parallel)
- [two_speakers_add.json](InfiniteTalk_Runpod_Serverless/examples/two_speakers_add.json) — Two speakers (add/concatenate)
- [tts_single.json](InfiniteTalk_Runpod_Serverless/examples/tts_single.json) — Single-speaker TTS
- [tts_multi.json](InfiniteTalk_Runpod_Serverless/examples/tts_multi.json) — Two-speaker TTS
- [batch.json](InfiniteTalk_Runpod_Serverless/examples/batch.json) — Batch of heterogeneous jobs
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

- Inputs/outputs and payload schemas: [ARCHITECTURE.md](InfiniteTalk_Runpod_Serverless/ARCHITECTURE.md)
- Example payloads and notes: [EXAMPLES.md](InfiniteTalk_Runpod_Serverless/EXAMPLES.md)
- InfiniteTalk CLI and helpers:
  - [generate_infinitetalk.py](InfiniteTalk-main/generate_infinitetalk.py)
  - [Python.function get_embedding()](InfiniteTalk-main/generate_infinitetalk.py:323)
  - [Python.function save_video_ffmpeg](InfiniteTalk-main/wan/utils/multitalk_utils.py:1)