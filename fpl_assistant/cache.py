"""Tiny JSON-on-disk cache so we don't hammer the FPL API on every dashboard refresh."""
import json
import time
from pathlib import Path
from typing import Any, Callable

from fpl_assistant.config import CACHE_DIR


def cached_fetch(key: str, ttl_seconds: int, fetch_fn: Callable[[], Any]) -> Any:
    path = _path_for(key)
    if path.exists():
        age = time.time() - path.stat().st_mtime
        if age < ttl_seconds:
            with open(path, "r") as f:
                return json.load(f)

    data = fetch_fn()
    with open(path, "w") as f:
        json.dump(data, f)
    return data


def _path_for(key: str) -> Path:
    safe_key = key.replace("/", "_")
    return CACHE_DIR / f"{safe_key}.json"
