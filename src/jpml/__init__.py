"""jpml -- a hybrid JSON/TOML configuration language.

``.jp`` files use TOML-style ``[SECTION]`` headers at the top level and
JSON-style ``{...}`` / ``[...]`` structures inside them, with unquoted keys and
``#`` comments::

    [SERVER_ID]
    config: {
      disabled_channels:,
      disabled_users: [9892, 82082, 8209]
    }

Typical use::

    import jpml

    data = jpml.load("data/servers.jp")          # -> dict
    jpml.dump(data, "data/servers.jp")           # formatted, atomic write

    cfg = jpml.JPConfig.load("data/servers.jp")  # dict-like, dotted paths
    cfg.set_path("SERVER_ID.prefix", "!")
    cfg.save()
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version

from .errors import JPDecodeError, JPEncodeError, JPError
from .jp_config import (
    ENCODING,
    SUFFIX,
    JPConfig,
    dump,
    dumps,
    load,
    load_dir,
    loads,
)

try:
    #: Taken from the installed distribution metadata, so ``pyproject.toml`` is
    #: the only place a release version has to be bumped.
    __version__ = _installed_version("jpml")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0+unknown"

__all__ = [
    "JPConfig",
    "JPDecodeError",
    "JPEncodeError",
    "JPError",
    "ENCODING",
    "SUFFIX",
    "dump",
    "dumps",
    "load",
    "load_dir",
    "loads",
    "__version__",
]
