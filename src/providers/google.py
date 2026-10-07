"""Google AI Studio provider (Gemini).

API contract:
- Endpoint: /v1/models/{model}:generateContent
- Payload: {"contents": [...]}
- Response: {"candidates": [{"content": {"parts": [{"text": "..."}]}}]}
"""
from __future__ import annotations

import logging
from typing import Dict, Iterator, List, Optional

from .base import BaseProvider, ProviderConfig, ProviderResponse

logger = logging.getLogger(__name__)


class GoogleProvider(BaseProvider):
    """Provider for Google AI Studio (Gemini models)."""

    name = "google_ai_studio"

    def __init__(self, config: ProviderConfig, session=None):
        super().__init__(config)
        self.session = session

    def _build_payload(self, messages: List[Dict[str, str]],
                       temperature: float, max_tokens: int) -> Dict:
        """Build the API payload (Google format)."""
        # Convert OpenAI messages format to Google contents format
        contents = []
        for msg in messages:
            role = msg.get("role", "user")
            if role == "system":
                # Google doesn't have system role; prepend to first user message
                continue
            google_role = "user" if role == "user" else "model"
            contents.append({
                "role": google_role,
                "parts": [{"text": msg.get("content", "")}],
            })

        return {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

    def _get_url(self, stream: bool = False) -> str:
        """Get the API endpoint URL."""
        method = "streamGenerateContent" if stream else "generateContent"
        return (f"{self.config.base_url.rstrip('/')}/v1/models/"
                f"{self.config.model}:{method}?key={self.config.api_key}")

    def chat(self, messages: List[Dict[str, str]],
             temperature: float = 0.7,
             max_tokens: int = 2000) -> ProviderResponse:
        """Send a chat request."""
        import requests

        url = self._get_url()
        payload = self._build_payload(messages, temperature, max_tokens)

        session = self.session or requests.Session()
        response = session.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=self.config.timeout,
        )
        response.raise_for_status()

        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return ProviderResponse(content="", raw=data)

        content = ""
        parts = candidates[0].get("content", {}).get("parts", [])
        for part in parts:
            content += part.get("text", "")

        usage = self._extract_usage(data)
        return ProviderResponse(content=content, usage=usage, raw=data)

    def stream_chat(self, messages: List[Dict[str, str]],
                    temperature: float = 0.7,
                    max_tokens: int = 2000) -> Iterator[str]:
        """Stream a chat response."""
        import json
        import requests

        url = self._get_url(stream=True) + "&alt=sse"
        payload = self._build_payload(messages, temperature, max_tokens)

        session = self.session or requests.Session()
        response = session.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
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
                try:
                    data = json.loads(data_str)
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        for part in parts:
                            text = part.get("text")
                            if text:
                                yield text
                except json.JSONDecodeError:
                    continue

    def _extract_usage(self, data: Dict) -> Optional[Dict[str, int]]:
        """Extract token usage from response."""
        usage = data.get("usageMetadata")
        if not usage:
            return None
        return {
            "input": usage.get("promptTokenCount", 0),
            "output": usage.get("candidatesTokenCount", 0),
            "total": usage.get("totalTokenCount", 0),
        }
