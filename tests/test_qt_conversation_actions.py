"""Tests for Qt conversation actions (src/qt_conversation_actions.py)."""
import json
import tempfile
import unittest
from pathlib import Path

from src.qt_conversation_actions import (
    export_to_markdown,
    export_to_json,
    export_to_text,
    export_conversation,
    get_last_assistant_message,
    get_last_user_message,
    count_messages,
    summarize_messages,
)


class TestExportToMarkdown(unittest.TestCase):
    def test_basic_export(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        result = export_to_markdown(messages, "Test Chat")
        self.assertIn("# Test Chat", result)
        self.assertIn("**User**: Hello", result)
        self.assertIn("**AI**: Hi there!", result)

    def test_system_message(self):
        messages = [{"role": "system", "content": "System prompt"}]
        result = export_to_markdown(messages)
        self.assertIn("**System**: System prompt", result)

    def test_empty_messages(self):
        result = export_to_markdown([])
        self.assertIn("# Conversation", result)


class TestExportToJson(unittest.TestCase):
    def test_basic_export(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        result = export_to_json(messages, "Test")
        data = json.loads(result)
        self.assertEqual(data["title"], "Test")
        self.assertEqual(len(data["messages"]), 2)
        self.assertEqual(data["messages"][0]["role"], "user")

    def test_unicode_content(self):
        messages = [{"role": "user", "content": "Olá, mundo! 你好"}]
        result = export_to_json(messages)
        data = json.loads(result)
        self.assertIn("Olá", data["messages"][0]["content"])


class TestExportToText(unittest.TestCase):
    def test_basic_export(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        result = export_to_text(messages)
        self.assertIn("[USER] Hello", result)
        self.assertIn("[ASSISTANT] Hi!", result)


class TestExportConversation(unittest.TestCase):
    def test_export_markdown(self):
        messages = [{"role": "user", "content": "Test"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.md"
            ok, message = export_conversation(messages, str(filepath), "Test")
            self.assertTrue(ok)
            self.assertTrue(filepath.exists())
            content = filepath.read_text(encoding="utf-8")
            self.assertIn("# Test", content)

    def test_export_json(self):
        messages = [{"role": "user", "content": "Test"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.json"
            ok, _message = export_conversation(messages, str(filepath))
            self.assertTrue(ok)
            data = json.loads(filepath.read_text(encoding="utf-8"))
            self.assertEqual(len(data["messages"]), 1)

    def test_export_text(self):
        messages = [{"role": "user", "content": "Test"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.txt"
            ok, _message = export_conversation(messages, str(filepath))
            self.assertTrue(ok)
            content = filepath.read_text(encoding="utf-8")
            self.assertIn("[USER] Test", content)

    def test_export_failure(self):
        messages = [{"role": "user", "content": "Test"}]
        ok, message = export_conversation(messages, "/invalid/path/test.md")
        self.assertFalse(ok)
        self.assertIsNotNone(message)


class TestGetLastMessages(unittest.TestCase):
    def test_get_last_assistant(self):
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "How are you?"},
            {"role": "assistant", "content": "I'm good!"},
        ]
        self.assertEqual(get_last_assistant_message(messages), "I'm good!")

    def test_get_last_assistant_none(self):
        messages = [{"role": "user", "content": "Hi"}]
        self.assertIsNone(get_last_assistant_message(messages))

    def test_get_last_user(self):
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "How are you?"},
        ]
        self.assertEqual(get_last_user_message(messages), "How are you?")

    def test_get_last_user_none(self):
        messages = [{"role": "assistant", "content": "Hello!"}]
        self.assertIsNone(get_last_user_message(messages))


class TestCountMessages(unittest.TestCase):
    def test_count_by_role(self):
        messages = [
            {"role": "user", "content": "1"},
            {"role": "user", "content": "2"},
            {"role": "assistant", "content": "3"},
            {"role": "system", "content": "4"},
        ]
        counts = count_messages(messages)
        self.assertEqual(counts["user"], 2)
        self.assertEqual(counts["assistant"], 1)
        self.assertEqual(counts["system"], 1)
        self.assertEqual(counts["total"], 4)

    def test_empty(self):
        counts = count_messages([])
        self.assertEqual(counts["total"], 0)


class TestSummarizeMessages(unittest.TestCase):
    def test_basic_summary(self):
        messages = [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "Python is a programming language."},
        ]
        summary = summarize_messages(messages)
        self.assertIn("2 messages", summary)
        self.assertIn("1 user", summary)
        self.assertIn("1 AI", summary)
        self.assertIn("What is Python?", summary)

    def test_max_chars(self):
        messages = [
            {"role": "user", "content": "A" * 1000},
            {"role": "assistant", "content": "B" * 1000},
        ]
        summary = summarize_messages(messages, max_chars=100)
        self.assertLessEqual(len(summary), 100)

    def test_empty(self):
        summary = summarize_messages([])
        self.assertIn("0 messages", summary)


if __name__ == "__main__":
    unittest.main()
