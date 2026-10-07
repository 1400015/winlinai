"""Anthropic provider (Claude).

API contract:
- Endpoint: /v1/messages
- Payload: {"model": "...", "messages": [...], "max_tokens": ...}
- Response: {"content": [{"type": "text", "text": "..."}]}
"""
from __future__ import annotations

import json
import logging
from typing import Dict, Iterator, List, Optional

from .base import BaseProvider, ProviderConfig, ProviderResponse

logger = logging.getLogger(__name__)


class AnthropicProvider(BaseProvider):
    """Provider for Anthropic (Claude models)."""

    name = "anthropic"

    def __init__(self, config: ProviderConfig, session=None):
        super().__init__(config)
        self.session = session

    def _build_payload(self, messages: List[Dict[str, str]],
                       temperature: float, max_tokens: int,
                       stream: bool = False) -> Dict:
        """Build the API payload (Anthropic format)."""
        # Extract system message (Anthropic has separate system parameter)
        system_prompt = ""
        anthropic_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            if role == "system":
                system_prompt = msg.get("content", "")
            else:
                anthropic_role = "user" if role == "user" else "assistant"
                anthropic_messages.append({
                    "role": anthropic_role,
                    "content": msg.get("content", ""),
                })

        payload = {
            "model": self.config.model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            payload["system"] = system_prompt
        if stream:
            payload["stream"] = True

        return payload

    def _build_headers(self) -> Dict[str, str]:
        """Build request headers."""
        return {
            "Content-Type": "application/json",
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
        }

    def _get_url(self) -> str:
        """Get the API endpoint URL."""
        return f"{self.config.base_url.rstrip('/')}/v1/messages"

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
        content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")

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
                try:
                    data = json.loads(data_str)
                    if data.get("type") == "content_block_delta":
                        delta = data.get("delta", {})
                        if delta.get("type") == "text_delta":
                            yield delta.get("text", "")
                except json.JSONDecodeError:
                    continue

    def _extract_usage(self, data: Dict) -> Optional[Dict[str, int]]:
        """Extract token usage from response."""
        usage = data.get("usage")
        if not usage:
            return None
        return {
            "input": usage.get("input_tokens", 0),
            "output": usage.get("output_tokens", 0),
            "total": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        }
