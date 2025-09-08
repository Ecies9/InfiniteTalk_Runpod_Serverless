#!/usr/bin/env bash
# Push a previously built image.
# Usage:
#   IMAGE=myregistry.com/infinitetalk-runpod TAG=gpu ./InfiniteTalk_Runpod_Serverless/scripts/push_image.sh
#   ./InfiniteTalk_Runpod_Serverless/scripts/push_image.sh myregistry.com/infinitetalk-runpod:gpu
set -euo pipefail

if [[ $# -gt 0 ]]; then
  REF="$1"
else
  IMAGE="${IMAGE:-infinitetalk-runpod}"
  TAG="${TAG:-gpu}"
  REF="${IMAGE}:${TAG}"
fi

echo "Pushing image: ${REF}"
docker push "${REF}"
echo "Pushed ${REF}"