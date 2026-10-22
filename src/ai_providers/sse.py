"""Parsers for the streaming contracts used by the providers.

The parsers consume already bounded events (decoded JSON) or lines (Cohere),
so transport limits and cancellation remain in ``src.ai_client``.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..ai_errors import AIProviderError, AIResponseLimitError, safe_provider_error
from ..stream_events import MAX_STREAM_EVENTS


def iter_openai_style(events, usage_events: Optional[List[Dict[str, Any]]] = None):
    for data in events:
        if data.get("error"):
            raise AIProviderError("Provider stream error: " + safe_provider_error(data["error"]))
        if usage_events is not None and isinstance(data.get("usage"), dict):
            usage_events.append(data["usage"])
        choices = data.get("choices") or []
        if choices:
            content = (choices[0].get("delta") or {}).get("content") or ""
            if content:
                yield content


def iter_anthropic(events, usage_events: Optional[List[Dict[str, Any]]] = None):
    for data in events:
        if data.get("type") == "error":
            raise AIProviderError("Anthropic stream error: " + safe_provider_error(data.get("error")))
        if usage_events is not None:
            usage = (data.get("message") or {}).get("usage") if data.get("type") == "message_start" else data.get("usage")
            if isinstance(usage, dict):
                usage_events.append(usage)
        delta = data.get("delta")
        if data.get("type") == "content_block_delta" and isinstance(delta, dict) and delta.get("text"):
            yield delta["text"]


def iter_cohere(lines, usage_events: Optional[List[Dict[str, Any]]] = None):
    """Cohere v1 is newline-delimited JSON, not the v2 SSE contract."""
    events = 0
    for raw in lines:
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        if not line:
            continue
        events += 1
        if events > MAX_STREAM_EVENTS:
            raise AIResponseLimitError("Provider stream exceeded the local event limit")
        if line.startswith("data:"):
            line = line[5:].lstrip(" ")
        try:
            data = json.loads(line)
        except json.JSONDecodeError as error:
            raise AIProviderError("Invalid JSON in Cohere stream") from error
        event = data.get("event_type")
        if event == "text-generation":
            if data.get("text"):
                yield data["text"]
        elif event == "stream-end":
            reply = data.get("response") or {}
            meta = reply.get("meta") or {}
            usage = meta.get("billed_units") or meta.get("tokens")
            if usage_events is not None and isinstance(usage, dict):
                usage_events.append(usage)
            if data.get("finish_reason") in {"ERROR", "ERROR_TOXIC"}:
                raise AIProviderError("Cohere stream failed: " + str(data.get("finish_reason")))
        elif event == "error" or data.get("error"):
            raise AIProviderError("Cohere stream error: " + safe_provider_error(data.get("error") or data.get("message")))


def iter_google(events, usage_events: Optional[List[Dict[str, Any]]] = None):
    for data in events:
        if data.get("error"):
            raise AIProviderError("Google stream error: " + safe_provider_error(data["error"]))
        block = (data.get("promptFeedback") or {}).get("blockReason")
        if block:
            raise AIProviderError("Google blocked the prompt: " + str(block))
        if usage_events is not None and isinstance(data.get("usageMetadata"), dict):
            usage_events.append(data["usageMetadata"])
        candidates = data.get("candidates") or []
        if candidates:
            parts = (candidates[0].get("content") or {}).get("parts") or []
            for part in parts:
                if part.get("text"):
                    yield part["text"]
