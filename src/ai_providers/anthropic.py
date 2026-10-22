"""Anthropic Claude chat and streaming."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..ai_errors import (
    AIProviderError, AIRequestCancelled, AIResponseLimitError, redact_url,
    safe_provider_error,
)
from ..bounded_http import close_response
from . import logger


def split_messages(messages: List[Dict[str, str]]):
    """Separate the system prompt and convert the remaining roles.

    Anthropic requires `system` as a top-level field, only accepts
    `user`/`assistant` in the `messages` array, messages must ALTERNATE
    (no two consecutive of the same role) and the first must be `user`.
    The UI history gives no such guarantees - a failed/cancelled turn
    can leave two `user` in a row (the request died with a 400).
    """
    system_parts = []
    converted: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "system":
            system_parts.append(content)
        elif role in ("user", "assistant"):
            if converted and converted[-1]["role"] == role:
                # Merge consecutive messages of the same role into one.
                converted[-1]["content"] = f"{converted[-1]['content']}\n\n{content}"
            else:
                converted.append({"role": role, "content": content})
    # The API rejects history that does not start with `user`.
    while converted and converted[0]["role"] != "user":
        converted.pop(0)
    return "\n\n".join(system_parts), converted


def _payload(model: str, anthropic_messages, system_prompt: str,
             temperature: float, max_tokens: int) -> Dict:
    body = {
        "model": model,
        "messages": anthropic_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if system_prompt:
        body["system"] = system_prompt
    return body


def _headers(api_key: str) -> Dict[str, str]:
    # `anthropic-version` is required; `x-api-key` is the auth.
    return {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }


def chat(client, messages: List[Dict[str, str]], model: str, api_key: str,
         base_url: str, temperature: float, max_tokens: int, timeout: int) -> Optional[str]:
    """Communicate with the Anthropic Claude API."""
    url = f"{base_url}/messages"
    system_prompt, anthropic_messages = split_messages(messages)

    try:
        response = client._make_request(
            url, _payload(model, anthropic_messages, system_prompt, temperature, max_tokens),
            _headers(api_key), timeout,
        )
        try:
            data = response.json()
        finally:
            close_response(response)

        client._record_usage("anthropic", data)

        if data.get("type") == "error":
            logger.error("Anthropic error: %s", safe_provider_error(data.get('error', {}).get('message', 'Unknown')))
            return None

        content = data.get("content")
        if isinstance(content, list):
            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
            return "".join(texts)
        if isinstance(content, dict):
            return content.get("text", "")
        return ""
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing Anthropic JSON: {redact_url(str(e))}")
        return None
    except KeyError as e:
        logger.error(f"Invalid response format from Anthropic: {redact_url(str(e))}")
        return None
    except (AIRequestCancelled, AIResponseLimitError):
        raise
    except Exception as e:
        logger.error(f"Anthropic error: {redact_url(str(e))}")
        return None


def stream(client, messages: List[Dict[str, str]], model: str, api_key: str,
           base_url: str, temperature: float, max_tokens: int, timeout: int):
    """Stream with Anthropic Claude."""
    url = f"{base_url}/messages"
    system_prompt, anthropic_messages = split_messages(messages)

    body = _payload(model, anthropic_messages, system_prompt, temperature, max_tokens)
    body["stream"] = True

    usage_events: List[Dict] = []
    received: List[str] = []
    try:
        response = client._make_request(url, body, _headers(api_key), timeout, stream=True)
        try:
            for chunk in client._bounded_text(client._iter_sse_anthropic(response, usage_events)):
                received.append(chunk)
                yield chunk
        finally:
            close_response(response)
            client._finish_stream_usage("anthropic", usage_events, messages,
                                        "".join(received))
    except AIProviderError:
        raise
    except Exception as e:
        raise AIProviderError(
            f"anthropic stream error: {redact_url(str(e))}"
        ) from e
