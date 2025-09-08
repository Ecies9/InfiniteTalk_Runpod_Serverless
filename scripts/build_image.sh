#!/usr/bin/env bash
# Build the CUDA-enabled Docker image for the Runpod Serverless worker.
# Usage:
#   ./InfiniteTalk_Runpod_Serverless/scripts/build_image.sh [TAG]
# Examples:
#   ./InfiniteTalk_Runpod_Serverless/scripts/build_image.sh
#   ./InfiniteTalk_Runpod_Serverless/scripts/build_image.sh myregistry.com/infinitetalk-runpod:gpu
set -euo pipefail

DEFAULT_TAG="infinitetalk-runpod:gpu"
TAG="${1:-${TAG:-$DEFAULT_TAG}}"

# Optional: pass PREFETCH_MODELS=1 to bake caches (not recommended for serverless due to image size)
#   PREFETCH_MODELS=1 ./InfiniteTalk_Runpod_Serverless/scripts/build_image.sh
PREFETCH_MODELS="${PREFETCH_MODELS:-0}"

echo "Building image: ${TAG}"
docker build \
  -t "${TAG}" \
  -f InfiniteTalk_Runpod_Serverless/Dockerfile \
  --build-arg PREFETCH_MODELS="${PREFETCH_MODELS}" \
  .

echo "Built ${TAG}"