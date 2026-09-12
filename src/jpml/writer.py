"""Serialiser that turns Python objects back into ``.jp`` source.

The output style is fixed and deterministic, so a file stays stable under
repeated round-trips:

* Every top-level mapping becomes a ``[SECTION]``; sections are separated by a
  blank line.
* Section entries sit one per line with no separating commas.
* Nested objects always expand across lines with ``indent`` spaces per level
  and comma-separated entries; ``{}`` is the only inline form.
* Arrays stay on one line while they fit inside ``width``; otherwise they break
  one element per line.
* ``None`` is written as an empty value (``key:``) inside mappings, and as
  ``null`` inside arrays, since an array element cannot be empty.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence

from .errors import JPEncodeError

__all__ = ["dumps"]

#: Keys matching this are written without quotes.
_BARE_KEY = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_\-]*")

_STRING_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\b": "\\b",
    "\f": "\\f",
}


def _escape_char(char: str) -> str:
    """Return the escaped form of one character."""
    simple = _STRING_ESCAPES.get(char)
    if simple is not None:
        return simple
    code = ord(char)
    if code > 0xFFFF:
        # Encode astral characters as a UTF-16 surrogate pair.
        code -= 0x10000
        high = 0xD800 + (code >> 10)
        low = 0xDC00 + (code & 0x3FF)
        return f"\\u{high:04x}\\u{low:04x}"
    return f"\\u{code:04x}"


class _Writer:
    """Renders values using one fixed set of formatting options."""

    def __init__(
        self,
        *,
        indent: int,
        width: int,
        sort_keys: bool,
        ensure_ascii: bool,
        default: Callable[[object], object] | None,
    ) -> None:
        if indent < 0:
            raise ValueError("indent must be >= 0")
        self.indent = " " * indent
        self.width = width
        self.sort_keys = sort_keys
        self.ensure_ascii = ensure_ascii
        self.default = default
        # ids of the containers currently being rendered, to catch cycles.
        self._active: set[int] = set()

    # -- documents -------------------------------------------------------

    def document(self, mapping: Mapping) -> str:
        """Render a whole document."""
        preamble: list[str] = []
        blocks: list[str] = []

        for key, value in self._items(mapping):
            if isinstance(value, Mapping):
                body = [self.entry(k, v, 0) for k, v in self._items(value)]
                blocks.append("\n".join([f"[{self.format_key(key)}]", *body]))
            else:
                # Anything after a header would be read back as part of that
                # section, so scalar roots are hoisted above the first one.
                preamble.append(self.entry(key, value, 0))

        if preamble:
            blocks.insert(0, "\n".join(preamble))
        return "\n\n".join(blocks) + "\n" if blocks else ""

    # -- pieces ----------------------------------------------------------

    def entry(self, key: str, value: object, level: int) -> str:
        """Render one ``key: value`` line (possibly spanning several lines)."""
        prefix = f"{self.indent * level}{self.format_key(key)}:"
        if value is None:
            return prefix
        return f"{prefix} {self.render(value, level, len(prefix) + 1)}"

    def format_key(self, key: str) -> str:
        """Render a key, quoting it only when it is not a bare word."""
        return key if _BARE_KEY.fullmatch(key) else self.format_string(key)

    def format_string(self, value: str) -> str:
        """Render a string literal with the minimum necessary escaping."""
        out = ['"']
        for char in value:
            if char in _STRING_ESCAPES or char < " " or char == "\x7f":
                out.append(_escape_char(char))
            elif self.ensure_ascii and ord(char) > 0x7E:
                out.append(_escape_char(char))
            else:
                out.append(char)
        out.append('"')
        return "".join(out)

    def render(self, value: object, level: int, column: int) -> str:
        """Render any value; *column* is where it starts on the current line."""
        if value is None:
            return "null"
        if isinstance(value, bool):  # must precede int
            return "true" if value else "false"
        if isinstance(value, str):
            return self.format_string(value)
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return self.format_float(value)
        if isinstance(value, Mapping):
            return self.render_object(value, level)
        if isinstance(value, (bytes, bytearray)):
            raise JPEncodeError(
                "binary data has no .jp representation; decode or encode it "
                "to a string first"
            )
        if isinstance(value, Sequence):
            return self.render_array(value, level, column)
        return self.render_default(value, level, column)

    def format_float(self, value: float) -> str:
        """Render a float, including the non-finite literals."""
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return repr(value)

    def render_default(self, value: object, level: int, column: int) -> str:
        """Convert an unsupported type through the ``default`` hook."""
        if self.default is None:
            raise JPEncodeError(
                f"object of type {type(value).__name__!r} is not serialisable "
                f"to .jp; pass default= to convert it"
            )
        converted = self.default(value)
        if converted is value or isinstance(converted, type(value)):
            raise JPEncodeError(
                f"default() returned an unconverted {type(value).__name__!r}"
            )
        return self.render(converted, level, column)

    # -- containers ------------------------------------------------------

    def render_object(self, mapping: Mapping, level: int) -> str:
        """Render ``{...}``; always multi-line unless empty."""
        with self._guard(mapping):
            items = self._items(mapping)
            if not items:
                return "{}"
            body = ",\n".join(self.entry(k, v, level + 1) for k, v in items)
            return f"{{\n{body}\n{self.indent * level}}}"

    def render_array(self, values: Sequence, level: int, column: int) -> str:
        """Render ``[...]``, inline when it fits on the line."""
        with self._guard(values):
            parts = [self.render(v, level + 1, column) for v in values]
            if not parts:
                return "[]"
            inline = f"[{', '.join(parts)}]"
            if "\n" not in inline and column + len(inline) <= self.width:
                return inline
            pad = self.indent * (level + 1)
            body = ",\n".join(pad + part for part in parts)
            return f"[\n{body}\n{self.indent * level}]"

    # -- helpers ---------------------------------------------------------

    def _items(self, mapping: Mapping) -> list[tuple[str, object]]:
        """Return ``(key, value)`` pairs with keys normalised to strings."""
        items = [(self._coerce_key(k), v) for k, v in mapping.items()]
        if self.sort_keys:
            items.sort(key=lambda pair: pair[0])
        return items

    @staticmethod
    def _coerce_key(key: object) -> str:
        """Normalise a mapping key to ``str``.

        Integer keys are common (Discord snowflakes, for instance) and convert
        unambiguously, so they are accepted; anything else is rejected rather
        than silently stringified.
        """
        if isinstance(key, str):
            return key
        if isinstance(key, int) and not isinstance(key, bool):
            return str(key)
        raise JPEncodeError(
            f"keys must be strings (or ints), got {type(key).__name__!r}"
        )

    def _guard(self, container: object) -> "_CycleGuard":
        return _CycleGuard(self._active, container)


class _CycleGuard:
    """Context manager that rejects containers which contain themselves."""

    __slots__ = ("active", "key")

    def __init__(self, active: set[int], container: object) -> None:
        self.active = active
        self.key = id(container)
        if self.key in active:
            raise JPEncodeError("circular reference detected")

    def __enter__(self) -> "_CycleGuard":
        self.active.add(self.key)
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.active.discard(self.key)


def dumps(
    obj: Mapping,
    *,
    indent: int = 2,
    width: int = 88,
    sort_keys: bool = False,
    ensure_ascii: bool = False,
    default: Callable[[object], object] | None = None,
) -> str:
    """Serialise *obj* to ``.jp`` source text.

    Args:
        obj: The mapping to serialise.  Every top-level mapping value becomes a
            ``[SECTION]``.
        indent: Spaces per nesting level.
        width: Column budget used to decide whether an array stays inline.
        sort_keys: Sort keys alphabetically instead of keeping insertion order.
        ensure_ascii: Escape non-ASCII characters instead of writing them
            literally.
        default: Called for objects of otherwise unsupported types; it must
            return something serialisable (e.g. ``str`` for a ``datetime``).

    Returns:
        The document text, ending with a newline (empty input gives ``""``).

    Raises:
        JPEncodeError: If *obj* or one of its members cannot be represented.
    """
    if not isinstance(obj, Mapping):
        raise JPEncodeError(
            f"the top level of a .jp document must be a mapping, got "
            f"{type(obj).__name__!r}"
        )
    writer = _Writer(
        indent=indent,
        width=width,
        sort_keys=sort_keys,
        ensure_ascii=ensure_ascii,
        default=default,
    )
    return writer.document(obj)
