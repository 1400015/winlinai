"""Cohere v1 chat and streaming (newline-delimited JSON)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..ai_errors import (
    AIProviderError, AIRequestCancelled, AIResponseLimitError, redact_url,
)
from ..bounded_http import close_response
from . import logger


def _history(messages: List[Dict[str, str]]):
    """Convert the OpenAI-style history to the v1 contract."""
    chat_history = []
    preamble_parts = []
    for msg in messages:
        role = msg["role"]
        if role == "system":
            preamble_parts.append(msg["content"])
        elif role == "user":
            chat_history.append({"role": "USER", "message": msg["content"]})
        elif role == "assistant":
            chat_history.append({"role": "CHATBOT", "message": msg["content"]})
    last_user_text = ""
    # The final user turn is the `message`, not part of the history
    if chat_history and chat_history[-1]["role"] == "USER":
        last_user_text = chat_history.pop()["message"]
    # v1 answers 400 with an empty `message` (history ending in assistant or
    # only system messages): fail early and clearly.
    if not last_user_text:
        raise AIProviderError(
            "Cohere requires a final user message; history ends without one"
        )
    return preamble_parts, chat_history, last_user_text


def _headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def chat(client, messages: List[Dict[str, str]], model: str, api_key: str,
         base_url: str, temperature: float, max_tokens: int, timeout: int) -> Optional[str]:
    """Communicate with the Cohere API (v1 /chat contract)."""
    url = f"{base_url}/chat"
    preamble_parts, chat_history, last_user_text = _history(messages)

    body = {
        "model": model,
        "message": last_user_text,
        "chat_history": chat_history,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if preamble_parts:
        body["preamble"] = "\n\n".join(preamble_parts)

    try:
        response = client._make_request(url, body, _headers(api_key), timeout)
        try:
            data = response.json()
        finally:
            close_response(response)

        meta = data.get("meta") or {}
        client._record_usage("cohere", {"usage": meta.get("billed_units") or meta.get("tokens") or {}})
        return data.get("text") or ""
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing Cohere JSON: {redact_url(str(e))}")
        return None
    except KeyError as e:
        logger.error(f"Invalid response format from Cohere: {redact_url(str(e))}")
        return None
    except (AIRequestCancelled, AIResponseLimitError):
        raise
    except Exception as e:
        logger.error(f"Cohere error: {redact_url(str(e))}")
        return None


def stream(client, messages: List[Dict[str, str]], model: str, api_key: str,
           base_url: str, temperature: float, max_tokens: int, timeout: int):
    """Stream with Cohere (v1 contract, same as chat)."""
    url = f"{base_url}/chat"
    preamble_parts, chat_history, last_user_text = _history(messages)

    body = {
        "model": model,
        "message": last_user_text,
        "chat_history": chat_history,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if preamble_parts:
        body["preamble"] = "\n\n".join(preamble_parts)

    usage_events: List[Any] = []
    received: List[Any] = []
    try:
        response = client._make_request(url, body, _headers(api_key), timeout, stream=True)
        try:
            for chunk in client._bounded_text(client._iter_sse_cohere(response, usage_events)):
                received.append(chunk)
                yield chunk
        finally:
            close_response(response)
            client._finish_stream_usage("cohere", usage_events, messages, "".join(received))
    except AIProviderError:
        raise
    except Exception as e:
        raise AIProviderError(
            f"cohere stream error: {redact_url(str(e))}"
        ) from e
