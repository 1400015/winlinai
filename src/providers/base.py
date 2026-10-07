"""Base provider interface for AI providers.

Defines the common contract that all providers must implement.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional


@dataclass
class ProviderConfig:
    """Configuration for a provider."""
    name: str
    api_key: str
    base_url: str
    model: str
    timeout: int = 30
    extra: Optional[Dict[str, Any]] = None


@dataclass
class ProviderResponse:
    """Response from a provider."""
    content: str
    usage: Optional[Dict[str, int]] = None  # {"input": int, "output": int, "total": int}
    raw: Optional[Dict[str, Any]] = None


class BaseProvider:
    """Base class for AI providers.

    Subclasses must implement:
    - chat(): Send messages and return a response
    - stream_chat(): Stream a response chunk by chunk
    """

    name: str = "base"

    def __init__(self, config: ProviderConfig):
        self.config = config

    def chat(self, messages: List[Dict[str, str]],
             temperature: float = 0.7,
             max_tokens: int = 2000) -> ProviderResponse:
        """Send messages and return a response."""
        raise NotImplementedError

    def stream_chat(self, messages: List[Dict[str, str]],
                    temperature: float = 0.7,
                    max_tokens: int = 2000) -> Iterator[str]:
        """Stream a response chunk by chunk."""
        raise NotImplementedError

    def supports_images(self) -> bool:
        """Whether this provider supports image inputs."""
        return False

    def supports_streaming(self) -> bool:
        """Whether this provider supports streaming."""
        return True
