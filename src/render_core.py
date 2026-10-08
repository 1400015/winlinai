"""Render helpers for chat text.

`from __future__ import annotations` keeps the PEP 604 unions (`int | None`)
and builtin generics (`tuple[int, int]`) as strings at runtime, so this
module imports on Python 3.8 (without it, the annotations are evaluated at
import time and `X | None` raises TypeError before 3.10).
"""
from __future__ import annotations

import os
import re
import xml.sax.saxutils

CODE_RE = re.compile(r"```(\S*)\n(.*?)```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")


def esc(text: str) -> str:
    """Escape text for safe inclusion in Pango/markup."""
    return xml.sax.saxutils.escape(text)


_WIN_PATH_RE = re.compile(
    r"^[A-Za-z]:[\\/][^\0]*$"     # drive letter with \ or /
    r"|^\\\\[^\\/]+\\[^\\/]+.*$"  # UNC \\server\share...
    r"|^//[^/]+/[^/]+.*$")          # UNC //server/share...
_WIN_PATH_FIRST_LINE_RE = re.compile(
    r"^[A-Za-z]:[\\/][^\0]*$"
    r"|^\\\\[^\\/]+\\[^\\/]+.*$"
    r"|^//[^/]+/[^/]+.*$")


def _is_absolute_path_line(line: str) -> bool:
    """True for an absolute POSIX or Windows path, without resolving it.

    The decision is lexical only: no expanduser/expandvars/normpath/abspath,
    and it never opens the path. Security stays in WindowsFileActions and
    write_file_safe, which refuse links, junctions and sensitive paths.
    """
    return bool(_WIN_PATH_RE.match(line))


class FileBlock:
    """A ``` block with a file path on the first line."""

    def __init__(self, path, content):
        self.path = path
        self.content = content

    @classmethod
    def _from_header(cls, header: str, body: str):
        """A path in the fence's info string; the body is the content."""
        if header.startswith("/") or header.startswith("~/"):
            return cls(os.path.expanduser(header), body)
        if _WIN_PATH_RE.match(header):
            return cls(header, body)
        return None

    @classmethod
    def _from_first_line(cls, body: str):
        """An empty info string: the first body line is the path only when
        it is an absolute path of a known form. The rest is the content."""
        stripped = body.lstrip("\r\n")
        lines = stripped.split("\n", 1)
        if len(lines) < 2:
            return None
        first, content = lines[0].strip("\r"), lines[1]
        if not _WIN_PATH_FIRST_LINE_RE.match(first):
            return None
        return cls(first, content)

    @classmethod
    def parse_all(cls, text):
        blocks = []
        for match in CODE_RE.finditer(text):
            header = match.group(1).strip()
            body = match.group(2)
            block = cls._from_header(header, body)
            if block is None and not header:
                # A language label (```python) is not a path; a relative
                # name (foo.py, ..\..\Windows) is not a path either.
                block = cls._from_first_line(body)
            if block is not None:
                blocks.append(block)
        return blocks


def _inline_to_markup(text: str) -> str:
    parts = []
    pos = 0
    for m in INLINE_CODE_RE.finditer(text):
        parts.append(esc(text[pos:m.start()]))
        parts.append(
            "<span font_family='monospace' background='#2a2a30'>%s</span>"
            % esc(m.group(1)))
        pos = m.end()
    parts.append(esc(text[pos:]))
    return "".join(parts)


def _code_block_to_markup(body: str) -> str:
    """Render a fenced block as a monospace span (escaped, never raw)."""
    return ("<span font_family='monospace' background='#2a2a30'>%s</span>"
            % esc(body))


CODE_BLOCK_TAG = "code-block"
INLINE_CODE_TAG = "inline-code"


def code_ranges(text: str) -> list[tuple[int, int, str]]:
    """Return `(start, end, tag)` spans for fenced blocks and inline code.

    Offsets are relative to `text`, so a caller can apply the tags to a region
    that is already in the chat buffer without re-inserting (and therefore
    without disturbing) the text.
    """
    ranges: list[tuple[int, int, str]] = []
    for match in CODE_RE.finditer(text):
        ranges.append((match.start(), match.end(), CODE_BLOCK_TAG))

    # Inline code, but only outside fenced blocks: mask them out first so a
    # backtick inside a block cannot produce a bogus nested span.
    masked = list(text)
    for start, end, _tag in ranges:
        for index in range(start, end):
            masked[index] = "\0"
    for match in INLINE_CODE_RE.finditer("".join(masked)):
        inner = match.group(1)
        if "\0" not in inner:
            # Strip the surrounding backticks.
            ranges.append((match.start() + 1, match.end() - 1, INLINE_CODE_TAG))

    ranges.sort()
    return ranges


def render_text_markup(text: str) -> str:
    parts = []
    pos = 0
    for m in CODE_RE.finditer(text):
        parts.append(_inline_to_markup(text[pos:m.start()]))
        # The block itself must be emitted: the old loop advanced `pos` past
        # it without appending anything, so every fenced block disappeared
        # from the rendered text.
        parts.append(_code_block_to_markup(m.group(2)))
        pos = m.end()
    parts.append(_inline_to_markup(text[pos:]))
    return "".join(parts)


# --- Chat buffer logic (GTK-free, so it can be tested headless) -----------
#
# The "Thinking..." placeholder and the streaming response are inserted into
# the same Gtk.TextBuffer. Searching for the "[AI]" line to delete was
# fragile: the response also starts with "[AI]", so the search deleted the
# entire response. The fix is to store the exact offset interval of the
# placeholder and delete only that interval.

def placeholder_span(char_count_before: int, text: str) -> tuple[int, int]:
    """Interval (start, end) occupied by `text` inserted starting at `char_count_before`."""
    start = max(0, int(char_count_before))
    return start, start + len(text)


def valid_span(start: int | None, end: int | None, char_count: int) -> tuple[int, int] | None:
    """Return (start, end) if the interval is usable in the buffer, or None.

    Guards against stale offsets: if the buffer shrank (or nothing was
    inserted), the operation is a no-op instead of corrupting the text.
    """
    if start is None or end is None:
        return None
    start, end = int(start), int(end)
    if start < 0 or start >= end or end > int(char_count):
        return None
    return start, end


def header_offset(char_count_before: int, label: str) -> int:
    """Offset of the end of the ``\\n[label]\\n`` header inside a message."""
    return max(0, int(char_count_before)) + len("\n[%s]\n" % label)

