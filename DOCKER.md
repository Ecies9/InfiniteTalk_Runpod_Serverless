# Docker — InfiniteTalk Runpod Serverless

This doc covers building the CUDA-enabled worker image for Runpod Serverless, a slim CPU-only image for CI/import checks, and local run commands.

References:
- Entry point: [Python.file entrypoint.py](InfiniteTalk_Runpod_Serverless/entrypoint.py:1)
- Worker requirements: [Markdown.file requirements.txt](InfiniteTalk_Runpod_Serverless/worker/requirements.txt)
- Full guide: [Markdown.file GUIDE.md](InfiniteTalk_Runpod_Serverless/GUIDE.md)

## Prerequisites

- Docker 24+
- For local GPU tests: NVIDIA GPU + drivers and nvidia-container-runtime
  - Install NVIDIA Container Toolkit per NVIDIA docs, then restart Docker.
- Container registry (Runpod registry or external) to push the built image.

## Build Images

From repo root (where the InfiniteTalk_Runpod_Serverless directory resides):

GPU (CUDA 12.1 + cuDNN; Torch 2.4.1, TorchVision 0.19.1, XFormers 0.0.28):
- docker build -t infinitetalk-runpod:gpu -f InfiniteTalk_Runpod_Serverless/Dockerfile .

CPU-only (non-inference; for CI/import validation):
- docker build -t infinitetalk-runpod:cpu -f InfiniteTalk_Runpod_Serverless/Dockerfile.cpu .

Optional model prefetch at build (not recommended for serverless due to image size):
- PREFETCH_MODELS=1 docker build -t infinitetalk-runpod:gpu -f InfiniteTalk_Runpod_Serverless/Dockerfile .

Helper scripts:
- Build (Linux/macOS): [Bash.file build_image.sh](InfiniteTalk_Runpod_Serverless/scripts/build_image.sh:1)
- Build (Windows PowerShell): [PowerShell.file build_image.ps1](InfiniteTalk_Runpod_Serverless/scripts/build_image.ps1:1)
- Push: [Bash.file push_image.sh](InfiniteTalk_Runpod_Serverless/scripts/push_image.sh:1)

## Local Test

GPU host (verifies the worker boots and registers the handler):
- docker run --rm --gpus all -e RP_DEBUG_LOCAL=1 -p 8008:8008 infinitetalk-runpod:gpu

Notes:
- Requires nvidia-container-runtime. On success, the container starts the Runpod serverless local sim via [Python.function runpod.serverless.start()](runpod-python-main/runpod/serverless/__init__.py:136) from [Python.file entrypoint.py](InfiniteTalk_Runpod_Serverless/entrypoint.py:18).
- Logs should show the worker starting without import errors. Handler function is defined in [Python.file handler.py](InfiniteTalk_Runpod_Serverless/worker/handler.py:245).

CPU-only quick import check (no GPU, no inference):
- docker run --rm infinitetalk-runpod:cpu python -c "import InfiniteTalk_Runpod_Serverless.worker.handler as h; print('ok')"

## Runpod Serverless Deploy

1) Build and push:
- IMAGE=<registry/namespace/infinitetalk-runpod:gpu>
- docker tag infinitetalk-runpod:gpu $IMAGE
- docker push $IMAGE
  - Or use [Bash.file push_image.sh](InfiniteTalk_Runpod_Serverless/scripts/push_image.sh:1)

2) Create Endpoint (Runpod Console → Serverless → New → Import Docker):
- Image: <registry/namespace/infinitetalk-runpod:gpu>
- Hardware: A100 80GB or L40S 48GB recommended
- Scaling: Min workers 0–2, Max per expected concurrency, FlashBoot on
- Timeouts: executionTimeout ~ 1800s for streaming jobs

3) Configure environment variables (examples):
- CKPT_DIR=/runpod-volume/weights/Wan2.1-I2V-14B-480P
- INFINITETALK_DIR=/runpod-volume/weights/InfiniteTalk/single/infinitetalk.safetensors
- WAV2VEC_DIR=/runpod-volume/weights/chinese-wav2vec2-base
- QUANT_DIR=/runpod-volume/weights/quant
- S3_ENDPOINT, S3_REGION, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET
- TRANSFORMERS_CACHE=/root/.cache/huggingface/transformers
- HF_HOME=/root/.cache/huggingface

4) Weights: Attach a Network Volume at /runpod-volume or bake weights into the image (larger image, faster cold starts).

Cross-link: See endpoint creation details in [Markdown.file GUIDE.md](InfiniteTalk_Runpod_Serverless/GUIDE.md).

## Notes

- The GPU Dockerfile installs CUDA-compatible torch/torchvision/xformers that match [Markdown.file requirements.txt](InfiniteTalk_Runpod_Serverless/worker/requirements.txt). flash-attn is not installed in-image (building from source would require CUDA toolkit). If your pipeline requires it at runtime, provide compatible wheels via a private index or switch to a devel base and add a compile step.
- Caches: HF_HOME and TRANSFORMERS_CACHE default to /root/.cache/huggingface; for serverless, prefer runtime fetch or mount a volume.
- Entry command is python [Python.file entrypoint.py](InfiniteTalk_Runpod_Serverless/entrypoint.py:18), which calls [Python.function runpod.serverless.start()](runpod-python-main/runpod/serverless/__init__.py:136).