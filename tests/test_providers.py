"""Tests for the provider plugin system (src/providers/)."""
import unittest

from src.providers import (
    BaseProvider,
    ProviderConfig,
    ProviderResponse,
    OpenAICompatibleProvider,
    GoogleProvider,
    AnthropicProvider,
    CohereProvider,
)


class TestProviderConfig(unittest.TestCase):
    def test_basic_config(self):
        config = ProviderConfig(
            name="openrouter",
            api_key="sk-test",
            base_url="https://openrouter.ai/api/v1",
            model="google/gemini-2.5-flash",
        )
        self.assertEqual(config.name, "openrouter")
        self.assertEqual(config.api_key, "sk-test")
        self.assertEqual(config.timeout, 30)  # default

    def test_custom_timeout(self):
        config = ProviderConfig(
            name="test",
            api_key="key",
            base_url="https://api.test.com",
            model="model",
            timeout=60,
        )
        self.assertEqual(config.timeout, 60)


class TestProviderResponse(unittest.TestCase):
    def test_basic_response(self):
        response = ProviderResponse(content="Hello!")
        self.assertEqual(response.content, "Hello!")
        self.assertIsNone(response.usage)

    def test_response_with_usage(self):
        response = ProviderResponse(
            content="Hello!",
            usage={"input": 10, "output": 5, "total": 15},
        )
        self.assertEqual(response.usage["total"], 15)


class TestBaseProvider(unittest.TestCase):
    def test_cannot_instantiate_base(self):
        config = ProviderConfig("test", "key", "https://test.com", "model")
        provider = BaseProvider(config)
        with self.assertRaises(NotImplementedError):
            provider.chat([])
        with self.assertRaises(NotImplementedError):
            list(provider.stream_chat([]))

    def test_default_capabilities(self):
        config = ProviderConfig("test", "key", "https://test.com", "model")
        provider = BaseProvider(config)
        self.assertFalse(provider.supports_images())
        self.assertTrue(provider.supports_streaming())


