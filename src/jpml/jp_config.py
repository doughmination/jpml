"""Public API for reading and writing ``.jp`` configuration files.

The module mirrors :mod:`json` -- :func:`loads`, :func:`load`, :func:`dumps`,
:func:`dump` -- and adds :class:`JPConfig`, a dict-like wrapper that remembers
the file it came from::

    from jpml import JPConfig

    cfg = JPConfig.load("data/servers.jp")
    cfg.set_path("SERVER_ID.config.disabled_users", [9892])
    cfg.save()
"""

from __future__ import annotations

import copy
import os
import tempfile
from collections.abc import Callable, Iterator, Mapping, MutableMapping
from pathlib import Path
from typing import IO, Any

from . import writer
from .errors import JPDecodeError, JPEncodeError, JPError
from .parser import parse

__all__ = [
    "load",
    "loads",
    "dump",
    "dumps",
    "load_dir",
    "JPConfig",
    "JPError",
    "JPDecodeError",
    "JPEncodeError",
    "SUFFIX",
    "ENCODING",
]

#: Conventional file extension.
SUFFIX = ".jp"

#: ``.jp`` files are always UTF-8.
ENCODING = "utf-8"

#: Keyword arguments understood by :func:`dumps`.
_WRITE_OPTIONS = ("indent", "width", "sort_keys", "ensure_ascii", "default")

#: Keyword arguments understood by :func:`loads`.
_READ_OPTIONS = ("duplicate_keys", "dict_factory")

# ---------------------------------------------------------------------------
# functional API
# ---------------------------------------------------------------------------


def loads(
    text: str,
    *,
    filename: str | None = None,
    duplicate_keys: str = "error",
    dict_factory: type | None = None,
) -> dict:
    """Parse ``.jp`` *text* into a plain :class:`dict`.

    Args:
        text: The document source.
        filename: Name to show in error messages.
        duplicate_keys: ``"error"``, ``"first"`` or ``"last"``.
        dict_factory: Mapping type to build (e.g. ``collections.OrderedDict``).

    Raises:
        JPDecodeError: If the document is malformed.
    """
    return parse(
        text,
        filename=filename,
        duplicate_keys=duplicate_keys,
        dict_factory=dict_factory,
    )


def load(
    source: str | os.PathLike[str] | IO[str],
    *,
    duplicate_keys: str = "error",
    dict_factory: type | None = None,
) -> dict:
    """Read a ``.jp`` document from a path or an open text file.

    Args:
        source: Filesystem path, or any object with a ``read()`` method.
        duplicate_keys: ``"error"``, ``"first"`` or ``"last"``.
        dict_factory: Mapping type to build.

    Raises:
        JPDecodeError: If the document is malformed.
        OSError: If the file cannot be read.
    """
    if hasattr(source, "read"):
        text = source.read()
        filename = getattr(source, "name", None)
    else:
        path = Path(source)
        text = path.read_text(encoding=ENCODING)
        filename = str(path)
    return loads(
        text,
        filename=filename,
        duplicate_keys=duplicate_keys,
        dict_factory=dict_factory,
    )


def dumps(obj: Mapping, **options: Any) -> str:
    """Serialise *obj* to ``.jp`` text.

    See :func:`jpml.writer.dumps` for the full list of options.
    """
    return writer.dumps(obj, **options)


def dump(
    obj: Mapping,
    target: str | os.PathLike[str] | IO[str],
    *,
    atomic: bool = True,
    **options: Any,
) -> None:
    """Write *obj* to a path or an open text file.

    Args:
        obj: Mapping to serialise.
        target: Filesystem path, or any object with a ``write()`` method.
        atomic: When *target* is a path, write to a temporary file in the same
            directory and rename it into place, so a crash or a concurrent
            reader never sees a half-written config.  Ignored for file objects.
        **options: Forwarded to :func:`dumps`.

    Raises:
        JPEncodeError: If *obj* cannot be represented.
        OSError: If the file cannot be written.
    """
    text = dumps(obj, **options)
    if hasattr(target, "write"):
        target.write(text)
        return
    path = Path(target)
    if atomic:
        _atomic_write(path, text)
    else:
        path.write_text(text, encoding=ENCODING, newline="\n")


