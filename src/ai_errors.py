"""Structured provider failures shared by the client and the provider modules.

These exceptions are re-exported by ``src.ai_client`` so existing callers keep
importing them from the historical location.
"""

from __future__ import annotations

import re

from requests.exceptions import RequestException

from .log_privacy import redact_text


_SECRET_QUERY_RE = re.compile(
    r"([?&](?:key|api_key|apikey|access_token|token|sig|signature|password|auth)=)[^&\s]+",
    re.I,
)


class AIProviderError(RequestException):
    """Falha ESTRUTURADA de provider (rede, HTTP, config) — não é conteúdo.

    Contrato: erros de comunicação NUNCA viajam como chunks de texto do
    modelo. Herda de RequestException para preservar a política de retry
    (`_is_transient` inspeciona `.response`) e para que a UI/CLI possam
    apanhar a falha por tipo em vez de adivinhar por prefixos de string
    (`_is_api_failure` por startswith perdia erros a meio do stream e
    disparava o fallback offline para respostas legítimas que começassem
    por "Error:").
    """


class ProviderNotConfigured(AIProviderError):
    """Provider sem chave/base_url configurados — permanente, sem retry."""


class AIRequestCancelled(AIProviderError):
    """The user cancelled this request; do not retry or fall back offline."""


class AIResponseLimitError(AIProviderError):
    """A provider exceeded local response limits; its response is incomplete."""


class AIImageRequestError(AIProviderError):
    """Image requests fail explicitly and must never fall back to text/OCR."""


class AIUnsupportedImageProvider(AIImageRequestError):
    """This mode or provider does not support reviewed image requests."""


class AIUnsupportedImageModel(AIImageRequestError):
    """The model's image-input capability has not been confirmed locally."""


def redact_url(url: str) -> str:
    """Remove segredos de query strings antes de escrever no log."""
    if not url:
        return url
    return _SECRET_QUERY_RE.sub(r"\1***", url)


def safe_provider_error(value):
    # Redact before truncating: cutting a quoted secret or a token first can
    # prevent recognizing it. This is shared with diagnostics/trial reports.
    return redact_text(redact_url(str(value)))[:500]
