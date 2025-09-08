import os
import sys

# Ensure project root is on sys.path so worker package can be imported when container starts
CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(CURRENT_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    import runpod  # type: ignore
except Exception as e:
    raise RuntimeError("Runpod SDK is required to start the serverless worker.") from e

from InfiniteTalk_Runpod_Serverless.worker.handler import run  # noqa: E402


if __name__ == "__main__":
    # Start Runpod serverless worker with our handler
    # See reference: [Python.function runpod.serverless.start()](runpod-python-main/runpod/serverless/__init__.py:136)
    runpod.serverless.start({"handler": run})