"""OpenAI-compatible provider (OpenRouter, Mistral, Groq, Local LLM).

These providers share the same API contract:
- Endpoint: /chat/completions
- Payload: {"messages": [...], "model": "..."}
- Response: {"choices": [{"message": {"content": "..."}}]}
"""
from __future__ import annotations

import json
import logging
from typing import Dict, Iterator, List, Optional

from .base import BaseProvider, ProviderConfig, ProviderResponse

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(BaseProvider):
    """Provider for OpenAI-compatible APIs.

    Used by: OpenRouter, Mistral, Groq, Local LLM (Ollama)
    """

    def __init__(self, config: ProviderConfig, session=None):
        super().__init__(config)
        self.session = session

    def _build_payload(self, messages: List[Dict[str, str]],
                       temperature: float, max_tokens: int,
                       stream: bool = False) -> Dict:
        """Build the API payload."""
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _build_headers(self) -> Dict[str, str]:
        """Build request headers."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }
        # OpenRouter-specific headers
        if self.config.name == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/1400015/winlinai"
            headers["X-Title"] = "WinLinAI"
        return headers

    def _get_url(self) -> str:
        """Get the API endpoint URL."""
        return f"{self.config.base_url.rstrip('/')}/chat/completions"

    def chat(self, messages: List[Dict[str, str]],
             temperature: float = 0.7,
             max_tokens: int = 2000) -> ProviderResponse:
        """Send a chat request."""
        import requests

        url = self._get_url()
        payload = self._build_payload(messages, temperature, max_tokens)
        headers = self._build_headers()

        session = self.session or requests.Session()
        response = session.post(
            url,
            json=payload,
            headers=headers,
            timeout=self.config.timeout,
        )
        response.raise_for_status()

        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            return ProviderResponse(content="", raw=data)

        content = (choices[0].get("message") or {}).get("content") or ""
        usage = self._extract_usage(data)

        return ProviderResponse(content=content, usage=usage, raw=data)

    def stream_chat(self, messages: List[Dict[str, str]],
                    temperature: float = 0.7,
                    max_tokens: int = 2000) -> Iterator[str]:
        """Stream a chat response."""
        import requests

        url = self._get_url()
        payload = self._build_payload(messages, temperature, max_tokens, stream=True)
        headers = self._build_headers()

        session = self.session or requests.Session()
        response = session.post(
            url,
            json=payload,
            headers=headers,
            timeout=self.config.timeout,
            stream=True,
        )
        response.raise_for_status()

        for line in response.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8")
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    choices = data.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content
                except json.JSONDecodeError:
                    continue

    def _extract_usage(self, data: Dict) -> Optional[Dict[str, int]]:
        """Extract token usage from response."""
        usage = data.get("usage")
        if not usage:
            return None
        return {
            "input": usage.get("prompt_tokens", 0),
            "output": usage.get("completion_tokens", 0),
            "total": usage.get("total_tokens", 0),
        }
