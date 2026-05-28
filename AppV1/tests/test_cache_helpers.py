"""Tests for Redis cache helpers (no live Upstash connection required)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from cache.helpers import cache_get_sync, cache_set_sync, make_cache_key


def test_make_cache_key_is_stable():
    k1 = make_cache_key("summary", {"url": "https://example.com/a", "tone": "Informational"})
    k2 = make_cache_key("summary", {"tone": "Informational", "url": "https://example.com/a"})
    assert k1 == k2
    assert k1.startswith("news:summary:")


def test_cache_get_miss_when_redis_not_configured():
    with patch("cache.helpers.get_redis_sync", return_value=None):
        assert cache_get_sync("news:test:key") is None


def test_cache_set_noop_when_redis_not_configured():
    with patch("cache.helpers.get_redis_sync", return_value=None):
        assert cache_set_sync("news:test:key", {"a": 1}) is False


def test_cache_roundtrip_with_mock_redis():
    store: dict[str, str] = {}

    mock_client = MagicMock()

    def _set(key, value, ex=None):
        store[key] = value
        return True

    def _get(key):
        return store.get(key)

    mock_client.set = _set
    mock_client.get = _get

    with patch("cache.helpers.get_redis_sync", return_value=mock_client):
        key = make_cache_key("llm_json", {"user": "hello"})
        assert cache_get_sync(key) is None
        payload = {"agent1": {"cross_section_summary": "test"}}
        assert cache_set_sync(key, payload, ttl=86400) is True
        loaded = cache_get_sync(key)
        assert loaded == payload


def test_cache_deserializes_json_strings():
    mock_client = MagicMock()
    mock_client.get.return_value = json.dumps(["positive", "neutral"])
    with patch("cache.helpers.get_redis_sync", return_value=mock_client):
        result = cache_get_sync("news:sentiment_batch:abc")
        assert result == ["positive", "neutral"]
