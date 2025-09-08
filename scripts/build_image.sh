#!/usr/bin/env bash
# Build the CUDA-enabled Docker image for the Runpod Serverless worker.
# Usage:
#   ./scripts/build_image.sh [TAG]
# Examples:
#   ./scripts/build_image.sh
#   ./scripts/build_image.sh myregistry.com/infinitetalk-runpod:gpu
set -euo pipefail

DEFAULT_TAG="infinitetalk-runpod:gpu"
TAG="${1:-${TAG:-$DEFAULT_TAG}}"

# Optional: pass PREFETCH_MODELS=1 to bake caches (not recommended for serverless due to image size)
#   PREFETCH_MODELS=1 ./scripts/build_image.sh
PREFETCH_MODELS="${PREFETCH_MODELS:-0}"

echo "Building image: ${TAG}"
docker build \
  -t "${TAG}" \
  -f Dockerfile \
  --build-arg PREFETCH_MODELS="${PREFETCH_MODELS}" \
  .

echo "Built ${TAG}"