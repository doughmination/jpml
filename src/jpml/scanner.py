"""Character-level scanning primitives for the ``.jp`` format.

The scanner owns the cursor and every *lexical* concern: whitespace, comments,
quoted strings, and the interpretation of bare (unquoted) tokens.  It knows
nothing about the grammar -- that lives in :mod:`jpml.parser`.

The format is deliberately context sensitive (``[`` opens a section header at
the top level but an array everywhere else), so there is no standalone token
stream; the parser drives the scanner directly.
"""

from __future__ import annotations

from .errors import JPDecodeError

__all__ = ["Scanner", "interpret_bare", "KEYWORDS"]

#: Whitespace that never terminates a line.
INLINE_SPACE = " \t\f\v"

#: Characters that end an unquoted value.
VALUE_END = frozenset(",}]\r\n#")

#: Characters that end an unquoted key.  A key normally ends at its colon; the
#: others are listed so that a missing colon is reported at the character that
#: caused it rather than at the end of the line.  A bare key may contain spaces
#: (``my key: 1``) but not brackets or quotes -- quote the key for those.
KEY_END = frozenset(":,{}[]\"'\r\n#")

#: Characters that end one segment of a ``[dotted.header]``.
HEADER_END = frozenset(".]\r\n#")

_ESCAPES = {
    '"': '"',
    "'": "'",
    "\\": "\\",
    "/": "/",
    "0": "\0",
    "a": "\a",
    "b": "\b",
    "e": "\x1b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}

_HEX_WIDTH = {"x": 2, "u": 4, "U": 8}

_HEXDIGITS = frozenset("0123456789abcdefABCDEF")

_INF = float("inf")

_MISSING = object()

#: Bare words with a fixed meaning.  Matched case-insensitively so that both
#: JSON (``true``/``null``) and Python (``True``/``None``) spellings work.
#: Deliberately excludes ``yes``/``no``/``on``/``off``: silently turning those
#: into booleans surprises people more often than it helps.
KEYWORDS: dict[str, object] = {
    "true": True,
    "false": False,
    "null": None,
    "none": None,
    "nil": None,
    "nan": float("nan"),
    "inf": _INF,
    "infinity": _INF,
    "+inf": _INF,
    "+infinity": _INF,
    "-inf": -_INF,
    "-infinity": -_INF,
}


def _parse_number(text: str) -> int | float:
    """Convert *text* to an ``int`` or ``float``, or raise :class:`ValueError`.

    Accepts underscore separators, an optional sign, and the ``0x`` / ``0o`` /
    ``0b`` radix prefixes, mirroring both TOML and Python literals.
    """
    body = text[1:] if text[:1] in "+-" else text
    if not body:
        raise ValueError(text)
    if body[:2].lower() in ("0x", "0o", "0b"):
        return int(text, 0)
    try:
        return int(text, 10)
    except ValueError:
        return float(text)


def interpret_bare(text: str) -> object:
    """Interpret an unquoted token as a Python value.

    Resolution order is keyword, then number, then plain string.  An empty or
    whitespace-only token means "no value" and yields ``None``, which is what
    makes ``disabled_channels:,`` legal.
    """
    token = text.strip()
    if not token:
        return None
    keyword = KEYWORDS.get(token.lower(), _MISSING)
    if keyword is not _MISSING:
        return keyword
    try:
        return _parse_number(token)
    except ValueError:
        return token


class Scanner:
    """A cursor over the source text with lexical helpers.

    Args:
        text: The full document being parsed.
        filename: Optional name used in error messages.
    """

    __slots__ = ("text", "pos", "filename", "_len")

    def __init__(self, text: str, filename: str | None = None) -> None:
        # A UTF-8 BOM is common in files written by Windows editors.
        self.text = text.lstrip("﻿") if text.startswith("﻿") else text
        self.pos = 0
        self.filename = filename
        self._len = len(self.text)

    # -- cursor ----------------------------------------------------------

    @property
    def eof(self) -> bool:
        """Whether the cursor has reached the end of the document."""
        return self.pos >= self._len

    def peek(self, offset: int = 0) -> str | None:
        """Return the character at ``pos + offset``, or ``None`` past the end."""
        index = self.pos + offset
        return self.text[index] if 0 <= index < self._len else None

    def advance(self, count: int = 1) -> None:
        """Move the cursor forward by *count* characters."""
        self.pos += count

    def error(self, message: str, pos: int | None = None) -> JPDecodeError:
        """Build a :class:`JPDecodeError` anchored at *pos* (default: cursor)."""
        return JPDecodeError(
            message,
            self.text,
            self.pos if pos is None else pos,
            filename=self.filename,
        )

    def describe_here(self) -> str:
        """Describe the current character for use in an error message."""
        char = self.peek()
        if char is None:
            return "end of file"
        if char in "\r\n":
            return "end of line"
        return repr(char)

    # -- trivia ----------------------------------------------------------

    def skip_inline(self) -> None:
        """Skip spaces, tabs and a ``#`` comment -- but never a line break."""
        text, end, i = self.text, self._len, self.pos
        while i < end:
            char = text[i]
            if char in INLINE_SPACE:
                i += 1
            elif char == "#":
                while i < end and text[i] not in "\r\n":
                    i += 1
            else:
                break
        self.pos = i

    def skip_ignorable(self) -> None:
        """Skip all whitespace (line breaks included) and comments."""
        text, end, i = self.text, self._len, self.pos
        while i < end:
            char = text[i]
            if char in INLINE_SPACE or char in "\r\n":
                i += 1
            elif char == "#":
                while i < end and text[i] not in "\r\n":
                    i += 1
            else:
                break
        self.pos = i

    # -- literals --------------------------------------------------------

    def scan_string(self) -> str:
        """Read a quoted string at the cursor and return its decoded value.

        Single and double quotes behave identically and both honour backslash
        escapes.  A backslash at end of line continues the string onto the next
        line, swallowing the following indentation.
        """
        start = self.pos
        quote = self.text[start]
        text, end = self.text, self._len
        i = start + 1
        chunks: list[str] = []
        literal_from = i

        while True:
            if i >= end:
                raise self.error("unterminated string literal", start)
            char = text[i]
            if char == quote:
                chunks.append(text[literal_from:i])
                self.pos = i + 1
                return "".join(chunks)
            if char in "\r\n":
                raise self.error(
                    "unterminated string literal (use \\n for a line break)", start
                )
            if char != "\\":
                i += 1
                continue

            chunks.append(text[literal_from:i])
            escape_at = i
            i += 1
            if i >= end:
                raise self.error("unterminated escape sequence", escape_at)
            marker = text[i]

            if marker in _ESCAPES:
                chunks.append(_ESCAPES[marker])
                i += 1
            elif marker in _HEX_WIDTH:
                decoded, i = self._scan_hex_escape(i, escape_at)
                chunks.append(decoded)
            elif marker in "\r\n":
                # Backslash-newline: continue the string, eating the indent.
                i += 1
                if marker == "\r" and i < end and text[i] == "\n":
                    i += 1
                while i < end and text[i] in INLINE_SPACE:
                    i += 1
            else:
                raise self.error(f"invalid escape sequence '\\{marker}'", escape_at)
            literal_from = i

    def _scan_hex_escape(self, marker_at: int, escape_at: int) -> tuple[str, int]:
        r"""Decode ``\xNN`` / ``\uNNNN`` / ``\UNNNNNNNN`` starting at *marker_at*."""
        text = self.text
        marker = text[marker_at]
        width = _HEX_WIDTH[marker]
        digits = text[marker_at + 1 : marker_at + 1 + width]
        if len(digits) < width or not all(d in _HEXDIGITS for d in digits):
            raise self.error(f"'\\{marker}' escape needs {width} hex digits", escape_at)
        code = int(digits, 16)
        i = marker_at + 1 + width

        # Recombine a UTF-16 surrogate pair, as JSON encoders emit them.
        if marker == "u" and 0xD800 <= code <= 0xDBFF and text[i : i + 2] == "\\u":
            low_digits = text[i + 2 : i + 6]
            if len(low_digits) == 4 and all(d in _HEXDIGITS for d in low_digits):
                low = int(low_digits, 16)
                if 0xDC00 <= low <= 0xDFFF:
                    code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)
                    i += 6

        if 0xD800 <= code <= 0xDFFF:
            raise self.error(f"'\\{marker}{digits}' is an unpaired surrogate", escape_at)
        if code > 0x10FFFF:
            raise self.error(
                f"'\\{marker}{digits}' is outside the Unicode range", escape_at
            )
        return chr(code), i

    def scan_until(self, terminators: frozenset[str]) -> str:
        """Consume characters up to (not including) any of *terminators*."""
        text, end, i = self.text, self._len, self.pos
        while i < end and text[i] not in terminators:
            i += 1
        raw = text[self.pos : i]
        self.pos = i
        return raw
