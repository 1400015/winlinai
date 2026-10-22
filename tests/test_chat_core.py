"""The GUI-free chat core is shared by the GTK and Qt tracks."""
import ast
import inspect
import unittest
from pathlib import Path
from unittest.mock import Mock

from src import chat_core
from src.chat_core import (
    MAX_CONTEXT_CHARS,
    MAX_CONTEXT_MESSAGES,
    apply_context_budget,
    limit_context,
    offline_reply_text,
    request_budget,
    should_use_provider,
)


ROOT = Path(__file__).resolve().parents[1]


def _config(max_messages=None, max_chars=None):
    values = {}
    if max_messages is not None:
        values["context.max_messages"] = max_messages
    if max_chars is not None:
        values["context.max_chars"] = max_chars
    config = Mock()
    config.get = Mock(side_effect=lambda key, default=None: values.get(key, default))
    config.get_api_key = Mock(return_value=None)
    return config


class _Assistant:
    def __init__(self, answer="answer", error=None):
        self.answer = answer
        self.error = error

    def handle(self, message, lang="en"):
        if self.error is not None:
            raise self.error
        return type("Reply", (), {"text": self.answer})()


class _Client:
    def __init__(self, selected, base_url=""):
        self.selected = selected
        self.base_url = base_url

    def active_provider(self):
        return self.selected

    def _local_settings(self):
        return {"base_url": self.base_url}


class TestLimitContext(unittest.TestCase):
    def test_keeps_newest_and_respects_both_budgets(self):
        messages = [{"role": "user", "content": "m{}".format(i)} for i in range(30)]
        bounded = limit_context(messages, 20, 12000)
        self.assertEqual(len(bounded), 20)
        self.assertEqual(bounded[0]["content"], "m10")
        self.assertEqual(bounded[-1]["content"], "m29")
        self.assertEqual(len(messages), 30)

    def test_character_budget_keeps_the_newest_message_alone(self):
        messages = [{"role": "user", "content": "a" * 600},
                    {"role": "assistant", "content": "b" * 600},
                    {"role": "user", "content": "c" * 600}]
        bounded = limit_context(messages, 20, 1000)
        self.assertEqual(len(bounded), 1)
        self.assertEqual(bounded[0]["content"], "c" * 600)

    def test_gtk_and_qt_share_the_same_budget_contract(self):
        messages = [{"role": "user" if i % 2 == 0 else "assistant",
                     "content": "m{}".format(i)} for i in range(25)]
        self.assertEqual(apply_context_budget(messages, 5, 12000),
                         limit_context(messages[-5:], 5, 12000))


class TestRequestBudget(unittest.TestCase):
    def test_defaults_when_unset(self):
        max_messages, max_chars = request_budget(_config())
        self.assertEqual(max_messages, MAX_CONTEXT_MESSAGES)
        self.assertEqual(max_chars, MAX_CONTEXT_CHARS)

    def test_invalid_values_fall_back_without_clamping(self):
        for bad in ("abc", 1, 501, None):
            max_messages, _ = request_budget(_config(max_messages=bad))
            self.assertEqual(max_messages, MAX_CONTEXT_MESSAGES, "value {!r}".format(bad))
        for bad in ("abc", 999, 400001, None):
            _, max_chars = request_budget(_config(max_chars=bad))
            self.assertEqual(max_chars, MAX_CONTEXT_CHARS, "value {!r}".format(bad))


class TestOfflineReply(unittest.TestCase):
    def test_empty_message_never_reaches_the_assistant(self):
        self.assertIsNone(offline_reply_text(_Assistant(), "   "))

    def test_answer_is_returned(self):
        self.assertEqual(offline_reply_text(_Assistant("local"), "hi"), "local")

    def test_failure_is_contained(self):
        self.assertIsNone(offline_reply_text(_Assistant(error=RuntimeError("boom")), "hi"))


class TestShouldUseProvider(unittest.TestCase):
    def test_no_client_is_offline(self):
        self.assertFalse(should_use_provider(None, _config()))

    def test_offline_selection_is_respected(self):
        self.assertFalse(should_use_provider(_Client(None), _config()))

    def test_configured_key_selects_the_provider(self):
        config = _config()
        config.get_api_key.return_value = "key"
        self.assertTrue(should_use_provider(_Client("openrouter"), config))

    def test_missing_key_without_local_selection_is_offline(self):
        self.assertFalse(should_use_provider(_Client("openrouter"), _config()))

    def test_local_selection_requires_a_base_url(self):
        self.assertFalse(should_use_provider(_Client("local_llm"), _config()))
        self.assertTrue(should_use_provider(_Client("local_llm", "http://localhost:1234"), _config()))


class TestCoreBoundary(unittest.TestCase):
    def test_core_imports_no_gui_toolkit(self):
        tree = ast.parse(inspect.getsource(chat_core))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertFalse(imported & {"PySide6", "gi", "gtk", "PyQt5", "PyQt6"})

    def test_both_shells_import_the_shared_core(self):
        qt_source = (ROOT / "src" / "qt_chat.py").read_text(encoding="utf-8")
        gtk_source = (ROOT / "src" / "main_window.py").read_text(encoding="utf-8")
        self.assertIn("from .chat_core import", qt_source)
        self.assertIn("from .chat_core import", gtk_source)
        self.assertIn("request_budget", gtk_source)
        self.assertIn("limit_context", gtk_source)


if __name__ == "__main__":
    unittest.main()
