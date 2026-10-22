"""Local model servers (Ollama and OpenAI-compatible) chat and streaming."""

from __future__ import annotations

from typing import Dict, List, Optional

from ..ai_errors import AIProviderError, AIRequestCancelled, AIResponseLimitError, redact_url
from . import logger


def _payload(model: str, messages: List[Dict[str, str]], temperature: float,
             max_tokens: int, stream: bool = False) -> Dict:
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if stream:
        body["stream"] = True
    return body


def chat(client, messages: List[Dict[str, str]], model: str, api_key: str,
         base_url: str, temperature: float, max_tokens: int, timeout: int) -> Optional[str]:
    """Communicate with a local model (Ollama, etc)."""
    url = f"{base_url}/chat/completions"
    try:
        return client._chat_openai_style(
            "local_llm", url, _payload(model, messages, temperature, max_tokens),
            {}, timeout,
        )
    except (AIRequestCancelled, AIResponseLimitError):
        raise
    except AIProviderError as e:
        logger.error(f"Local model error: {redact_url(str(e))}")
        return None


def stream(client, messages: List[Dict[str, str]], model: str, api_key: str,
           base_url: str, temperature: float, max_tokens: int, timeout: int):
    url = f"{base_url}/chat/completions"
    yield from client._stream_openai_style(
        "local_llm", url,
        _payload(model, messages, temperature, max_tokens, stream=True),
        {}, timeout, messages,
    )
