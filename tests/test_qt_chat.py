"""Tests for Qt chat AI provider integration (src/qt_chat.py)."""
import threading
import unittest
from unittest.mock import Mock

from src.ai_client import AIRequestCancelled
from src.qt_chat import (
    offline_reply_text,
    append_is_bounded,
    provider_reply_text,
    should_use_provider,
    MAX_LOG_CHARS,
)


class TestOfflineReplyText(unittest.TestCase):
    def test_empty_message_returns_none(self):
        assistant = Mock()
        self.assertIsNone(offline_reply_text(assistant, ""))
        self.assertIsNone(offline_reply_text(assistant, "   "))

    def test_returns_reply_text(self):
        assistant = Mock()
        reply = Mock()
        reply.text = "Hello!"
        assistant.handle.return_value = reply
        result = offline_reply_text(assistant, "Hi")
        self.assertEqual(result, "Hello!")
        assistant.handle.assert_called_once()

    def test_returns_none_on_no_reply(self):
        assistant = Mock()
        assistant.handle.return_value = None
        self.assertIsNone(offline_reply_text(assistant, "Hi"))

    def test_handles_exception(self):
        assistant = Mock()
        assistant.handle.side_effect = RuntimeError("boom")
        self.assertIsNone(offline_reply_text(assistant, "Hi"))


class TestAppendIsBounded(unittest.TestCase):
    def test_within_limit(self):
        self.assertTrue(append_is_bounded(0, "hello"))
        self.assertTrue(append_is_bounded(MAX_LOG_CHARS - 10, "hello"))

    def test_exceeds_limit(self):
        self.assertFalse(append_is_bounded(MAX_LOG_CHARS - 3, "hello"))
        self.assertFalse(append_is_bounded(MAX_LOG_CHARS, "x"))


class TestProviderReplyText(unittest.TestCase):
    def test_no_client(self):
        text, error = provider_reply_text(None, [{"role": "user", "content": "Hi"}])
        self.assertIsNone(text)
        self.assertEqual(error, "no-client")

    def test_successful_response(self):
        client = Mock()
        client.chat.return_value = "Hello from AI!"
        messages = [{"role": "user", "content": "Hi"}]
        text, error = provider_reply_text(client, messages)
        self.assertEqual(text, "Hello from AI!")
        self.assertIsNone(error)

    def test_empty_response(self):
        client = Mock()
        client.chat.return_value = None
        messages = [{"role": "user", "content": "Hi"}]
        text, error = provider_reply_text(client, messages)
        self.assertIsNone(text)
        self.assertEqual(error, "empty-response")

    def test_provider_exception(self):
        client = Mock()
        client.chat.side_effect = RuntimeError("API error")
        messages = [{"role": "user", "content": "Hi"}]
        text, error = provider_reply_text(client, messages)
        self.assertIsNone(text)
        self.assertEqual(error, "RuntimeError")

    def test_adds_system_message(self):
        client = Mock()
        client.chat.return_value = "OK"
        messages = [{"role": "user", "content": "Hi"}]
        provider_reply_text(client, messages, lang="pt")
        # Should have added a system message (parity with GTK build_system_message)
        called_messages = client.chat.call_args[0][0]
        self.assertEqual(called_messages[0]["role"], "system")
        self.assertIn("Respond in Portuguese", called_messages[0]["content"])

    def test_system_message_languages(self):
        client = Mock()
        client.chat.return_value = "OK"
        messages = [{"role": "user", "content": "Hi"}]

        provider_reply_text(client, messages, lang="en")
        self.assertIn("Respond in English", client.chat.call_args[0][0][0]["content"])

        provider_reply_text(client, messages, lang="pt")
        self.assertIn("Respond in Portuguese", client.chat.call_args[0][0][0]["content"])

        provider_reply_text(client, messages, lang="es")
        self.assertIn("Respond in Spanish", client.chat.call_args[0][0][0]["content"])

        provider_reply_text(client, messages, lang="fr")
        self.assertIn("Respond in French", client.chat.call_args[0][0][0]["content"])

        provider_reply_text(client, messages, lang="de")
        self.assertIn("Respond in German", client.chat.call_args[0][0][0]["content"])

    def test_system_message_expert_mode(self):
        client = Mock()
        client.chat.return_value = "OK"
        messages = [{"role": "user", "content": "Hi"}]
        provider_reply_text(client, messages, expert=True)
        content = client.chat.call_args[0][0][0]["content"]
        self.assertIn("diagnose", content.lower())

    def test_system_message_without_expert_omits_diagnosis(self):
        client = Mock()
        client.chat.return_value = "OK"
        messages = [{"role": "user", "content": "Hi"}]
        provider_reply_text(client, messages, expert=False)
        content = client.chat.call_args[0][0][0]["content"]
        self.assertNotIn("diagnose Linux systems", content)

    def test_cancel_event_passed_to_client(self):
        client = Mock()
        client.chat.return_value = "OK"
        messages = [{"role": "user", "content": "Hi"}]
        event = threading.Event()
        provider_reply_text(client, messages, cancel_event=event)
        self.assertIs(client.chat.call_args.kwargs["cancel_event"], event)

    def test_cancelled_request_returns_cancelled_error(self):
        client = Mock()
        client.chat.side_effect = AIRequestCancelled("user stop")
        messages = [{"role": "user", "content": "Hi"}]
        text, error = provider_reply_text(
            client, messages, cancel_event=threading.Event())
        self.assertIsNone(text)
        self.assertEqual(error, "cancelled")

    def test_no_cancel_event_defaults_to_none(self):
        client = Mock()
        client.chat.return_value = "OK"
        messages = [{"role": "user", "content": "Hi"}]
        provider_reply_text(client, messages)
        self.assertIsNone(client.chat.call_args.kwargs["cancel_event"])


