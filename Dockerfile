# CUDA-enabled image for Runpod Serverless worker
# Base: CUDA 12.1 + cuDNN on Ubuntu 22.04 (compatible with Torch 2.4.1, xformers 0.0.28.post2)
FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

# Avoid interactive tzdata prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
# Common ML caches (mounted or written under /root/.cache by default)
ENV HF_HOME=/root/.cache/huggingface
ENV TRANSFORMERS_CACHE=/root/.cache/huggingface/transformers
ENV WANDB_DISABLED=1
# Build-time override for CUDA archs (Ada/Hopper safe defaults)
ENV TORCH_CUDA_ARCH_LIST="8.6;8.9;9.0+PTX"

# Optional: allow prefetching models at build-time (defaults to off for serverless)
ARG PREFETCH_MODELS=0

# System dependencies:
# - python3.10 + venv (Ubuntu 22.04 ships Python 3.10)
# - git (optional for some pip installs)
# - ffmpeg, libsndfile1 (audio IO)
# - build-essential, python3-dev (wheels fallback; try to keep small)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    python3-dev \
    git \
    ffmpeg \
    libsndfile1 \
    ca-certificates \
    curl \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

# Upgrade pip/setuptools/wheel to maximize prebuilt wheel usage
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Set workdir at repo root inside image
WORKDIR /workspace

# Copy only the worker subset first to leverage Docker layer caching on pip installs
# Copy requirements to install dependencies
COPY InfiniteTalk_Runpod_Serverless/worker/requirements.txt ./InfiniteTalk_Runpod_Serverless/worker/requirements.txt

# Install CUDA-compatible core deps:
# - torch/torchvision/torchaudio from cu121 index
# - xformers from PyPI (prebuilt cu121 wheels)
# NOTE: We intentionally skip flash-attn here because building from source requires the CUDA toolkit.
#       If you absolutely need flash-attn, prefer using a base image with CUDA devel or add a custom wheel index.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cu121 \
      torch==2.4.1 torchvision==0.19.1 torchaudio==2.4.1 \
 && pip install --no-cache-dir xformers==0.0.28.post2

# Install remaining Python dependencies from requirements, excluding heavy CUDA-specific lines we already installed.
# Filter out torch/torchvision/xformers/flash-attn to avoid conflicts.
RUN set -ex; \
    grep -vE '^(torch|torchvision|xformers|flash-attn)\\b' InfiniteTalk_Runpod_Serverless/worker/requirements.txt > /tmp/req.txt; \
    pip install --no-cache-dir -r /tmp/req.txt; \
    rm -f /tmp/req.txt

# Copy entire repo (after deps for better layer caching)
COPY . /workspace

# Optional: prefetch models to cache inside image (not recommended for serverless due to image size).
# Implement your own lightweight prefetch logic in a safe, skippable way.
# When PREFETCH_MODELS=1, try to import minimal code and touch common model caches.
RUN if [ "$PREFETCH_MODELS" = "1" ]; then \
      python3 - <<'PY' || true; \
      import os; \
      print("Prefetch step placeholder: implement model snapshot downloads if desired."); \
PY \
    ; fi

# Default user environment tweaks (safe defaults)
ENV PYTHONDONTWRITEBYTECODE=1

# Health: make sure Python can import the worker entrypoint
# The entrypoint sets sys.path to ensure proper imports.
WORKDIR /workspace/InfiniteTalk_Runpod_Serverless

# Clean up any build-time leftovers (keep runtime libs only)
# Note: We keep ffmpeg/libsndfile and Python; build-essential and python3-dev can be removed to slim further
# but retaining them can help for any runtime wheel fallbacks. If size is critical, uncomment the removal below.
# RUN apt-get purge -y build-essential python3-dev && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Documented local GPU run requires nvidia-container-runtime:
# docker run --rm --gpus all -e RP_DEBUG_LOCAL=1 infinitetalk-runpod:gpu
ENTRYPOINT ["python3", "entrypoint.py"]