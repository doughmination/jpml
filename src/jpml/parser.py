"""Recursive-descent parser for the ``.jp`` format.

Grammar
-------

::

    document   := entry* section*
    section    := '[' key ('.' key)* ']' NEWLINE entry*
    entry      := key ':' value? separator
    value      := object | array | string | number | keyword | bare
    object     := '{' entry* '}'
    array      := '[' (value separator)* ']'
    separator  := ',' | NEWLINE | lookahead('}' | ']' | EOF)

Two rules keep the format unambiguous:

* ``[`` starts a **section header** only at the top level of the document.
  Anywhere a value is expected it starts an **array**.
* A value must begin on the same line as its ``:``.  That is what lets
  ``disabled_channels:,`` mean "this key exists and has no value" instead of
  swallowing the next line.
"""

from __future__ import annotations

from .errors import JPDecodeError
from .scanner import HEADER_END, KEY_END, VALUE_END, Scanner, interpret_bare

__all__ = ["Parser", "parse"]

#: How deep ``{`` / ``[`` nesting may go before we refuse, so that hostile or
#: corrupt input raises a clean error instead of blowing the Python stack.
MAX_DEPTH = 200

_DUPLICATE_POLICIES = ("error", "first", "last")


class Parser:
    """Parses one ``.jp`` document into plain Python containers.

    Args:
        text: Document source.
        filename: Name used in error messages.
        duplicate_keys: What to do when a key appears twice in the same
            mapping -- ``"error"`` (default), ``"first"`` (keep the original)
            or ``"last"`` (keep the later one).
        dict_factory: Callable producing the mapping type used for objects and
            sections; defaults to :class:`dict`.
    """

    def __init__(
        self,
        text: str,
        *,
        filename: str | None = None,
        duplicate_keys: str = "error",
        dict_factory: type | None = None,
    ) -> None:
        if duplicate_keys not in _DUPLICATE_POLICIES:
            raise ValueError(
                f"duplicate_keys must be one of {_DUPLICATE_POLICIES!r}, "
                f"got {duplicate_keys!r}"
            )
        self.scanner = Scanner(text, filename)
        self.duplicate_keys = duplicate_keys
        self.dict_factory = dict_factory or dict
        self._depth = 0
        # Section paths that have been opened by an explicit header, used to
        # detect '[a]' appearing twice.
        self._defined: set[tuple[str, ...]] = set()

    # -- entry point -----------------------------------------------------

    def parse(self) -> dict:
        """Parse the whole document and return its root mapping."""
        scanner = self.scanner
        root = self.dict_factory()
        current = root

        while True:
            scanner.skip_ignorable()
            if scanner.eof:
                return root
            if scanner.peek() == "[":
                current = self._parse_header(root)
                continue
            key, value, key_pos = self._parse_entry()
            self._store(current, key, value, key_pos)
            self._consume_separator(None)

    # -- sections --------------------------------------------------------

    def _parse_header(self, root: dict) -> dict:
        """Parse ``[a.b.c]`` and return the mapping its entries belong to."""
        scanner = self.scanner
        start = scanner.pos
        scanner.advance()  # '['

        path: list[str] = []
        pending_dot = False
        while True:
            scanner.skip_inline()
            char = scanner.peek()
            if char is None or char in "\r\n":
                raise scanner.error("unterminated section header", start)
            if char == "]":
                if not path:
                    raise scanner.error("section header cannot be empty", start)
                if pending_dot:
                    raise scanner.error("section header segment cannot be empty")
                scanner.advance()
                break
            if char in "\"'":
                path.append(scanner.scan_string())
            else:
                segment = scanner.scan_until(HEADER_END).strip()
                if not segment:
                    raise scanner.error(
                        "section header segment cannot be empty", scanner.pos
                    )
                path.append(segment)
            pending_dot = False

            scanner.skip_inline()
            char = scanner.peek()
            if char == ".":
                scanner.advance()
                pending_dot = True
                continue
            if char == "]":
                scanner.advance()
                break
            if char is None or char in "\r\n":
                raise scanner.error("unterminated section header", start)
            raise scanner.error(
                f"expected '.' or ']' in section header, found {scanner.describe_here()}"
            )

        scanner.skip_inline()
        char = scanner.peek()
        if char is not None and char not in "\r\n":
            raise scanner.error(
                f"unexpected {scanner.describe_here()} after section header"
            )

        return self._open_section(root, tuple(path), start)

    def _open_section(
        self, root: dict, path: tuple[str, ...], start: int
    ) -> dict:
        """Create or reuse the nested mapping addressed by *path*."""
        scanner = self.scanner
        if path in self._defined and self.duplicate_keys == "error":
            pretty = ".".join(path)
            raise scanner.error(f"section '[{pretty}]' is defined twice", start)
        self._defined.add(path)

        node = root
        for depth, part in enumerate(path):
            existing = node.get(part)
            if existing is None and part not in node:
                child = self.dict_factory()
                node[part] = child
                node = child
                continue
            if not isinstance(existing, dict):
                pretty = ".".join(path[: depth + 1])
                raise scanner.error(
                    f"cannot open section '[{'.'.join(path)}]': "
                    f"'{pretty}' is already a non-section value",
                    start,
                )
            node = existing
        return node

    # -- entries ---------------------------------------------------------

    def _parse_entry(self) -> tuple[str, object, int]:
        """Parse ``key: value`` and return ``(key, value, key_position)``."""
        scanner = self.scanner
        scanner.skip_inline()
        key_pos = scanner.pos
        key = self._parse_key()

        scanner.skip_inline()
        if scanner.peek() != ":":
            raise scanner.error(
                f"expected ':' after key {key!r}, found {scanner.describe_here()}"
            )
        scanner.advance()
        return key, self._parse_optional_value(), key_pos

    def _parse_key(self) -> str:
        """Read a quoted or bare key."""
        scanner = self.scanner
        char = scanner.peek()
        if char is None:
            raise scanner.error("expected a key, found end of file")
        if char in "\"'":
            return scanner.scan_string()
        if char in "}]":
            raise scanner.error(f"unexpected {scanner.describe_here()}")

        start = scanner.pos
        key = scanner.scan_until(KEY_END).strip()
        if not key:
            raise scanner.error(
                f"expected a key, found {scanner.describe_here()}", start
            )
        return key

    def _parse_optional_value(self) -> object:
        """Read the value after a ``:``, or ``None`` when the value is empty."""
        scanner = self.scanner
        scanner.skip_inline()
        char = scanner.peek()
        if char is None or char in ",\r\n":
            return None
        return self._parse_value()

    def _parse_value(self) -> object:
        """Read any value at the cursor."""
        scanner = self.scanner
        char = scanner.peek()
        if char == "{":
            return self._parse_object()
        if char == "[":
            return self._parse_array()
        if char in "\"'":
            return scanner.scan_string()
        return interpret_bare(scanner.scan_until(VALUE_END))

    # -- containers ------------------------------------------------------

    def _enter(self, start: int) -> None:
        self._depth += 1
        if self._depth > MAX_DEPTH:
            raise self.scanner.error(
                f"nesting deeper than {MAX_DEPTH} levels", start
            )

    def _parse_object(self) -> dict:
        """Parse ``{ key: value, ... }``."""
        scanner = self.scanner
        start = scanner.pos
        self._enter(start)
        scanner.advance()  # '{'
        obj = self.dict_factory()

        while True:
            scanner.skip_ignorable()
            char = scanner.peek()
            if char is None:
                raise scanner.error("unterminated object: missing '}'", start)
            if char == "}":
                scanner.advance()
                self._depth -= 1
                return obj
            if char == ",":
                # Tolerate stray or repeated separators.
                scanner.advance()
                continue
            key, value, key_pos = self._parse_entry()
            self._store(obj, key, value, key_pos)
            self._consume_separator("}")

    def _parse_array(self) -> list:
        """Parse ``[ value, ... ]``."""
        scanner = self.scanner
        start = scanner.pos
        self._enter(start)
        scanner.advance()  # '['
        items: list[object] = []

        while True:
            scanner.skip_ignorable()
            char = scanner.peek()
            if char is None:
                raise scanner.error("unterminated array: missing ']'", start)
            if char == "]":
                scanner.advance()
                self._depth -= 1
                return items
            if char == ",":
                scanner.advance()
                continue
            if char == "}":
                raise scanner.error("unterminated array: found '}' before ']'", start)
            items.append(self._parse_value())
            self._consume_separator("]")

    # -- separators and storage -----------------------------------------

    def _consume_separator(self, closing: str | None) -> None:
        """Require a ``,``, a line break, or the closing bracket after a value."""
        scanner = self.scanner
        scanner.skip_inline()
        char = scanner.peek()
        if char is None or char in "\r\n":
            return
        if char == ",":
            scanner.advance()
            return
        if closing is not None and char == closing:
            return
        if closing is None and char == "[":
            # A section header always starts its own line; reaching one here
            # means the previous entry never ended.
            raise scanner.error("expected a line break before a section header")
        expected = "',' or a line break"
        if closing is not None:
            expected = f"',', a line break or '{closing}'"
        raise scanner.error(
            f"expected {expected} after value, found {scanner.describe_here()}"
        )

    def _store(self, target: dict, key: str, value: object, key_pos: int) -> None:
        """Insert ``key`` into ``target``, applying the duplicate-key policy."""
        if key in target:
            if self.duplicate_keys == "error":
                raise self.scanner.error(f"duplicate key {key!r}", key_pos)
            if self.duplicate_keys == "first":
                return
        target[key] = value


def parse(
    text: str,
    *,
    filename: str | None = None,
    duplicate_keys: str = "error",
    dict_factory: type | None = None,
) -> dict:
    """Parse *text* as a ``.jp`` document.

    This is the low-level entry point; most callers want
    :func:`jpml.jp_config.loads`.

    Raises:
        JPDecodeError: If the document is malformed.
    """
    return Parser(
        text,
        filename=filename,
        duplicate_keys=duplicate_keys,
        dict_factory=dict_factory,
    ).parse()
