# GUIDE — Deploy and Use InfiniteTalk on Runpod Serverless

This guide walks through building the worker image, creating a Runpod Serverless endpoint, configuring environment variables, understanding cold starts, and using the bundled Gradio UI to submit jobs and download results. Troubleshooting tips and known errors are listed at the end.

Key references:
- Architecture: [Markdown.file ARCHITECTURE.md](ARCHITECTURE.md)
- InfiniteTalk internals: [Markdown.file infinitetalk.md](infinitetalk.md)
- Runpod serverless concepts: [Markdown.file rpserverless.md](rpserverless.md)
- Core InfiniteTalk generation: [Python.function generate_infinitetalk()](InfiniteTalk-main/wan/multitalk.py:376)
- Worker SDK entry: [Python.function runpod.serverless.start()](runpod-python-main/runpod/serverless/__init__.py:136)
- Progress updates: [Python.function runpod.serverless.progress_update()](runpod-python-main/runpod/serverless/__init__.py:19)


## 1) Build the Docker Image

Base requirements (see detailed plan in [Markdown.file ARCHITECTURE.md](ARCHITECTURE.md)):
- CUDA 12.1 runtime compatible with Torch 2.4.1 + xformers 0.0.28
- Python 3.10
- ffmpeg installed at OS level
- Python deps from InfiniteTalk and worker requirements

Suggested steps:
- Create Dockerfile as specified in [Markdown.file ARCHITECTURE.md](ARCHITECTURE.md) section 8.
- Bake model weights or attach a Network Volume:
  - Bake for fastest cold starts (larger image)
  - Network Volume for flexibility and smaller images
- Build and push:
  - docker build -t <registry>/infinitetalk-sls:0.1.0 .
  - docker push <registry>/infinitetalk-sls:0.1.0

Image entrypoint should run the worker, which registers the handler via [Python.function runpod.serverless.start()](runpod-python-main/runpod/serverless/__init__.py:136).


## 2) Create the Runpod Serverless Endpoint

Use Runpod Console:
- New Endpoint → Import Docker → provide the image reference.
- Hardware:
  - GPU: A100 80GB or L40S 48GB preferred. 24GB cards may work with offload and VRAM management but slower.
- Scaling:
  - Min workers: 0 (Flex) or small Active count (1–2) to reduce cold starts
  - Max workers: based on expected concurrency (1 per GPU)
  - FlashBoot: enable
- Timeouts:
  - executionTimeout: 1800s for streaming jobs
  - TTL: 86400s (24h)

Environment variables (examples):
- Model paths
  - CKPT_DIR=/runpod-volume/weights/Wan2.1-I2V-14B-480P
  - INFINITETALK_DIR=/runpod-volume/weights/InfiniteTalk/single/infinitetalk.safetensors
  - WAV2VEC_DIR=/runpod-volume/weights/chinese-wav2vec2-base
  - QUANT_DIR=/runpod-volume/weights/quant (optional)
- Storage (S3-compatible)
  - S3_ENDPOINT=https://s3.example.com
  - S3_REGION=us-east-1
  - S3_ACCESS_KEY=...
  - S3_SECRET_KEY=...
  - S3_BUCKET=infinitetalk-artifacts
  - S3_PUBLIC_BASE=https://cdn.example.com/infinitetalk (optional)
- Worker behavior (optional)
  - DEFAULT_SIZE=infinitetalk-480
  - DEFAULT_SAMPLE_STEPS=8
  - ENABLE_TECACHE=false
  - ENABLE_APG=false

Attach a Network Volume
- Mount at /runpod-volume
- Pre-stage model weights in the volume (or bake into the image)


## 3) Local Testing (No Deployment Required)

Run the worker locally for quick tests:
- Start a local API server:
  - python worker/handler.py --rp_serve_api --rp_api_port 8008
  - Note: rename handler to main if using concurrency > 1 as per Runpod SDK.
- Submit a job:
  - curl -X POST http://localhost:8008/run -H "Content-Type: application/json" -d @InfiniteTalk_Runpod_Serverless/examples/single_image.json
- Or run a test input inline:
  - python worker/handler.py --test_input "@InfiniteTalk_Runpod_Serverless/examples/single_image.json"

See payloads in [Markdown.file EXAMPLES.md](EXAMPLES.md).


## 4) Using the Gradio Web UI

