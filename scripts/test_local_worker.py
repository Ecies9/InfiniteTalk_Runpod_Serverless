import json
import os
import sys
import uuid
from pathlib import Path

# Ensure project root on path
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from InfiniteTalk_Runpod_Serverless.worker.handler import run  # noqa: E402


def load_payload(name: str) -> dict:
    p = ROOT_DIR / "examples" / name
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    # Choose which payload to run
    choices = {
        "image": "payload_single_image.json",
        "video": "payload_single_video.json",
    }
    which = os.environ.get("PAYLOAD", "image")
    fname = choices.get(which, "payload_single_image.json")

    payload = load_payload(fname)

    job = {"id": f"local-{uuid.uuid4()}", **payload}
    result = run(job)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()