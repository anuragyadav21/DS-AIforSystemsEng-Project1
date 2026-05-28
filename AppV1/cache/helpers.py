"""Cache helpers: JSON serialization, TTL writes, hit/miss logging."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Optional, TypeVar

from config import REDIS_CACHE_TTL_SECONDS

from .redis_client import get_redis_async, get_redis_sync, is_configured

logger = logging.getLogger(__name__)

T = TypeVar("T")
_KEY_PREFIX = "news:"


def is_redis_enabled() -> bool:
    return is_configured()


def make_cache_key(namespace: str, payload: Any) -> str:
    """Stable Redis key from namespace + JSON-serializable payload."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    safe_ns = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(namespace))
    return f"{_KEY_PREFIX}{safe_ns}:{digest}"


def _serialize(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def _deserialize(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def cache_get_sync(key: str) -> Optional[Any]:
    client = get_redis_sync()
    if client is None:
        return None
    try:
        raw = client.get(key)
        if raw is None:
            logger.info("Redis cache MISS key=%s", key)
            return None
        logger.info("Redis cache HIT key=%s", key)
        return _deserialize(raw)
    except Exception as exc:
        logger.warning("Redis cache GET failed key=%s error=%s", key, exc)
        return None


async def cache_get_async(key: str) -> Optional[Any]:
    client = get_redis_async()
    if client is None:
        return None
    try:
        raw = await client.get(key)
        if raw is None:
            logger.info("Redis cache MISS key=%s", key)
            return None
        logger.info("Redis cache HIT key=%s", key)
        return _deserialize(raw)
    except Exception as exc:
        logger.warning("Redis cache GET failed key=%s error=%s", key, exc)
        return None


def cache_set_sync(key: str, value: Any, ttl: Optional[int] = None) -> bool:
    client = get_redis_sync()
    if client is None:
        return False
    ex = int(ttl if ttl is not None else REDIS_CACHE_TTL_SECONDS)
    try:
        client.set(key, _serialize(value), ex=ex)
        logger.info("Redis cache SET key=%s ttl=%ss", key, ex)
        return True
    except Exception as exc:
        logger.warning("Redis cache SET failed key=%s error=%s", key, exc)
        return False


async def cache_set_async(key: str, value: Any, ttl: Optional[int] = None) -> bool:
    client = get_redis_async()
    if client is None:
        return False
    ex = int(ttl if ttl is not None else REDIS_CACHE_TTL_SECONDS)
    try:
        await client.set(key, _serialize(value), ex=ex)
        logger.info("Redis cache SET key=%s ttl=%ss", key, ex)
        return True
    except Exception as exc:
        logger.warning("Redis cache SET failed key=%s error=%s", key, exc)
        return False


def cache_delete_sync(key: str) -> None:
    client = get_redis_sync()
    if client is None:
        return
    try:
        client.delete(key)
    except Exception as exc:
        logger.warning("Redis cache DELETE failed key=%s error=%s", key, exc)


def get_or_set_sync(
    key: str,
    factory: Callable[[], T],
    *,
    ttl: Optional[int] = None,
) -> T:
    """Return cached value or compute, store with TTL, and return."""
    cached = cache_get_sync(key)
    if cached is not None:
        return cached  # type: ignore[return-value]
    value = factory()
    cache_set_sync(key, value, ttl=ttl)
    return value


async def get_or_set_async(
    key: str,
    factory: Callable[[], Awaitable[T]],
    *,
    ttl: Optional[int] = None,
) -> T:
    """Async variant of get_or_set_sync."""
    cached = await cache_get_async(key)
    if cached is not None:
        return cached  # type: ignore[return-value]
    value = await factory()
    await cache_set_async(key, value, ttl=ttl)
    return value
