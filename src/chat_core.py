"""GUI-free chat request core shared by the GTK and Qt tracks.

Both shells must take the same routing, context-budget and provider
decisions. This module owns those contracts and never imports GTK or Qt, so
the decisions stay testable without a display and cannot drift between the
two interfaces.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

MAX_LOG_CHARS = 131072
MAX_CONTEXT_MESSAGES = 20
MAX_CONTEXT_CHARS = 12000


def offline_reply_text(offline_assistant, message, lang="en"):
    """Pure send path: run the offline assistant and return its answer.

    Kept GUI-free so the routing contract (including failure handling) is
    testable without PySide6 or GTK, exactly like the GTK track's decision
    points.
    """
    message = (message or "").strip()
    if not message:
        return None
    try:
        reply = offline_assistant.handle(message, lang)
        return reply.text if reply is not None else None
    except Exception as error:
        logger.error("Offline assistant failed: %s", type(error).__name__)
        return None


def append_is_bounded(log_chars, chunk):
    """Pure bound decision for the message log."""
    return log_chars + len(chunk) <= MAX_LOG_CHARS


def limit_context(messages, max_messages, max_chars):
    """Truncate a message list to the configured budget without mutating it.

    Keeps the newest messages, then drops the oldest while the character
    total exceeds max_chars, always keeping at least the newest message.
    """
    bounded = list(messages)
    if len(bounded) > max_messages:
        bounded = bounded[-max_messages:]
    total = sum(len(message["content"]) for message in bounded)
    while len(bounded) > 1 and total > max_chars:
        removed = bounded.pop(0)
        total -= len(removed["content"])
    return bounded


def apply_context_budget(messages, max_messages, max_chars):
    """Return a truncated copy of the request messages within the budget.

    Same contract as the GTK track (_build_request_messages): keep the
    last max_messages, then drop the oldest while the character total
    exceeds max_chars, always keeping at least the newest message. The
    system message provider_reply_text prepends is not part of this
    count. The input list is never modified.
    """
    bounded = [dict(message) for message in messages
               if message.get("role") in ("user", "assistant") and message.get("content")]
    return limit_context(bounded, max_messages, max_chars)


def request_budget(config_manager):
    """Read the configured context budget with GTK-safe_number semantics.

    Out-of-range or invalid values fall back to the defaults; there are no
    clamps (1 and 501 both mean the default, like theme_utils.safe_number).
    """
    from .theme_utils import safe_number
    max_messages = safe_number(
        config_manager.get("context.max_messages"), MAX_CONTEXT_MESSAGES,
        int, minimum=2, maximum=500)
    max_chars = safe_number(
        config_manager.get("context.max_chars"), MAX_CONTEXT_CHARS,
        int, minimum=1000, maximum=400000)
    return max_messages, max_chars


def provider_reply_text(ai_client, messages, lang="en", image_paths=None, cancel_event=None,
                        expert=False, distro=None, query="", context=None):
    """Pure send path: call the AI provider and return its answer.

    Args:
        ai_client: AIClient instance
        messages: List of message dicts
        lang: Language code for system prompt
        image_paths: Optional list of image file paths to attach
        cancel_event: Optional threading.Event; when set, the request is
            aborted via AIClient's AIRequestCancelled (no offline fallback).
        expert: Expert mode flag for the system message
        distro: DistroInfo for the system message (None on Windows)
        query: User query for knowledge context in the system message
        context: System context snapshot for the system message

    Returns (text, error) where error is None on success.
    Error "cancelled" means the user aborted (AIRequestCancelled).
    """
    if ai_client is None:
        return None, "no-client"
    try:
        from .assistant_context import build_system_message
        system_message = build_system_message(
            expert=expert, distro=distro, query=query, lang=lang, context=context)
        full_messages = [system_message] + list(messages)

        # image_paths are already-prepared ImageAttachment objects (prepared
        # and validated on the UI thread before this worker started). Validate
        # the immutable snapshot once more; on any failure the request is
        # refused - it is never sent without the image the user attached.
        images: Optional[list] = None
        if image_paths:
            from .image_attachments import ImageAttachmentError, validate_attachment
            validated = []
            for attachment in image_paths:
                try:
                    validate_attachment(attachment)
                except ImageAttachmentError as error:
                    return None, "image:{}".format(error)
                validated.append(attachment)
            images = validated

        response = ai_client.chat(full_messages, images=images, cancel_event=cancel_event)
        if response:
            return response, None
        return None, "empty-response"
    except Exception as error:
        from .ai_client import AIRequestCancelled
        if isinstance(error, AIRequestCancelled):
            logger.info("Provider request cancelled by user")
            return None, "cancelled"
        logger.error("AI provider failed: %s", type(error).__name__)
        return None, type(error).__name__


def should_use_provider(ai_client, config_manager):
    """Decide whether to use the AI provider or the offline assistant.

    Returns True when an AI provider is configured and ready. The active
    provider and assistance mode are resolved by the client, the same
    component the request itself uses: a selection change (offline or
    local mode) must be honoured by the very next request, not just by
    the provider indicator.
    """
    if ai_client is None:
        return False
    # The assistance mode and the active provider are resolved by the
    # client, the same component the request itself uses: a selection
    # change (offline or local mode) must be honoured by the very next
    # request, not just by the provider indicator. Offline mode disables
    # the provider; local mode requires the local settings to name a
    # server; otherwise the configured-key checks below decide.
    if hasattr(ai_client, "active_provider"):
        # The selection is resolved by the client, the same component the
        # request itself uses. A refused selection and any unexpected
        # failure in that resolution both propagate: neither is offline.
        selected = ai_client.active_provider()
        if selected is None:
            return False
        if selected == "local_llm":
            try:
                base_url = ai_client._local_settings()["base_url"]
                return bool(base_url)
            except Exception:
                return False
    try:
        # Check if any provider has an API key configured
        for provider in ("openrouter", "google_ai_studio", "anthropic",
                         "mistral", "groq", "cohere"):
            try:
                key = config_manager.get_api_key(provider)
                if key:
                    return True
            except Exception:
                pass
        # A local LLM counts only when it is the configured active provider;
        # the default base_url with zero keys and no active selection must
        # not present a provider as ready (the chat would dispatch to a
        # worker that cannot answer).
        try:
            provider = config_manager.get("api.provider")
            if provider == "local_llm":
                base_url = config_manager.get("api.providers.local_llm.base_url")
                if base_url:
                    return True
        except Exception:
            pass
    except Exception:
        pass
    return False
