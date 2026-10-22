"""Google AI Studio (Gemini) chat and streaming."""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from ..ai_errors import AIProviderError, redact_url
from ..bounded_http import close_response
from . import logger


def safety_settings(client):
    """Google safety settings.

    By default we do NOT send `safetySettings`: the API applies its own
    filters. `disable_safety_filters: true` in config allows disabling
    them explicitly.
    """
    if not client.config.get("api.providers.google_ai_studio.disable_safety_filters", False):
        return []
    logger.warning("Google AI Studio safety filters disabled by configuration")
    return [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]


def payload(client, messages, temperature, max_tokens) -> Dict:
    """Keep system instructions separate from Gemini conversation turns."""
    contents = []
    instructions = []
    for message in messages:
        part = {"text": message["content"]}
        if message["role"] == "system":
            instructions.append(part)
        else:
            contents.append({
                "role": "user" if message["role"] == "user" else "model",
                "parts": [part],
            })
    body = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
        "safetySettings": safety_settings(client),
    }
    if instructions:
        body["systemInstruction"] = {"parts": instructions}
    return body


def chat(client, messages: List[Dict[str, str]], model: str, api_key: str,
         base_url: str, temperature: float, max_tokens: int, timeout: int) -> Optional[str]:
    """Communicate with the Google AI Studio API."""
    # The key goes in a header, never in the query string: URLs leak into
    # logs, proxies and exception messages.
    url = f"{base_url}/models/{model}:generateContent"
    headers = {"x-goog-api-key": api_key}

    body = payload(client, messages, temperature, max_tokens)

    try:
        response = client._make_request(url, body, headers, timeout)
        try:
            data = response.json()
        finally:
            close_response(response)

        client._record_usage("google_ai_studio", data)

        if not data.get("candidates"):
            # Safety block: without this the user saw an empty response and
            # never learned that a provider filter caused it.
            block_reason = (data.get("promptFeedback") or {}).get("blockReason")
            if block_reason:
                logger.warning(
                    "Google AI Studio blocked the prompt: %s", block_reason
                )
                return f"[blocked by safety filters: {block_reason}]"
            logger.warning("No candidates in Google AI Studio response")
            return ""

        # Multi-part replies: using only parts[0] truncated the text, while
        # the streaming path joined every part - the two disagreed.
        parts = (data["candidates"][0].get("content") or {}).get("parts") or []
        texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
        return "".join(texts)

    except json.JSONDecodeError as e:
        logger.error(f"Error parsing Google AI Studio JSON: {e}")
        return None
    except (KeyError, IndexError, TypeError) as e:
        logger.error(f"Invalid response format from Google AI Studio: {e}")
        return None
    except AIProviderError:
        raise
    except Exception as e:
        logger.error(f"Google AI Studio error: {redact_url(str(e))}")
        return None


def stream(client, messages: List[Dict[str, str]], model: str, api_key: str,
           base_url: str, temperature: float, max_tokens: int, timeout: int):
    """Stream with Google AI Studio (streamGenerateContent, SSE)."""
    # `alt=sse` makes the endpoint emit `data: {...}` lines; the API key
    # travels in a header so it never ends up in a logged URL.
    url = f"{base_url}/models/{model}:streamGenerateContent?alt=sse"
    headers = {"x-goog-api-key": api_key}

    body = payload(client, messages, temperature, max_tokens)

    usage_events: List[Dict] = []
    received: List[str] = []
    try:
        response = client._make_request(url, body, headers, timeout, stream=True)
        try:
            for chunk in client._bounded_text(client._iter_sse_google(response, usage_events)):
                received.append(chunk)
                yield chunk
        finally:
            close_response(response)
            client._finish_stream_usage("google_ai_studio", usage_events,
                                        messages, "".join(received))
    except AIProviderError:
        raise
    except Exception as e:
        raise AIProviderError(
            f"google_ai_studio stream error: {redact_url(str(e))}"
        ) from e
