# InfiniteTalk Runpod Serverless

Serverless packaging of InfiniteTalk for audio-driven video dubbing on Runpod, plus a lightweight Gradio client that submits jobs to a Runpod endpoint and previews results.

Core references:
- InfiniteTalk pipeline: [Python.class InfiniteTalkPipeline()](InfiniteTalk-main/wan/multitalk.py:108)
- Generation entry: [Python.function generate_infinitetalk()](InfiniteTalk-main/wan/multitalk.py:376)
- Architecture for this repo: [Markdown.file ARCHITECTURE.md](InfiniteTalk_Runpod_Serverless/ARCHITECTURE.md)


## Features

- Runpod Serverless worker with strict input validation, structured logging, and granular progress updates.
- Async job flow with artifact upload to S3 or Runpod Network Volume; presigned URLs returned.
- Gradio Web UI for:
  - Runpod API key + Endpoint ID entry
  - Upload image/video and audio (or TTS text)
  - Configure InfiniteTalk parameters (resolution, steps, guidance, streaming, VRAM/quant options)
  - Poll status, display progress, render final MP4, and download.
- Local testing via Runpod SDK local API server and example payloads.


## Repository Structure

See [Markdown.file REPO_STRUCTURE.md](InfiniteTalk_Runpod_Serverless/REPO_STRUCTURE.md) for the planned code layout (worker, ui, examples, scripts, Dockerfile, configs).


## Prerequisites

- Runpod account and access to Serverless Endpoints.
- Container registry for custom images (Runpod registry or external).
- GPU selection: Prefer A100 80GB or L40S 48GB for stability.
- Model weights prepared according to InfiniteTalk:
  - Wan2.1-I2V-14B-480P (ckpt_dir)
  - InfiniteTalk weights (infinitetalk_dir)
  - chinese-wav2vec2-base (wav2vec_dir)
  - Optional quant_dir for int8/fp8
  - See InfiniteTalk setup: [Markdown.file infinitetalk.md](infinitetalk.md)

Runtime dependencies (bundled in image):
- Python 3.10, PyTorch 2.4.1, xformers 0.0.28, Flash-Attn 2.7.4.post1, ffmpeg.


## Quickstart

1) Review architecture and schemas
- Read [Markdown.file ARCHITECTURE.md](InfiniteTalk_Runpod_Serverless/ARCHITECTURE.md) for the worker lifecycle, input/output schemas, logging, and storage.

2) Build the image
- Use the Dockerfile plan in [Markdown.file ARCHITECTURE.md](InfiniteTalk_Runpod_Serverless/ARCHITECTURE.md) section 8.
- Tag with semantic version (e.g., infinitetalk-sls:0.1.0).

3) Create a Runpod Serverless endpoint
- Choose GPU type, set Min/Max workers.
- Set environment variables for model paths and S3 (if used).
- Attach a Network Volume or bake weights into the image.

4) Test locally (optional)
- Serve local API from the worker: python worker/handler.py --rp_serve_api --rp_api_port 8008
- POST example payloads from [Markdown.file EXAMPLES.md](InfiniteTalk_Runpod_Serverless/EXAMPLES.md).

5) Use the Gradio UI
- Launch the UI app and input your Runpod API key and Endpoint ID.
- Upload image/video/audio (or TTS), set parameters, submit, and monitor progress.

Full step-by-step guide: [Markdown.file GUIDE.md](InfiniteTalk_Runpod_Serverless/GUIDE.md)


## Build and Deploy Overview

- Dockerfile requirements and CUDA/cuDNN: see [Markdown.file ARCHITECTURE.md](InfiniteTalk_Runpod_Serverless/ARCHITECTURE.md)
- Entry point: worker/handler registers with [Python.function runpod.serverless.start()](runpod-python-main/runpod/serverless/__init__.py:136)
- Caching strategy:
  - Prefer model weights embedded or mounted via Network Volume at /runpod-volume/weights
  - Warm-up path on import to minimize cold latency
- Endpoint configuration:
  - Execution timeout: 1800s for streaming workloads
  - Concurrency: 1 per GPU
  - FlashBoot enabled; consider Active workers to reduce cold starts


## Parameter Surface (UI and API)

Key InfiniteTalk parameters (defaults in brackets):
- size: infinitetalk-480 | infinitetalk-720 [infinitetalk-480]
- mode: clip | streaming [clip]
- frame_num: int (4n+1) [81]
- max_frame_num: int [1000] (streaming)
- sample_steps: int [40] (recommend 8–12 for demos)
- sample_text_guide_scale: float [5.0]
- sample_audio_guide_scale: float [4.0]
- motion_frame: int [9]
- color_correction_strength: float [1.0]
- use_teacache: bool [false]; teacache_thresh: float [0.2]
- use_apg: bool [false]; apg_momentum: float [-0.75]; apg_norm_threshold: float [55]
- base_seed: int [42]
- num_persistent_param_in_dit: int (VRAM management)
- offload_model: bool [true on single GPU]
- quant: int8|fp8; quant_dir: path if quant enabled

Mapped to core functions:
- Pipeline: [Python.class InfiniteTalkPipeline()](InfiniteTalk-main/wan/multitalk.py:108)
- Generation: [Python.function generate_infinitetalk()](InfiniteTalk-main/wan/multitalk.py:376)


## Links

- Design: [Markdown.file ARCHITECTURE.md](InfiniteTalk_Runpod_Serverless/ARCHITECTURE.md)
- Setup and usage: [Markdown.file GUIDE.md](InfiniteTalk_Runpod_Serverless/GUIDE.md)
- Examples: [Markdown.file EXAMPLES.md](InfiniteTalk_Runpod_Serverless/EXAMPLES.md)
- Structure: [Markdown.file REPO_STRUCTURE.md](InfiniteTalk_Runpod_Serverless/REPO_STRUCTURE.md)