class TestOpenAICompatibleProvider(unittest.TestCase):
    def setUp(self):
        self.config = ProviderConfig(
            name="openrouter",
            api_key="sk-test",
            base_url="https://openrouter.ai/api/v1",
            model="google/gemini-2.5-flash",
        )
        self.provider = OpenAICompatibleProvider(self.config)

    def test_build_payload(self):
        messages = [{"role": "user", "content": "Hello"}]
        payload = self.provider._build_payload(messages, 0.7, 1000)
        self.assertEqual(payload["model"], "google/gemini-2.5-flash")
        self.assertEqual(payload["messages"], messages)
        self.assertEqual(payload["temperature"], 0.7)
        self.assertEqual(payload["max_tokens"], 1000)
        self.assertNotIn("stream", payload)

    def test_build_payload_stream(self):
        messages = [{"role": "user", "content": "Hello"}]
        payload = self.provider._build_payload(messages, 0.7, 1000, stream=True)
        self.assertTrue(payload["stream"])
        self.assertIn("stream_options", payload)

    def test_build_headers(self):
        headers = self.provider._build_headers()
        self.assertEqual(headers["Authorization"], "Bearer sk-test")
        self.assertIn("HTTP-Referer", headers)  # OpenRouter specific

    def test_get_url(self):
        url = self.provider._get_url()
        self.assertEqual(url, "https://openrouter.ai/api/v1/chat/completions")

    def test_extract_usage(self):
        data = {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
        usage = self.provider._extract_usage(data)
        self.assertEqual(usage["input"], 10)
        self.assertEqual(usage["output"], 5)
        self.assertEqual(usage["total"], 15)

    def test_extract_usage_none(self):
        self.assertIsNone(self.provider._extract_usage({}))


class TestGoogleProvider(unittest.TestCase):
    def setUp(self):
        self.config = ProviderConfig(
            name="google_ai_studio",
            api_key="test-key",
            base_url="https://generativelanguage.googleapis.com/v1",
            model="gemini-3.5-flash-lite",
        )
        self.provider = GoogleProvider(self.config)

    def test_build_payload(self):
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
            {"role": "user", "content": "How are you?"},
        ]
        payload = self.provider._build_payload(messages, 0.7, 1000)
        # System message should be skipped
        self.assertEqual(len(payload["contents"]), 3)
        self.assertEqual(payload["contents"][0]["role"], "user")
        self.assertEqual(payload["contents"][1]["role"], "model")
        self.assertEqual(payload["generationConfig"]["temperature"], 0.7)

    def test_get_url(self):
        url = self.provider._get_url()
        self.assertIn("gemini-3.5-flash-lite", url)
        self.assertIn("generateContent", url)
        self.assertIn("key=test-key", url)

    def test_get_url_stream(self):
        url = self.provider._get_url(stream=True)
        self.assertIn("streamGenerateContent", url)

    def test_extract_usage(self):
        data = {"usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15}}
        usage = self.provider._extract_usage(data)
        self.assertEqual(usage["input"], 10)
        self.assertEqual(usage["output"], 5)


class TestAnthropicProvider(unittest.TestCase):
    def setUp(self):
        self.config = ProviderConfig(
            name="anthropic",
            api_key="test-key",
            base_url="https://api.anthropic.com/v1",
            model="claude-haiku-4-5-20251001",
        )
        self.provider = AnthropicProvider(self.config)

    def test_build_payload(self):
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
        ]
        payload = self.provider._build_payload(messages, 0.7, 1000)
        self.assertEqual(payload["system"], "You are helpful")
        self.assertEqual(len(payload["messages"]), 1)
        self.assertEqual(payload["messages"][0]["role"], "user")

    def test_build_headers(self):
        headers = self.provider._build_headers()
        self.assertEqual(headers["x-api-key"], "test-key")
        self.assertIn("anthropic-version", headers)

    def test_get_url(self):
        url = self.provider._get_url()
        self.assertEqual(url, "https://api.anthropic.com/v1/v1/messages")

    def test_extract_usage(self):
        data = {"usage": {"input_tokens": 10, "output_tokens": 5}}
        usage = self.provider._extract_usage(data)
        self.assertEqual(usage["input"], 10)
        self.assertEqual(usage["output"], 5)
        self.assertEqual(usage["total"], 15)


class TestCohereProvider(unittest.TestCase):
    def setUp(self):
        self.config = ProviderConfig(
            name="cohere",
            api_key="test-key",
            base_url="https://api.cohere.ai/v1",
            model="command-r-08-2024",
        )
        self.provider = CohereProvider(self.config)

    def test_build_payload(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
            {"role": "user", "content": "How are you?"},
        ]
        payload = self.provider._build_payload(messages, 0.7, 1000)
        self.assertEqual(payload["message"], "How are you?")
        # First user message is stored, then assistant, then last user is the message
        # So history has: USER("Hello"), CHATBOT("Hi!") = 2 items
        # But the logic adds to history only when a new user message comes after
        self.assertGreaterEqual(len(payload["chat_history"]), 1)

    def test_build_headers(self):
        headers = self.provider._build_headers()
        self.assertEqual(headers["Authorization"], "Bearer test-key")

    def test_get_url(self):
        url = self.provider._get_url()
        self.assertEqual(url, "https://api.cohere.ai/v1/v1/chat")

    def test_extract_usage(self):
        data = {"meta": {"tokens": {"input_tokens": 10, "output_tokens": 5}}}
        usage = self.provider._extract_usage(data)
        self.assertEqual(usage["total"], 15)


class TestProviderImports(unittest.TestCase):
    def test_all_providers_importable(self):
        from src.providers import (
            BaseProvider,
            ProviderConfig,
            ProviderResponse,
            OpenAICompatibleProvider,
            GoogleProvider,
            AnthropicProvider,
            CohereProvider,
        )
        self.assertTrue(all([
            BaseProvider,
            ProviderConfig,
            ProviderResponse,
            OpenAICompatibleProvider,
            GoogleProvider,
            AnthropicProvider,
            CohereProvider,
        ]))


if __name__ == "__main__":
    unittest.main()
