# In-memory + Upstash Redis TTL cache for research briefs (keyed by article URL + model + prompt version).

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from config import REDIS_CACHE_TTL_SECONDS
from cache.helpers import cache_get_sync, cache_set_sync, make_cache_key

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_store: dict[str, tuple[float, str]] = {}

# Default: 48 hours in-process; Redis uses REDIS_CACHE_TTL_SECONDS (24h by default).
DEFAULT_BRIEF_CACHE_TTL_SEC = 48 * 3600


def brief_cache_key(article_url: str, model: str, prompt_fingerprint: str) -> str:
    """Stable key for a brief: normalized URL, model id, and prompt version string."""
    u = (article_url or "").strip()
    return f"{u}\x1f{model}\x1f{prompt_fingerprint}"


def _redis_key(local_key: str) -> str:
    return make_cache_key("research_brief", {"key": local_key})


def get_cached_brief(key: str, *, now: Optional[float] = None) -> Optional[str]:
    """Return cached brief text if present and not expired (memory first, then Redis)."""
    t = now if now is not None else time.time()
    with _lock:
        item = _store.get(key)
        if item:
            exp, text = item
            if t <= exp:
                logger.info("research_brief in-memory cache HIT key_len=%s", len(key))
                return text
            del _store[key]

    cached = cache_get_sync(_redis_key(key))
    if cached is not None:
        text = str(cached)
        with _lock:
            _store[key] = (time.time() + DEFAULT_BRIEF_CACHE_TTL_SEC, text)
        return text
    return None


def set_cached_brief(key: str, text: str, ttl_sec: float = DEFAULT_BRIEF_CACHE_TTL_SEC) -> None:
    """Store a brief in memory and Redis (when configured)."""
    exp = time.time() + ttl_sec
    with _lock:
        _store[key] = (exp, text)
    cache_set_sync(_redis_key(key), text, ttl=REDIS_CACHE_TTL_SECONDS)
    logger.debug("research_brief cache store key_len=%s ttl_sec=%s", len(key), ttl_sec)
