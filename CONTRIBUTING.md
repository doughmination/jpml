# Contributing

## Getting set up

```bash
uv sync
uv run pytest -q
```

Requires Python 3.14+. `uv sync` installs the project and the `dev` dependency
group; `uv run jpml ...` runs the CLI from the working tree.

## Project layout

```
src/jpml/
├─ __init__.py     public exports
├─ errors.py       JPError, JPDecodeError (with line/column), JPEncodeError
├─ scanner.py      cursor, whitespace, comments, strings, bare tokens
├─ parser.py       recursive-descent grammar
├─ writer.py       deterministic serialiser
├─ jp_config.py    load/loads/dump/dumps/load_dir + JPConfig
├─ cli.py          the jpml command
└─ __main__.py     python -m jpml
tests/
└─ test_jp_config.py
```

`jp_config` is the public module; `import jpml` re-exports all of it, so
`jpml.load(...)` and `from jpml.jp_config import JPConfig` are equivalent.

The split is deliberate: `scanner.py` owns every *lexical* concern and knows
nothing about the grammar, while `parser.py` owns the grammar and drives the
scanner directly. There is no standalone token stream, because the format is
context sensitive — `[` opens a section header at the top level but an array
everywhere a value is expected.

## Tests

```bash
uv run pytest -q
```

CI (`.github/workflows/ci.yml`) runs the suite on Linux, Windows and macOS for
every push and pull request, and validates the bundled `.jp` files.

`jpml fmt` is deliberately *not* enforced in CI: rewriting a file drops its
comments, so formatting stays a manual choice.

## Releasing

Publishing runs from `.github/workflows/publish.yml` using PyPI **Trusted
Publishing** (OIDC), so there are no API tokens or repository secrets to manage.

### One-time setup

1. Create a GitHub environment named `pypi` under
   **Settings → Environments**. Adding a required reviewer to it gives a manual
   approval gate before anything is published.
2. Add a *pending publisher* at <https://pypi.org/manage/account/publishing/>:

   | Field | Value |
   | --- | --- |
   | PyPI project name | `jpml` |
   | Owner | `doughmination` |
   | Repository name | `jpml` |
   | Workflow name | `publish.yml` |
   | Environment name | `pypi` |

### Cutting a release

```bash
# 1. bump [project] version in pyproject.toml -- the only place it lives;
#    jpml.__version__ is read from the installed distribution metadata.
git commit -am "Release 1.0.1"
git tag v1.0.1
git push --follow-tags
```

Then publish a GitHub Release for that tag. The workflow installs the project,
runs the tests, checks that the tag matches the version in `pyproject.toml`,
builds an sdist and a wheel, verifies the metadata with `twine check --strict`,
and uploads to PyPI with [PEP 740 attestations][attestations].

The tag must match the version exactly — `version = "1.1.1"` needs the tag
`v1.1.1`, or the build fails before anything is uploaded.

If an upload fails after the artifacts were built, re-run the workflow from
**Actions → Publish → Run workflow**. Note that PyPI refuses to overwrite a
version that already exists, so a partially published release needs a version
bump rather than a retry.

[attestations]: https://peps.python.org/pep-0740/
