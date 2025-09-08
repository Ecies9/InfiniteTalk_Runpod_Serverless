import time
import json
import base64
import logging
from typing import Any, Dict, Optional, Tuple

import requests

# Minimal wrapper around Runpod REST API.
# Exposes:
# - submit_job(api_key, endpoint_id, input_payload)
# - get_status(api_key, endpoint_id, job_id)
# - extract_progress(status_json)

RUNPOD_API_BASE = "https://api.runpod.ai/v2"

_LOG = logging.getLogger("runpod_client")
_LOG.setLevel(logging.INFO)


def _headers(api_key: str) -> Dict[str, str]:
    # Sanitize: we never log the full key.
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _request_with_retry(
    method: str,
    url: str,
    api_key: str,
    json_payload: Optional[Dict[str, Any]] = None,
    max_retries: int = 5,
    base_sleep: float = 0.8,
) -> Tuple[Optional[requests.Response], Optional[str]]:
    """
    Simple retry/backoff for 429/5xx. Jitter-free to keep it deterministic.
    Returns (response, error_message).
    """
    for attempt in range(max_retries):
        try:
            resp = requests.request(method, url, headers=_headers(api_key), json=json_payload, timeout=60)
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                sleep_s = min(8.0, base_sleep * (2 ** attempt))
                _LOG.warning("Runpod HTTP %s on %s, retrying in %.1fs", resp.status_code, url, sleep_s)
                time.sleep(sleep_s)
                continue
            return resp, None
        except requests.RequestException as e:
            sleep_s = min(8.0, base_sleep * (2 ** attempt))
            _LOG.warning("Runpod request exception on %s: %s; retry in %.1fs", url, str(e), sleep_s)
            time.sleep(sleep_s)
            continue
    return None, f"Failed after {max_retries} attempts for {url}"


def submit_job(api_key: str, endpoint_id: str, input_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    POST /run to submit an async job.
    Input must align with worker schema: { "input": { ... } } or { "input": { "batch": [...] } }
    Returns JSON with job id on success or raises RuntimeError.
    """
    url = f"{RUNPOD_API_BASE}/{endpoint_id}/run"
    resp, err = _request_with_retry("POST", url, api_key, json_payload=input_payload)
    if err:
        raise RuntimeError(err)
    if resp is None:
        raise RuntimeError("No response from Runpod /run.")

    try:
        data = resp.json()
    except Exception:
        raise RuntimeError(f"Non-JSON response from Runpod /run: HTTP {resp.status_code} text={resp.text[:400]}")

    if resp.status_code not in (200, 201, 202):
        # Return explicit Runpod error if any
        msg = data.get("error", data)
        raise RuntimeError(f"Runpod /run error HTTP {resp.status_code}: {msg}")

    return data


def get_status(api_key: str, endpoint_id: str, job_id: str) -> Dict[str, Any]:
    """
    GET /status/{job_id}
    Returns the Runpod status JSON. Terminal when status in ["COMPLETED", "FAILED", "TIMEOUT"].
    """
    url = f"{RUNPOD_API_BASE}/{endpoint_id}/status/{job_id}"
    resp, err = _request_with_retry("GET", url, api_key, json_payload=None)
    if err:
        raise RuntimeError(err)
    if resp is None:
        raise RuntimeError("No response from Runpod /status.")

    try:
        data = resp.json()
    except Exception:
        raise RuntimeError(f"Non-JSON response from Runpod /status: HTTP {resp.status_code} text={resp.text[:400]}")

    if resp.status_code != 200:
        msg = data.get("error", data)
        raise RuntimeError(f"Runpod /status error HTTP {resp.status_code}: {msg}")

    return data


def extract_progress(status_json: Dict[str, Any]) -> Tuple[int, str, Optional[list]]:
    """
    Best-effort extraction of progress info from a Runpod status response.

    Returns:
    - percent (0..100)
    - stage text
    - structured checkpoints/logs (list) if available
    """
    # Runpod top-level status fields vary; commonly:
    # {
    #   "status": "IN_QUEUE|IN_PROGRESS|COMPLETED|FAILED|TIMEOUT",
    #   "id": "...",
    #   "output": {...},  # on completion
    #   "percent": 0-100, # sometimes provided
    #   "logs": [...]     # if worker emits
    # }
    percent = int(status_json.get("percent") or 0)
    status = status_json.get("status", "")
    stage = status

    # Some workers include 'statusText' or 'message'
    stage = status_json.get("statusText") or status_json.get("message") or stage

    # Worker-specific structured logs:
    checkpoints = None
    out = status_json.get("output")
    if isinstance(out, dict):
        # If worker propagated logs/checkpoints
        checkpoints = out.get("checkpoints") or out.get("logs")

    # Or sometimes logs are on the status root:
    if checkpoints is None:
        logs_root = status_json.get("logs")
        if isinstance(logs_root, list):
            checkpoints = logs_root

    return percent, str(stage), checkpoints