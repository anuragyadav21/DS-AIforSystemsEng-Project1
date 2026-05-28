import json
import logging
from collections.abc import Callable
from typing import Any, Optional

import httpx

from config import OPENAI_MODEL
from cache.helpers import cache_get_sync, cache_set_sync, make_cache_key

logger = logging.getLogger(__name__)
_shared_client: httpx.Client | None = None


def _client() -> httpx.Client:
    global _shared_client
    if _shared_client is None:
        _shared_client = httpx.Client(timeout=45.0)
    return _shared_client


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def call_text_llm(
    *,
    system_prompt: str,
    user_prompt: str,
    api_key: Optional[str],
    max_tokens: int = 250,
    temperature: float = 0.2,
) -> str | None:
    if not api_key or not str(api_key).strip():
        return None
    cache_key = make_cache_key(
        "llm_text",
        {
            "model": OPENAI_MODEL,
            "system": system_prompt,
            "user": user_prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
    )
    cached = cache_get_sync(cache_key)
    if cached is not None:
        return str(cached)
    try:
        resp = _client().post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        if resp.status_code != 200:
            logger.warning("LLM text call returned status %s", resp.status_code)
            return None
        payload = resp.json()
        text = payload["choices"][0]["message"]["content"].strip()
        if text:
            cache_set_sync(cache_key, text)
        return text
    except Exception as exc:
        logger.warning("LLM text call failed: %s", exc)
        return None


def call_json_llm(
    *,
    system_prompt: str,
    user_prompt: str,
    api_key: Optional[str],
    max_tokens: int = 700,
    temperature: float = 0.2,
) -> dict[str, Any] | None:
    if not api_key or not str(api_key).strip():
        return None
    cache_key = make_cache_key(
        "llm_json",
        {
            "model": OPENAI_MODEL,
            "system": system_prompt,
            "user": user_prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
    )
    cached = cache_get_sync(cache_key)
    if cached is not None and isinstance(cached, dict):
        return cached
    try:
        resp = _client().post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            },
        )
        if resp.status_code != 200:
            logger.warning("LLM JSON call returned status %s", resp.status_code)
            return None
        payload = resp.json()
        content = payload["choices"][0]["message"]["content"]
        parsed = _extract_json_object(content)
        if isinstance(parsed, dict) and parsed:
            cache_set_sync(cache_key, parsed)
        return parsed
    except Exception as exc:
        logger.warning("LLM JSON call failed: %s", exc)
        return None


def run_tool_round_then_json(
    *,
    system_prompt: str,
    first_user_content: str,
    tools: list[dict[str, Any]],
    tool_executor: Callable[[str, dict[str, Any]], str],
    api_key: Optional[str],
    max_tokens_first: int = 600,
    max_tokens_second: int = 750,
    temperature: float = 0.2,
) -> dict[str, Any] | None:
    """
    First Chat Completions call with tools and tool_choice auto (no JSON response_format).
    If the assistant issues tool_calls, run ``tool_executor(name, args)`` for each and append
    tool messages, then a second completion with response_format json_object only.

    If the first response has no tool_calls, returns parsed JSON from assistant content if valid,
    otherwise None (caller may fall back to call_json_llm).

    ``tool_executor`` returns the string content for each tool message (typically JSON text).
    """
    if not api_key or not str(api_key).strip():
        return None
    cache_key = make_cache_key(
        "llm_tool_json",
        {
            "model": OPENAI_MODEL,
            "system": system_prompt,
            "user": first_user_content,
            "tools": tools,
            "max_tokens_first": max_tokens_first,
            "max_tokens_second": max_tokens_second,
            "temperature": temperature,
        },
    )
    cached = cache_get_sync(cache_key)
    if cached is not None and isinstance(cached, dict):
        return cached
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": first_user_content},
    ]
    try:
        resp = _client().post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "max_tokens": max_tokens_first,
                "temperature": temperature,
            },
        )
        if resp.status_code != 200:
            logger.warning("LLM tool round 1 returned status %s", resp.status_code)
            return None
        payload = resp.json()
        msg = payload["choices"][0]["message"]
        tool_calls = msg.get("tool_calls")

        if not tool_calls:
            content = (msg.get("content") or "").strip()
            parsed = _extract_json_object(content)
            if isinstance(parsed, dict) and parsed:
                cache_set_sync(cache_key, parsed)
            return parsed if isinstance(parsed, dict) and parsed else None

        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": msg.get("content"),
            "tool_calls": tool_calls,
        }
        messages.append(assistant_msg)

        for tc in tool_calls:
            fn = tc.get("function") or {}
            name = str(fn.get("name") or "")
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            tool_content = tool_executor(name, args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_content,
                }
            )

        resp2 = _client().post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "messages": messages,
                "max_tokens": max_tokens_second,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            },
        )
        if resp2.status_code != 200:
            logger.warning("LLM tool round 2 returned status %s", resp2.status_code)
            return None
        payload2 = resp2.json()
        content2 = payload2["choices"][0]["message"].get("content") or ""
        out = _extract_json_object(content2)
        if isinstance(out, dict) and out:
            cache_set_sync(cache_key, out)
        return out if isinstance(out, dict) and out else None
    except Exception as exc:
        logger.warning("LLM tool round failed: %s", exc)
        return None
