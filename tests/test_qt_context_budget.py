"""The Qt request respects the configured context budget (GTK parity)."""
import unittest
from unittest.mock import Mock

from src.qt_chat import (
    MAX_CONTEXT_CHARS,
    MAX_CONTEXT_MESSAGES,
    apply_context_budget,
    request_budget,
)


def _config(max_messages=None, max_chars=None):
    values = {}
    if max_messages is not None:
        values["context.max_messages"] = max_messages
    if max_chars is not None:
        values["context.max_chars"] = max_chars
    config = Mock()
    config.get = Mock(side_effect=lambda key, default=None: values.get(key, default))
    return config


class TestApplyContextBudget(unittest.TestCase):
    def test_twenty_five_short_messages_keeps_last_twenty(self):
        messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": "m{}".format(i)}
                    for i in range(25)]
        bounded = apply_context_budget(messages, 20, 12000)
        self.assertEqual(len(bounded), 20)
        self.assertEqual(bounded[0]["content"], "m5")
        self.assertEqual(bounded[-1]["content"], "m24")
        # The original list is untouched.
        self.assertEqual(len(messages), 25)

    def test_character_budget_drops_oldest_until_it_fits(self):
        messages = [
            {"role": "user", "content": "a" * 600},
            {"role": "assistant", "content": "b" * 600},
            {"role": "user", "content": "c" * 600},
        ]
        # Budget 1000: 1800 total -> drop the oldest (600), 1200 -> drop again
        # would reach 600 but two messages sum 1200, so one more drop leaves
        # only the newest.
        bounded = apply_context_budget(messages, 20, 1000)
        self.assertEqual(len(bounded), 1)
        self.assertEqual(bounded[0]["content"], "c" * 600)

    def test_oversized_last_message_is_sent_alone(self):
        messages = [
            {"role": "user", "content": "small"},
            {"role": "assistant", "content": "also small"},
            {"role": "user", "content": "x" * 5000},
        ]
        bounded = apply_context_budget(messages, 20, 1000)
        self.assertEqual(len(bounded), 1)
        self.assertEqual(bounded[0]["content"], "x" * 5000)

    def test_input_is_copied_not_mutated(self):
        messages = [{"role": "user", "content": "a" * 600},
                    {"role": "assistant", "content": "b" * 600}]
        apply_context_budget(messages, 20, 1000)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["content"], "a" * 600)

    def test_only_user_and_assistant_enter_the_request(self):
        messages = [
            {"role": "system", "content": "system noise"},
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
        ]
        bounded = apply_context_budget(messages, 20, 12000)
        self.assertEqual([m["role"] for m in bounded], ["user", "assistant"])

    def test_just_added_user_message_survives(self):
        messages = [{"role": "user", "content": "old{}".format(i)} for i in range(30)]
        messages.append({"role": "user", "content": "just added"})
        bounded = apply_context_budget(messages, 20, 12000)
        self.assertEqual(bounded[-1]["content"], "just added")


class TestRequestBudget(unittest.TestCase):
    def test_defaults_when_unset(self):
        max_messages, max_chars = request_budget(_config())
        self.assertEqual(max_messages, MAX_CONTEXT_MESSAGES)
        self.assertEqual(max_chars, MAX_CONTEXT_CHARS)

    def test_invalid_values_fall_back_without_clamping(self):
        for bad in ("abc", 1, 501, None):
            max_messages, _ = request_budget(_config(max_messages=bad))
            self.assertEqual(max_messages, 20, "value {!r}".format(bad))
        for bad in ("abc", 999, 400001, None):
            _, max_chars = request_budget(_config(max_chars=bad))
            self.assertEqual(max_chars, 12000, "value {!r}".format(bad))

    def test_valid_values_pass_through(self):
        max_messages, max_chars = request_budget(_config(max_messages=5, max_chars=2000))
        self.assertEqual(max_messages, 5)
        self.assertEqual(max_chars, 2000)


if __name__ == "__main__":
    unittest.main()


class TestBudgetNeverTouchesHistory(unittest.TestCase):
    def test_history_store_is_not_written_or_cleared(self):
        import tempfile
        from pathlib import Path
        from src.history_store import HistoryStore
        directory = tempfile.mkdtemp()
        store = HistoryStore(str(Path(directory) / "history.json"))
        self.addCleanup(store.close)
        for index in range(30):
            store.append("user" if index % 2 == 0 else "assistant", "message {}".format(index))
        store.flush()
        before = store.load_messages()
        # A send-sized list goes through the budget; the store keeps every
        # message and is not truncated by the request construction.
        bounded = apply_context_budget(
            [{"role": "user", "content": "message {}".format(i)} for i in range(30)],
            20, 12000)
        self.assertEqual(len(bounded), 20)
        after = store.load_messages()
        self.assertEqual(len(after), len(before))
        self.assertEqual(len(after), 30)