Where:
- UI app file path: [Python.file app.py](InfiniteTalk_Runpod_Serverless/ui/app.py)

What it does:
- Collects your Runpod API key and Endpoint ID
- Uploads cond_image/cond_video and audio (or TTS text)
- Exposes InfiniteTalk parameters
- Sends /run requests and polls /status
- Displays progress checkpoints and final video with a download link

Steps:
1) Launch the UI
   - python InfiniteTalk_Runpod_Serverless/ui/app.py
2) Configure connection
   - Enter RUNPOD_API_KEY
   - Enter ENDPOINT_ID of your InfiniteTalk endpoint
3) Upload inputs
   - EITHER upload a single image OR a reference video (UI toggles visibility)
   - Upload audio for person1 and optionally person2 (or enter TTS text)
4) Set parameters
   - size (infinitetalk-480/720), mode (clip/streaming), sample_steps, guidance scales, motion_frame, color correction
5) Submit
   - The UI sends a /run request containing an input payload matching the schemas in [Markdown.file ARCHITECTURE.md](ARCHITECTURE.md)
6) Monitor
   - Progress is polled every 2s, backed off as runtime increases
   - Intermediate progress updates are displayed (validation, downloads, embeddings, chunk sampling, muxing, upload)
7) Retrieve result
   - The final MP4 URL is shown inline and available for download


## 5) Progress, Logs, and Troubleshooting

Progress in Runpod:
- Worker sends updates using [Python.function runpod.serverless.progress_update()](runpod-python-main/runpod/serverless/__init__.py:19)
- Status API shows percent and latest stage detail
- UI translates these into a progress bar and stage messages

Structured logs:
- JSON Lines with job_id correlation:
  - {"ts":"...","level":"INFO|ERROR","job_id":"...","event":"...","details":{...}}
- Examples in [Markdown.file ARCHITECTURE.md](ARCHITECTURE.md) section 13

Common errors (codes are surfaced in the UI):
- E_INPUT_VALIDATION — missing/invalid field; fix payload
- E_DOWNLOAD_FAILED — input URL fetch issue; check accessibility/size
- E_AUDIO_EMBEDDING — wav2vec2 extraction failure; verify WAV format or try again
- E_PIPELINE_LOAD — weight path missing; check CKPT_DIR/INFINITETALK_DIR/WAV2VEC_DIR
- E_OOM — reduce size=infinitetalk-480, sample_steps=8, disable concurrency
- E_FFMPEG — installation/codec problems; ensure ffmpeg is present
- E_UPLOAD — artifact upload failed; verify S3 credentials and bucket
- E_TIMEOUT — increase executionTimeout or simplify generation parameters

Runpod console logs:
- Inspect endpoint logs; filter by job id
- If long-term retention needed, persist logs to a Network Volume

Cold start notes:
- If models are not baked, first job will be slower
- Enable FlashBoot and keep 1–2 Active workers for production reliability


## 6) Security and Limits

Secrets:
- Set in endpoint environment variables only; never commit to code or bake into image

Payload size:
- /run: 10 MB; /runsync: 20 MB per platform defaults (see [Markdown.file rpserverless.md](rpserverless.md))
- For large inputs, upload to a Network Volume or external storage and pass paths/URLs

Rate limits:
- Respect 429 responses; the UI backs off automatically


## 7) Example Requests and CLI

Example payloads are provided in [Markdown.file EXAMPLES.md](EXAMPLES.md).

Minimal Python async submitter (planned):
- [Python.file submit_async.py](InfiniteTalk_Runpod_Serverless/scripts/submit_async.py): POST /run and poll /status with exponential backoff
- [Python.file submit_sync.py](InfiniteTalk_Runpod_Serverless/scripts/submit_sync.py): POST /runsync for short jobs


## 8) FAQ

- Q: Should I precompute audio embeddings in the UI?
  - A: No. The worker standardizes embedding computation using [Python.function get_embedding()](InfiniteTalk-main/generate_infinitetalk.py:323), ensuring reproducibility.

- Q: Recommended defaults for demos?
  - A: size=infinitetalk-480, sample_steps=8–12, mode=clip, and single speaker.

- Q: Which output codecs?
  - A: H.264 in MP4 at 25 fps via ffmpeg, maximizing compatibility.

- Q: How to reduce OOM risk?
  - A: Use offload_model=true, set num_persistent_param_in_dit=0, reduce steps, and avoid concurrent jobs in a single worker.