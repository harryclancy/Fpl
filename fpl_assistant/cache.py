"""Tiny JSON-on-disk cache so we don't hammer the FPL API on every dashboard refresh."""
import json
import time
from pathlib import Path
from typing import Any, Callable

from fpl_assistant.config import CACHE_DIR


def cached_fetch(key: str, ttl_seconds: int, fetch_fn: Callable[[], Any]) -> Any:
    """Fresh if we can get it, stale if we cannot, and only then an error.

    The last clause is the deployment-critical one. Serving data an hour
    past its TTL is a small inaccuracy; raising instead aborts the page,
    and at startup that aborts the whole deployment — the platform marks
    the build failed and keeps the previous one running. A stale copy is
    always the better failure.
    """
    path = _path_for(key)
    if path.exists():
        age = time.time() - path.stat().st_mtime
        if age < ttl_seconds:
            with open(path, "r") as f:
                return json.load(f)

    try:
        data = fetch_fn()
    except Exception:
        if path.exists():
            with open(path, "r") as f:
                return json.load(f)
        raise

    with open(path, "w") as f:
        json.dump(data, f)
    return data


def _path_for(key: str) -> Path:
    safe_key = key.replace("/", "_")
    return CACHE_DIR / f"{safe_key}.json"
