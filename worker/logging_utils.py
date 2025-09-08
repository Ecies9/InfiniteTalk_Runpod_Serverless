import json
import os
import sys
import time
import uuid
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Lightweight structured JSON logger tailored for Runpod workers.
# Emits lines to stdout in the format:
# {"ts","level","cid","event","data","lat_ms"}
#
# Usage:
#   logger = JsonLogger(correlation_id="...")
#   logger.log_event("INFO", "received", {"job_id": job_id})
#   with logger.timeit_stage("models_loading"):
#       load_models()
#
# Optionally, if runpod.serverless.utils.keep_warm is available, you can call it
# periodically from outside using the same correlation id to keep the worker hot.


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JsonLogger:
    def __init__(self, correlation_id: Optional[str] = None, job_id: Optional[str] = None):
        self.correlation_id = correlation_id or str(uuid.uuid4())
        self.job_id = job_id
        self._lock = threading.Lock()

    def _emit(self, level: str, event: str, data: Optional[Dict[str, Any]] = None, lat_ms: Optional[int] = None):
        rec = {
            "ts": _iso_now(),
            "level": level,
            "cid": self.correlation_id
        }
        if self.job_id:
            rec["job_id"] = self.job_id
        rec["event"] = event
        if data is not None:
            rec["data"] = data
        if lat_ms is not None:
            rec["lat_ms"] = lat_ms
        line = json.dumps(rec, ensure_ascii=False)
        with self._lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()

    # Convenience wrappers
    def info(self, event: str, data: Optional[Dict[str, Any]] = None):
        self._emit("INFO", event, data)

    def warn(self, event: str, data: Optional[Dict[str, Any]] = None):
        self._emit("WARN", event, data)

    def error(self, event: str, data: Optional[Dict[str, Any]] = None):
        self._emit("ERROR", event, data)

    # API required by spec
    def log_event(self, level: str, event: str, data: Optional[Dict[str, Any]] = None):
        level = level.upper()
        if level not in ("INFO", "WARN", "ERROR"):
            level = "INFO"
        self._emit(level, event, data)

    @contextmanager
    def timeit_stage(self, event: str, data_start: Optional[Dict[str, Any]] = None, log_ok_event: Optional[str] = None):
        """
        Context manager to time a stage.
        - Emits event (INFO) at enter.
        - Emits log_ok_event or f"{event}_ok" (INFO) with lat_ms at exit.
        """
        start = time.perf_counter()
        self.info(event, data_start)
        try:
            yield
        except Exception as e:
            # Let caller handle mapping to taxonomy; still emit error with stage timing
            lat_ms = int((time.perf_counter() - start) * 1000)
            self.error("stage_error", {"at_stage": event, "exc": type(e).__name__, "message": str(e), "lat_ms": lat_ms})
            raise
        else:
            lat_ms = int((time.perf_counter() - start) * 1000)
            self.info(log_ok_event or f"{event}_ok", {"lat_ms": lat_ms})

# Module-level helpers required by spec
_GLOBAL_LOGGERS: Dict[str, JsonLogger] = {}


def get_logger(correlation_id: Optional[str] = None, job_id: Optional[str] = None) -> JsonLogger:
    cid = correlation_id or job_id or str(uuid.uuid4())
    if cid not in _GLOBAL_LOGGERS:
        _GLOBAL_LOGGERS[cid] = JsonLogger(correlation_id=cid, job_id=job_id)
    return _GLOBAL_LOGGERS[cid]


# Spec helper aliases
def log_event(level: str, event: str, data: Optional[Dict[str, Any]] = None, correlation_id: Optional[str] = None, job_id: Optional[str] = None):
    get_logger(correlation_id, job_id).log_event(level, event, data)


def timeit_stage(event: str, correlation_id: Optional[str] = None, job_id: Optional[str] = None, data_start: Optional[Dict[str, Any]] = None, log_ok_event: Optional[str] = None):
    return get_logger(correlation_id, job_id).timeit_stage(event, data_start=data_start, log_ok_event=log_ok_event)