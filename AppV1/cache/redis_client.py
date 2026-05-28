"""Lazy Upstash Redis clients (sync + async). Disabled when env vars are missing."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from config import UPSTASH_REDIS_REST_TOKEN, UPSTASH_REDIS_REST_URL

if TYPE_CHECKING:
    from upstash_redis import Redis as SyncRedis
    from upstash_redis.asyncio import Redis as AsyncRedis

logger = logging.getLogger(__name__)

_sync_client: Optional["SyncRedis"] = None
_async_client: Optional["AsyncRedis"] = None
_init_logged = False


def is_configured() -> bool:
    return bool(
        UPSTASH_REDIS_REST_URL
        and str(UPSTASH_REDIS_REST_URL).strip()
        and UPSTASH_REDIS_REST_TOKEN
        and str(UPSTASH_REDIS_REST_TOKEN).strip()
    )


def _log_init_once(enabled: bool) -> None:
    global _init_logged
    if _init_logged:
        return
    _init_logged = True
    if enabled:
        logger.info("Upstash Redis caching enabled (lazy-loaded, TTL-based).")
    else:
        logger.info(
            "Upstash Redis not configured; AI cache disabled (set UPSTASH_REDIS_REST_URL and "
            "UPSTASH_REDIS_REST_TOKEN on Render to enable cross-user caching)."
        )


def get_redis_sync():
    """Return a shared sync Upstash Redis client, or None if not configured."""
    global _sync_client
    if not is_configured():
        _log_init_once(False)
        return None
    _log_init_once(True)
    if _sync_client is None:
        from upstash_redis import Redis

        _sync_client = Redis(
            url=str(UPSTASH_REDIS_REST_URL).strip(),
            token=str(UPSTASH_REDIS_REST_TOKEN).strip(),
        )
    return _sync_client


def get_redis_async():
    """Return a shared async Upstash Redis client, or None if not configured."""
    global _async_client
    if not is_configured():
        _log_init_once(False)
        return None
    _log_init_once(True)
    if _async_client is None:
        from upstash_redis.asyncio import Redis

        _async_client = Redis(
            url=str(UPSTASH_REDIS_REST_URL).strip(),
            token=str(UPSTASH_REDIS_REST_TOKEN).strip(),
        )
    return _async_client
