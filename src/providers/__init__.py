"""Provider plugin package for the AI client.

Each provider implements a common interface for chat and streaming.
Extracted from ai_client.py to reduce its size and improve modularity.
"""
from .base import BaseProvider, ProviderConfig, ProviderResponse
from .openai_compatible import OpenAICompatibleProvider
from .google import GoogleProvider
from .anthropic import AnthropicProvider
from .cohere import CohereProvider

__all__ = [
    "BaseProvider",
    "ProviderConfig",
    "ProviderResponse",
    "OpenAICompatibleProvider",
    "GoogleProvider",
    "AnthropicProvider",
    "CohereProvider",
]
