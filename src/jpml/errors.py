"""Exception hierarchy for the ``.jp`` (JSOML) configuration format.

All errors raised by this package derive from :class:`JPError`, so callers can
catch everything with a single ``except JPError``.  The decode error also
derives from :class:`ValueError` and the encode error from :class:`TypeError`,
which keeps the module drop-in compatible with code written against
:mod:`json`.
"""

from __future__ import annotations

__all__ = ["JPError", "JPDecodeError", "JPEncodeError"]


def _line_col(doc: str, pos: int) -> tuple[int, int]:
    """Return the 1-based ``(line, column)`` of *pos* inside *doc*."""
    line = doc.count("\n", 0, pos) + 1
    col = pos - doc.rfind("\n", 0, pos)
    return line, col


class JPError(Exception):
    """Base class for every error raised by :mod:`jsoml`."""


class JPEncodeError(JPError, TypeError):
    """Raised when a Python object cannot be serialised to ``.jp``."""


class JPDecodeError(JPError, ValueError):
    """Raised when a ``.jp`` document is malformed.

    The rendered message points at the exact offending character, for example::

        servers.jp:4:3: expected ':' after key 'prefix'
            prefix "!"
              ^

    Attributes:
        raw_message: The message without the location prefix or source excerpt.
        doc: The full source text that was being parsed.
        pos: Zero-based character offset of the error inside ``doc``.
        line: One-based line number of the error.
        col: One-based column number of the error.
        filename: Name of the file the text came from, if known.
    """

    def __init__(
        self,
        message: str,
        doc: str = "",
        pos: int = 0,
        *,
        filename: str | None = None,
    ) -> None:
        self.raw_message = message
        self.doc = doc
        self.pos = max(0, min(pos, len(doc)))
        self.filename = filename
        self.line, self.col = _line_col(doc, self.pos)
        super().__init__(self._render())

    def _render(self) -> str:
        location = f"{self.filename or '<string>'}:{self.line}:{self.col}"
        parts = [f"{location}: {self.raw_message}"]
        lines = self.doc.splitlines()
        if 0 < self.line <= len(lines):
            source = lines[self.line - 1].rstrip("\r")
            # Keep tabs in the caret prefix so the marker stays aligned.
            prefix = "".join(c if c == "\t" else " " for c in source[: self.col - 1])
            parts.append(f"    {source}")
            parts.append(f"    {prefix}^")
        return "\n".join(parts)
