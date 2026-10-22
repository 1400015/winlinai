"""The OpenAI-compatible chat contract shared by several providers.

OpenRouter, Mistral, Groq and local servers all use ``/chat/completions``
with a ``messages`` payload and ``choices[0].message`` in the reply.
Centralizing this keeps parsing, usage accounting and error shaping uniform.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..ai_errors import AIProviderError, redact_url
from ..bounded_http import close_response
from . import logger


def chat(client, provider: str, url: str, payload: Dict,
         headers: Dict, timeout: int) -> Optional[str]:
    """POST + parse an OpenAI-compatible provider.

    Raises AIProviderError on failure; returns "" when the provider answers
    without content (the contract already used by Mistral/Groq).
    """
    try:
        response = client._make_request(url, payload, headers, timeout)
        try:
            data = response.json()
        finally:
            close_response(response)

        client._record_usage(provider, data)

        choices = data.get("choices")
        if not choices:
            logger.warning(f"No choices in {provider} response")
            return ""
        content = (choices[0].get("message") or {}).get("content")
        if content is None:
            logger.warning(f"Empty content in {provider} response")
            return ""
        return content
    except AIProviderError:
        raise
    except json.JSONDecodeError as e:
        raise AIProviderError(f"Invalid JSON from {provider}: {redact_url(str(e))}") from e
    except Exception as e:
        raise AIProviderError(f"{provider} error: {redact_url(str(e))}") from e


def stream(client, provider: str, url: str, payload: Dict,
           headers: Dict, timeout: int, messages: List[Dict]):
    """Streaming generator for an OpenAI-compatible provider.

    Records real usage when the provider reports it in the final chunk
    (`stream_options: include_usage`), otherwise estimates from the text.
    """
    payload = dict(payload)
    include_usage = client.config.get("api.providers." + provider + ".stream_include_usage",
                                      provider != "local_llm")
    if include_usage:
        payload["stream_options"] = {"include_usage": True}

    usage_events: List[Dict[str, Any]] = []
    received: List[str] = []
    try:
        response = client._make_request(url, payload, headers, timeout, stream=True)
        try:
            for chunk in client._bounded_text(client._iter_sse_openai_style(response, usage_events)):
                received.append(chunk)
                yield chunk
        finally:
            close_response(response)
            client._finish_stream_usage(provider, usage_events, messages, "".join(received))
    except AIProviderError:
        raise
    except Exception as e:
        raise AIProviderError(
            f"{provider} stream error: {redact_url(str(e))}"
        ) from e
