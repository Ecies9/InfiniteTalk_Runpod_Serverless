from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import requests


DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
BACKOFF_SEC = 1.5
CHUNK_SIZE = 1024 * 1024


@dataclass
class DownloadResult:
    path: str
    bytes: int
    mime: Optional[str] = None
    from_url: Optional[str] = None


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def save_temp(buf: bytes, suffix: str = "", workdir: Optional[str] = None, filename: Optional[str] = None) -> str:
    workdir = workdir or "/tmp"
    _ensure_dir(workdir)
    if filename is None:
        ts = int(time.time() * 1000)
        filename = f"blob_{ts}{suffix}"
    out = os.path.join(workdir, filename)
    with open(out, "wb") as f:
        f.write(buf)
    return out


def _is_base64_payload(s: str) -> bool:
    if s.startswith("data:") and ";base64," in s:
        return True
    try:
        # quick heuristic, ignore whitespace
        base64.b64decode(s, validate=True)
        return True
    except Exception:
        return False


def decode_base64_to_file(data: str, workdir: str, suggested_name: str = "blob") -> DownloadResult:
    if data.startswith("data:") and ";base64," in data:
        header, b64 = data.split(",", 1)
        mime = header.split(":")[1].split(";")[0]
        ext = _mime_to_ext(mime)
        content = base64.b64decode(b64)
        path = save_temp(content, suffix=ext, workdir=workdir, filename=f"{suggested_name}{ext}")
        return DownloadResult(path=path, bytes=len(content), mime=mime, from_url=None)
    else:
        content = base64.b64decode(data)
        path = save_temp(content, workdir=workdir, filename=suggested_name)
        return DownloadResult(path=path, bytes=len(content), mime=None, from_url=None)


def _mime_to_ext(mime: Optional[str]) -> str:
    if not mime:
        return ""
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/flac": ".flac",
        "audio/ogg": ".ogg",
    }
    return mapping.get(mime, "")


def download_from_url(url_or_b64_or_path: str, workdir: str, filename: Optional[str] = None, checksum_sha256: Optional[str] = None, timeout: int = DEFAULT_TIMEOUT) -> DownloadResult:
    """
    Download helper with retries.
    - Accepts:
      * http(s) URL
      * base64 (data URL or raw)
      * local path (returns as-is)
    """
    # Local path
    if os.path.exists(url_or_b64_or_path):
        size = os.path.getsize(url_or_b64_or_path)
        return DownloadResult(path=url_or_b64_or_path, bytes=size, mime=None, from_url=None)

    # Base64
    if _is_base64_payload(url_or_b64_or_path):
        return decode_base64_to_file(url_or_b64_or_path, workdir, suggested_name=filename or "blob")

    # URL
    parsed = urlparse(url_or_b64_or_path)
    if parsed.scheme in ("http", "https"):
        last_err: Optional[Exception] = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                with requests.get(url_or_b64_or_path, stream=True, timeout=timeout) as r:
                    r.raise_for_status()
                    mime = r.headers.get("Content-Type")
                    ext = _mime_to_ext(mime)
                    name = filename or os.path.basename(parsed.path) or f"blob{ext}"
                    if not os.path.splitext(name)[1] and ext:
                        name = f"{name}{ext}"
                    _ensure_dir(workdir)
                    out_path = os.path.join(workdir, name)
                    h = hashlib.sha256() if checksum_sha256 else None
                    total = 0
                    with open(out_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                            if not chunk:
                                continue
                            f.write(chunk)
                            total += len(chunk)
                            if h:
                                h.update(chunk)
                    if checksum_sha256 and h and h.hexdigest() != checksum_sha256.lower():
                        raise ValueError("Checksum mismatch for downloaded file.")
                    return DownloadResult(path=out_path, bytes=total, mime=mime, from_url=url_or_b64_or_path)
            except Exception as e:
                last_err = e
                if attempt == MAX_RETRIES:
                    raise
                time.sleep(BACKOFF_SEC * attempt)
        # Should not reach
        raise last_err or RuntimeError("Unknown download error")
    else:
        raise ValueError("Unsupported input reference; must be http(s) URL, base64, or existing local path.")


def upload_to_presigned_url(file_path: str, presigned_url: str, content_type: Optional[str] = None, timeout: int = 120) -> Tuple[int, Dict[str, Any]]:
    """
    Upload a local file to a presigned URL (HTTP PUT).
    Returns (status_code, response_headers)
    """
    headers = {}
    if content_type:
        headers["Content-Type"] = content_type
    size = os.path.getsize(file_path)
    with open(file_path, "rb") as f:
        resp = requests.put(presigned_url, data=f, headers=headers, timeout=timeout)
    return resp.status_code, dict(resp.headers)


def make_artifact(type_: str, path: Optional[str] = None, url: Optional[str] = None, mime: Optional[str] = None, bytes_: Optional[int] = None) -> Dict[str, Any]:
    rec: Dict[str, Any] = {
        "type": type_
    }
    if url:
        rec["url"] = url
    if path:
        rec["path"] = path
    if mime:
        rec["mime"] = mime
    if bytes_ is not None:
        rec["bytes"] = int(bytes_)
    return rec