class TestShouldUseProvider(unittest.TestCase):
    def test_no_client(self):
        config = Mock()
        self.assertFalse(should_use_provider(None, config))

    def test_no_api_keys(self):
        client = Mock()
        config = Mock()
        config.get_api_key = Mock(return_value=None)
        config.get = Mock(return_value=None)
        self.assertFalse(should_use_provider(client, config))

    def test_with_openrouter_key(self):
        client = Mock()
        config = Mock()

        def get_key(provider):
            if provider == "openrouter":
                return "sk-test-key"
            return None

        config.get_api_key = Mock(side_effect=get_key)
        config.get = Mock(return_value=None)
        self.assertTrue(should_use_provider(client, config))

    def test_with_google_key(self):
        client = Mock()
        config = Mock()

        def get_key(provider):
            if provider == "google_ai_studio":
                return "google-key"
            return None

        config.get_api_key = Mock(side_effect=get_key)
        config.get = Mock(return_value=None)
        self.assertTrue(should_use_provider(client, config))

    def test_with_local_llm(self):
        client = Mock()
        config = Mock()
        config.get_api_key = Mock(return_value=None)
        config.get = Mock(side_effect=lambda key, default=None: {
            "api.provider": "local_llm",
            "api.providers.local_llm.base_url": "http://localhost:11434"
        }.get(key, default))
        self.assertTrue(should_use_provider(client, config))

    def test_default_local_url_without_selection_is_not_ready(self):
        """A stock config has a default local URL but no active provider.

        Treating the bare URL as a ready provider dispatches the question to
        a worker that cannot answer (no local server on the machine), which
        is what the wheel smoke test exercised on the Windows runner.
        """
        client = Mock()
        config = Mock()
        config.get_api_key = Mock(return_value=None)
        config.get = Mock(side_effect=lambda key, default=None: {
            "api.providers.local_llm.base_url": "http://localhost:11434/v1"
        }.get(key, default))
        self.assertFalse(should_use_provider(client, config))

    def test_broken_config(self):
        client = Mock()
        config = Mock()
        config.get_api_key = Mock(side_effect=Exception("broken"))
        config.get = Mock(side_effect=Exception("broken"))
        self.assertFalse(should_use_provider(client, config))


if __name__ == "__main__":
    unittest.main()
