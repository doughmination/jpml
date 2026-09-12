"""Command line interface: ``jpml <command> [files]``.

Commands:
    check      Validate ``.jp`` files and report the first error in each.
    fmt        Reformat files to canonical style (``-w`` to rewrite in place).
    get        Print one dotted-path value as JSON.
    to-json    Convert ``.jp`` to JSON.
    from-json  Convert JSON to ``.jp``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from . import __version__, jp_config
from .errors import JPError

_MISSING = object()


def _read(path: str) -> dict:
    """Load a ``.jp`` file, or stdin when *path* is ``-``."""
    if path == "-":
        return jp_config.loads(sys.stdin.read(), filename="<stdin>")
    return jp_config.load(path)


def _write_options(args: argparse.Namespace) -> dict:
    return {
        "indent": args.indent,
        "width": args.width,
        "sort_keys": args.sort_keys,
    }


def _cmd_check(args: argparse.Namespace) -> int:
    failures = 0
    for path in args.files:
        try:
            _read(path)
        except (JPError, OSError) as exc:
            failures += 1
            print(exc, file=sys.stderr)
        else:
            if not args.quiet:
                print(f"ok  {path}")
    return 1 if failures else 0


def _cmd_fmt(args: argparse.Namespace) -> int:
    failures = 0
    for path in args.files:
        try:
            data = _read(path)
            text = jp_config.dumps(data, **_write_options(args))
        except (JPError, OSError) as exc:
            failures += 1
            print(exc, file=sys.stderr)
            continue
        if args.write and path != "-":
            target = Path(path)
            if target.read_text(encoding=jp_config.ENCODING) == text:
                continue
            jp_config.dump(data, target, **_write_options(args))
            print(f"reformatted {path}", file=sys.stderr)
        else:
            sys.stdout.write(text)
    return 1 if failures else 0


def _cmd_get(args: argparse.Namespace) -> int:
    try:
        config = jp_config.JPConfig(_read(args.file))
    except (JPError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    value = config.get_path(args.path, _MISSING)
    if value is _MISSING:
        print(f"no such path: {args.path}", file=sys.stderr)
        return 1
    if isinstance(value, str) and args.raw:
        print(value)
    else:
        print(json.dumps(value, indent=2, ensure_ascii=False))
    return 0


def _cmd_to_json(args: argparse.Namespace) -> int:
    try:
        data = _read(args.file)
    except (JPError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    text = json.dumps(data, indent=args.indent, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)
    return 0


def _cmd_from_json(args: argparse.Namespace) -> int:
    try:
        raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(
            encoding="utf-8"
        )
        data = json.loads(raw)
        text = jp_config.dumps(data, **_write_options(args))
    except (JPError, OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser for the ``jpml`` command."""
    parser = argparse.ArgumentParser(
        prog="jpml", description="Work with .jp configuration files."
    )
    parser.add_argument("--version", action="version", version=f"jpml {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)

    def add_format_flags(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--indent", type=int, default=2, help="spaces per level")
        sub.add_argument(
            "--width", type=int, default=88, help="column budget for inline arrays"
        )
        sub.add_argument(
            "--sort-keys", action="store_true", help="sort keys alphabetically"
        )

    check = subcommands.add_parser("check", help="validate .jp files")
    check.add_argument("files", nargs="+")
    check.add_argument("-q", "--quiet", action="store_true", help="only report errors")
    check.set_defaults(func=_cmd_check)

    fmt = subcommands.add_parser("fmt", help="reformat .jp files")
    fmt.add_argument("files", nargs="+")
    fmt.add_argument(
        "-w", "--write", action="store_true", help="rewrite files in place"
    )
    add_format_flags(fmt)
    fmt.set_defaults(func=_cmd_fmt)

    get = subcommands.add_parser("get", help="print one value by dotted path")
    get.add_argument("file")
    get.add_argument("path", help="e.g. SERVER_ID.config.disabled_users")
    get.add_argument(
        "-r", "--raw", action="store_true", help="print strings unquoted"
    )
    get.set_defaults(func=_cmd_get)

    to_json = subcommands.add_parser("to-json", help="convert .jp to JSON")
    to_json.add_argument("file")
    to_json.add_argument("-o", "--output")
    to_json.add_argument("--indent", type=int, default=2)
    to_json.set_defaults(func=_cmd_to_json)

    from_json = subcommands.add_parser("from-json", help="convert JSON to .jp")
    from_json.add_argument("file")
    from_json.add_argument("-o", "--output")
    add_format_flags(from_json)
    from_json.set_defaults(func=_cmd_from_json)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``jpml`` console script."""
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