def load_dir(
    directory: str | os.PathLike[str],
    *,
    pattern: str = f"*{SUFFIX}",
    recursive: bool = False,
    **options: Any,
) -> dict[str, dict]:
    """Load every ``.jp`` file in *directory*, keyed by file stem.

    ``data/servers.jp`` and ``data/roles.jp`` become ``{"servers": {...},
    "roles": {...}}``.  With ``recursive=True`` nested files are keyed by their
    relative path without the suffix, using ``/`` separators.

    Args:
        directory: Folder to scan.
        pattern: Glob applied to file names.
        recursive: Whether to descend into sub-folders.
        **options: Forwarded to :func:`load`.

    Raises:
        NotADirectoryError: If *directory* does not exist or is not a folder.
        JPDecodeError: If any document is malformed.
    """
    root = Path(directory)
    if not root.is_dir():
        raise NotADirectoryError(f"no such config directory: {root}")
    paths = sorted(root.rglob(pattern) if recursive else root.glob(pattern))
    result: dict[str, dict] = {}
    for path in paths:
        if not path.is_file():
            continue
        relative = path.relative_to(root).with_suffix("")
        result[relative.as_posix()] = load(path, **options)
    return result


def _atomic_write(path: Path, text: str) -> None:
    """Write *text* to *path* via a same-directory temp file and ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding=ENCODING, newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# object API
# ---------------------------------------------------------------------------


class JPConfig(MutableMapping):
    """A mutable ``.jp`` document that remembers where it came from.

    Behaves like a ``dict`` of sections, and adds dotted-path access plus
    atomic saving::

        cfg = JPConfig.load("data/servers.jp", missing_ok=True)
        cfg.get_path("SERVER_ID.config.disabled_users", [])
        cfg.set_path("SERVER_ID.prefix", "!")
        cfg.save()

    Args:
        data: Initial mapping; copied, not aliased.
        path: File this config is bound to, used by :meth:`save` and
            :meth:`reload`.
        **options: Any :func:`loads` or :func:`dumps` option, remembered and
            reused by :meth:`reload` and :meth:`save`.
    """

    __slots__ = ("_data", "path", "_read_options", "_write_options")

    def __init__(
        self,
        data: Mapping | None = None,
        *,
        path: str | os.PathLike[str] | None = None,
        **options: Any,
    ) -> None:
        unknown = set(options) - set(_READ_OPTIONS) - set(_WRITE_OPTIONS)
        if unknown:
            raise TypeError(f"unknown option(s): {', '.join(sorted(unknown))}")
        self._data: dict = dict(data) if data is not None else {}
        self.path = Path(path) if path is not None else None
        self._read_options = {k: v for k, v in options.items() if k in _READ_OPTIONS}
        self._write_options = {k: v for k, v in options.items() if k in _WRITE_OPTIONS}

    # -- constructors ----------------------------------------------------

    @classmethod
    def load(
        cls,
        path: str | os.PathLike[str],
        *,
        missing_ok: bool = False,
        **options: Any,
    ) -> "JPConfig":
        """Read *path* into a new config.

        Args:
            path: File to read.
            missing_ok: Return an empty config bound to *path* instead of
                raising when the file does not exist yet.
            **options: Read and write options to remember.
        """
        target = Path(path)
        read_options = {k: v for k, v in options.items() if k in _READ_OPTIONS}
        if missing_ok and not target.exists():
            return cls(None, path=target, **options)
        return cls(load(target, **read_options), path=target, **options)

    @classmethod
    def loads(
        cls,
        text: str,
        *,
        path: str | os.PathLike[str] | None = None,
        **options: Any,
    ) -> "JPConfig":
        """Parse *text* into a new config."""
        read_options = {k: v for k, v in options.items() if k in _READ_OPTIONS}
        filename = str(path) if path is not None else None
        return cls(
            loads(text, filename=filename, **read_options), path=path, **options
        )

    # -- mapping protocol ------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def __delitem__(self, key: str) -> None:
        del self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        where = f" path={str(self.path)!r}" if self.path else ""
        return f"<JPConfig{where} sections={list(self._data)!r}>"

    # -- dotted paths ----------------------------------------------------

    def get_path(self, path: str, default: Any = None, *, sep: str = ".") -> Any:
        """Return the value at a dotted *path*, or *default* if absent.

        ``cfg.get_path("SERVER_ID.config.disabled_users", [])`` never raises on
        a missing section, so it is the safe way to read optional settings.
        """
        node: Any = self._data
        for part in path.split(sep):
            if not isinstance(node, Mapping) or part not in node:
                return default
            node = node[part]
        return node

    def set_path(self, path: str, value: Any, *, sep: str = ".") -> None:
        """Set the value at a dotted *path*, creating missing sections.

        Raises:
            TypeError: If an existing non-mapping value blocks the path.
        """
        parts = path.split(sep)
        node: Any = self._data
        for depth, part in enumerate(parts[:-1]):
            child = node.get(part)
            if child is None:
                # Missing, or present but empty ('key:'); either way a section
                # can be grown here.
                child = {}
                node[part] = child
            elif not isinstance(child, MutableMapping):
                blocked = sep.join(parts[: depth + 1])
                raise TypeError(
                    f"cannot descend into {blocked!r}: it holds "
                    f"{type(child).__name__}, not a section"
                )
            node = child
        node[parts[-1]] = value

    def has_path(self, path: str, *, sep: str = ".") -> bool:
        """Whether a dotted *path* exists (even if its value is ``None``)."""
        sentinel = object()
        return self.get_path(path, sentinel, sep=sep) is not sentinel

    def section(self, name: str, *, create: bool = False) -> dict:
        """Return the mapping stored under *name*.

        Args:
            name: Top-level section name.
            create: Create an empty section instead of raising when missing.

        Raises:
            KeyError: If the section is missing and *create* is false.
            TypeError: If *name* holds something other than a mapping.
        """
        if name not in self._data:
            if not create:
                raise KeyError(name)
            self._data[name] = {}
        value = self._data[name]
        if not isinstance(value, MutableMapping):
            raise TypeError(
                f"section {name!r} holds {type(value).__name__}, not a mapping"
            )
        return value

    # -- whole-document operations ---------------------------------------

    def merge(self, other: Mapping, *, deep: bool = True) -> "JPConfig":
        """Merge *other* into this config in place and return ``self``.

        With ``deep=True`` nested mappings are merged recursively; otherwise
        top-level keys are replaced outright.
        """
        _merge(self._data, other, deep=deep)
        return self

    def to_dict(self, *, deep: bool = True) -> dict:
        """Return the underlying data as a plain ``dict``.

        A deep copy by default, so callers cannot mutate the config by
        accident.
        """
        return copy.deepcopy(self._data) if deep else dict(self._data)

    def dumps(self, **options: Any) -> str:
        """Serialise this config to ``.jp`` text."""
        return writer.dumps(self._data, **{**self._write_options, **options})

    def save(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        atomic: bool = True,
        **options: Any,
    ) -> Path:
        """Write the config back to disk and return the path written.

        Args:
            path: Destination; defaults to the path the config was loaded from.
            atomic: Write via a temp file and rename (see :func:`dump`).
            **options: Override remembered write options for this call.

        Raises:
            ValueError: If no path was given and none is remembered.
        """
        target = Path(path) if path is not None else self.path
        if target is None:
            raise ValueError(
                "this config has no path; call save(path) or set .path first"
            )
        dump(
            self._data, target, atomic=atomic, **{**self._write_options, **options}
        )
        self.path = target
        return target

    def reload(self) -> "JPConfig":
        """Re-read the bound file, discarding in-memory changes."""
        if self.path is None:
            raise ValueError("this config has no path to reload from")
        self._data = load(self.path, **self._read_options)
        return self


def _merge(target: dict, source: Mapping, *, deep: bool) -> None:
    """Recursively merge *source* into *target*."""
    for key, value in source.items():
        current = target.get(key)
        if (
            deep
            and isinstance(current, MutableMapping)
            and isinstance(value, Mapping)
        ):
            _merge(current, value, deep=True)
        else:
            target[key] = value
