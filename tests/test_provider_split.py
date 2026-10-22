"""The provider split must stay complete and free of import cycles."""

import unittest
from pathlib import Path

from src.ai_client import AIClient
from src.ai_providers import (
    anthropic, cohere, google, groq, local_llm, mistral, openrouter,
)


ROOT = Path(__file__).resolve().parents[1]

MODULES = {
    "openrouter": openrouter,
    "google_ai_studio": google,
    "anthropic": anthropic,
    "mistral": mistral,
    "groq": groq,
    "cohere": cohere,
    "local_llm": local_llm,
}


class ProviderSplitTests(unittest.TestCase):
    def test_every_builtin_provider_has_chat_and_stream(self):
        for name, module in MODULES.items():
            with self.subTest(provider=name):
                self.assertTrue(callable(getattr(module, "chat", None)))
                self.assertTrue(callable(getattr(module, "stream", None)))
                self.assertTrue(callable(getattr(AIClient, f"_chat_{name}", None)))
                self.assertTrue(callable(getattr(AIClient, f"_stream_{name}", None)))

    def test_provider_modules_do_not_import_the_client(self):
        for name, module in MODULES.items():
            with self.subTest(provider=name):
                source = Path(module.__file__).read_text(encoding="utf-8")
                self.assertNotIn("ai_client", source)

    def test_the_builtin_list_matches_the_provider_modules(self):
        self.assertEqual(frozenset(MODULES), AIClient.BUILTIN_PROVIDERS)

    def test_the_client_keeps_no_provider_payloads(self):
        module_source = (ROOT / "src" / "ai_client.py").read_text(encoding="utf-8")
        self.assertNotIn("anthropic-version", module_source)
        self.assertNotIn("x-goog-api-key", module_source)


if __name__ == "__main__":
    unittest.main()
