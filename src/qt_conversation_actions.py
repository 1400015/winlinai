"""Qt conversation actions: export, copy, clear, summarize.

Pure logic functions (testable without PySide6) plus thin Qt wrappers
for the chat widget context menu and toolbar.

Actions:
- export_conversation: save to Markdown/JSON/Text
- copy_last_response: copy to clipboard
- clear_conversation: start a new session
- summarize_conversation: ask the AI to summarize
- regenerate_last: re-send the last user message
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from PySide6 import QtCore, QtWidgets
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


# ---------------------------------------------------------------------------
# Pure logic (no Qt required)
# ---------------------------------------------------------------------------

def export_to_markdown(messages: List[Dict], title: str = "Conversation") -> str:
    """Export messages to Markdown format."""
    lines = [f"# {title}", ""]
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if role == "user":
            lines.append(f"**User**: {content}")
        elif role == "assistant":
            lines.append(f"**AI**: {content}")
        elif role == "system":
            lines.append(f"**System**: {content}")
        else:
            lines.append(f"**{role}**: {content}")
        lines.append("")
    return "\n".join(lines)


def export_to_json(messages: List[Dict], title: str = "Conversation") -> str:
    """Export messages to JSON format."""
    data = {
        "title": title,
        "messages": [
            {"role": m.get("role", "unknown"), "content": m.get("content", "")}
            for m in messages
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def export_to_text(messages: List[Dict]) -> str:
    """Export messages to plain text format."""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "")
        lines.append(f"[{role}] {content}")
        lines.append("")
    return "\n".join(lines)


def export_conversation(messages: List[Dict], filepath: str,
                        title: str = "Conversation") -> Tuple[bool, str]:
    """Export conversation to a file. Returns (success, message)."""
    path = Path(filepath)
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            content = export_to_json(messages, title)
        elif suffix == ".txt":
            content = export_to_text(messages)
        else:
            # Default to Markdown
            content = export_to_markdown(messages, title)
        path.write_text(content, encoding="utf-8")
        return True, str(path)
    except Exception as error:
        logger.error("Export failed: %s", type(error).__name__)
        return False, str(error)


def get_last_assistant_message(messages: List[Dict]) -> Optional[str]:
    """Get the content of the last assistant message."""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            return msg.get("content", "")
    return None


def get_last_user_message(messages: List[Dict]) -> Optional[str]:
    """Get the content of the last user message."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return None


def count_messages(messages: List[Dict]) -> Dict[str, int]:
    """Count messages by role."""
    counts = {"user": 0, "assistant": 0, "system": 0, "other": 0}
    for msg in messages:
        role = msg.get("role", "other")
        if role in counts:
            counts[role] += 1
        else:
            counts["other"] += 1
    counts["total"] = len(messages)
    return counts


def summarize_messages(messages: List[Dict], max_chars: int = 500) -> str:
    """Create a brief summary of the conversation (local, no AI)."""
    counts = count_messages(messages)
    first_user = None
    last_assistant = None
    for msg in messages:
        if msg.get("role") == "user" and first_user is None:
            first_user = msg.get("content", "")[:100]
        if msg.get("role") == "assistant":
            last_assistant = msg.get("content", "")[:100]
    summary = f"{counts['total']} messages ({counts['user']} user, {counts['assistant']} AI)"
    if first_user:
        summary += f"\nFirst: {first_user}..."
    if last_assistant:
        summary += f"\nLast: {last_assistant}..."
    return summary[:max_chars]


# ---------------------------------------------------------------------------
# Qt wrappers
# ---------------------------------------------------------------------------

if TYPE_CHECKING or QT_AVAILABLE:
    _BaseMenu = QtWidgets.QMenu
else:
    _BaseMenu = object


class QtConversationMenu(_BaseMenu):
    """Context menu for the chat widget with conversation actions."""

    def __init__(self, chat_widget, parent=None):
        if not QT_AVAILABLE:
            raise RuntimeError("PySide6 is required for QtConversationMenu")
        super().__init__(parent)
        self.chat = chat_widget
        self._build()

    def _build(self):
        from . import i18n

        # Copy last response
        copy_action = self.addAction(i18n._("Copy last response"))
        copy_action.triggered.connect(self._copy_last)

        # Export submenu
        export_menu = self.addMenu(i18n._("Export conversation"))
        for fmt, label in (("md", "Markdown (.md)"),
                           ("json", "JSON (.json)"),
                           ("txt", "Text (.txt)")):
            action = export_menu.addAction(label)
            action.triggered.connect(lambda checked, f=fmt: self._export(f))

        self.addSeparator()

        # Clear conversation
        clear_action = self.addAction(i18n._("New conversation"))
        clear_action.triggered.connect(self._clear)

        # Summary
        summary_action = self.addAction(i18n._("Show summary"))
        summary_action.triggered.connect(self._show_summary)

    def _messages(self) -> List[Dict]:
        """Get current conversation messages from the chat widget."""
        return getattr(self.chat, "_pending_messages", [])

    def _copy_last(self):
        """Copy the last AI response to clipboard."""
        content = get_last_assistant_message(self._messages())
        if content:
            clipboard = QtWidgets.QApplication.clipboard()
            clipboard.setText(content)

    def _export(self, fmt: str):
        """Export conversation to a file."""
        from . import i18n
        messages = self._messages()
        if not messages:
            return
        default_name = f"conversation.{fmt}"
        filters = {
            "md": "Markdown (*.md)",
            "json": "JSON (*.json)",
            "txt": "Text (*.txt)",
        }.get(fmt, "All files (*)")
        filepath, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.chat, i18n._("Export conversation"), default_name, filters)
        if not filepath:
            return
        ok, message = export_conversation(messages, filepath)
        if ok:
            logger.info("Conversation exported to %s", filepath)

    def _clear(self):
        """Start a new conversation."""
        if hasattr(self.chat, "clear_conversation"):
            self.chat.clear_conversation()

    def _show_summary(self):
        """Show a summary of the conversation."""
        from . import i18n
        messages = self._messages()
        summary = summarize_messages(messages)
        QtWidgets.QMessageBox.information(
            self.chat, i18n._("Conversation summary"), summary)


def add_context_menu_to_chat(chat_widget):
    """Add a context menu to the chat log widget."""
    if not QT_AVAILABLE:
        return
    chat_widget.log.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
    menu = QtConversationMenu(chat_widget, chat_widget.log)
    chat_widget.log.customContextMenuRequested.connect(
        lambda pos: menu.exec(chat_widget.log.mapToGlobal(pos)))
