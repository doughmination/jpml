# jpml

[![CI](https://github.com/doughmination/jpml/actions/workflows/ci.yml/badge.svg)](https://github.com/doughmination/jpml/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/jpml)](https://pypi.org/project/jpml/)

**A configuration language that borrows TOML's sections and JSON's nesting.**

`.jp` files use `[SECTION]` headers at the top level and `{...}` / `[...]`
structures inside them. Keys need no quotes, `#` starts a comment, trailing
commas are fine, and a value is allowed to be *empty*.

```jp
[SERVER_ID]
config: {
  disabled_channels:,
  disabled_users: [9892, 82082, 8209]
}

[SERVER_ID_2]
prefix: "!"
modules: {
  moderation: true,
  fun: false
}
```

```python
>>> import jpml
>>> jpml.load("data/servers.jp")
{'SERVER_ID': {'config': {'disabled_channels': None,
                          'disabled_users': [9892, 82082, 8209]}},
 'SERVER_ID_2': {'prefix': '!', 'modules': {'moderation': True, 'fun': False}}}
```

---

## Why another format

JSON has no comments, demands quotes on every key, and rejects a trailing
comma. TOML has comments and headers, but nesting anything non-trivial means
either deeply dotted keys or a table per level.

`.jp` takes the half of each that suits configuration files people edit by hand:

* **Sections for the top level.** `[SERVER_ID]` reads better than another brace.
* **JSON for everything below it.** Nest objects and arrays as deep as you like.
* **No ceremony.** Unquoted keys, comments anywhere, trailing commas ignored.
* **Empty values are legal.** `disabled_channels:,` means the key exists and has
  no value yet — a real state in configs that JSON can only spell as `null`.

It is a small, fully specified format with a strict parser, precise error
messages, and a deterministic writer, so files stay stable when a program
rewrites them.

```bash
pip install jpml     # or: uv add jpml
```

No runtime dependencies. Python 3.14+.

---

## The format

### Sections

A `[NAME]` header opens a root key. Everything below it, until the next header,
belongs to that section.

```jp
[SERVER_ID]
prefix: "!"
```

Headers may be dotted to nest, and quoted when a name contains a dot:

```jp
[guild.limits]        # -> {"guild": {"limits": {...}}}
["weird.name"]        # -> {"weird.name": {...}}
```

Key/value pairs written *before* the first header land at the document root:

```jp
version: 2

[SERVER_ID]
prefix: "!"
```

### Entries

An entry is `key: value`. Keys need no quotes; a bare key may contain spaces but
not brackets, commas or quotes — quote it if it needs those.

Entries are separated by a line break, a comma, or both. Trailing and repeated
commas are accepted:

```jp
[SERVER_ID]
a: 1
b: {x: 1, y: 2,}
c: [1, 2, 3,]
```

### Empty values

A key with nothing after the colon parses to `None`:

```jp
config: {
  disabled_channels:,      # -> None
  timeout:                 # -> None
}
```

Because of this, **a value must start on the same line as its `:`**. An opening
`{` or `[` goes on the colon's line; its contents may then wrap freely.

### Values

| Type | Examples |
| --- | --- |
| String | `"hello"`, `'hello'`, `hello world` (unquoted) |
| Integer | `42`, `-7`, `1_000`, `0xff`, `0o755`, `0b1010` |
| Float | `3.5`, `1e3`, `inf`, `-inf`, `nan` |
| Boolean | `true`, `false` (case-insensitive, so `True` works too) |
| Null | `null`, `none`, `nil`, or nothing at all |
| Object | `{a: 1, b: 2}` |
| Array | `[1, 2, 3]` |

Unquoted values are read as a keyword first, then a number, then a plain string.
Quote a value if it contains a `#`, a comma, a bracket, or leading/trailing
whitespace you want to keep.

Strings honour the usual escapes — `\n`, `\t`, `\\`, `\"`, `\uXXXX`,
`\U0001F600`, plus `\` at end of line to continue onto the next.

### Comments

`#` runs to the end of the line and is allowed anywhere, including inside
objects and arrays.

---

## What you can do with it

### Read and write files

```python
import jpml

data = jpml.load("data/servers.jp")        # -> dict
jpml.dump(data, "data/servers.jp")         # formatted, atomic write

text = jpml.dumps(data)                    # -> str
data = jpml.loads(text)                    # -> dict
```

Writes are atomic by default: the file goes to a temporary neighbour and is
renamed into place, so a crash or a concurrent reader never sees half a config.

Options worth knowing:

```python
jpml.load("servers.jp", duplicate_keys="last")   # "error" (default), "first", "last"
jpml.dumps(data, indent=4, sort_keys=True)       # also: width, ensure_ascii
jpml.dumps(data, default=str)                    # convert datetimes and friends
```

### Edit a config in place

`JPConfig` is a `MutableMapping` that remembers the file it came from.

```python
from jpml import JPConfig

cfg = JPConfig.load("data/servers.jp", missing_ok=True)

cfg["SERVER_ID"]["prefix"]                              # plain dict access
cfg.get_path("SERVER_ID.config.disabled_users", [])     # never raises
cfg.set_path("SERVER_ID.config.disabled_users", [9892]) # creates missing sections
cfg.has_path("SERVER_ID.prefix")
cfg.section("NEW_SERVER", create=True)["prefix"] = "?"
cfg.merge({"SERVER_ID": {"modules": {"fun": True}}})    # deep merge
cfg.save()                                              # atomic, back to its own path
cfg.reload()                                            # discard in-memory changes
cfg.to_dict()                                           # deep copy as a plain dict
```

`missing_ok=True` gives an empty config bound to the path, which is what you
want for a program that writes its config on first run. Formatting options given
to the constructor are remembered by `save()`:

```python
cfg = JPConfig.load("data/servers.jp", indent=4, sort_keys=True)
```

### Load a whole folder

```python
config = jpml.load_dir("data")                 # {'servers': {...}, 'roles': {...}}
guilds = jpml.load_dir("data/guilds")          # {'1234567890': {...}, ...}
everything = jpml.load_dir("data", recursive=True)
```

Each file becomes one key, named after the file.

### Find mistakes quickly

Every error derives from `jpml.JPError`. `JPDecodeError` (a `ValueError`) points
at the exact character:

```
data/servers.jp:2:8: expected ':' after key 'prefix', found '"'
    prefix "!"
           ^
```

It carries `.line`, `.col`, `.pos`, `.filename` and `.raw_message` if you want to
render the failure yourself. `JPEncodeError` (a `TypeError`) explains what could
not be serialised — an unsupported type, a non-string key, a circular reference.

By default a repeated key is an error rather than a silent overwrite; pass
`duplicate_keys="first"` or `"last"` if you would rather it not be.

### Work from the shell

```bash
jpml check data/*.jp                      # validate; non-zero exit on failure
jpml fmt -w data/servers.jp               # reformat in place
jpml get data/servers.jp SERVER_ID.prefix # read one value
jpml to-json data/servers.jp -o out.json
jpml from-json out.json -o data/servers.jp
```

`python -m jpml ...` works identically, and `-` reads stdin.

---

## Round trips

`dumps` is deterministic, so a file rewritten twice is byte-identical:

* every top-level mapping becomes a `[SECTION]`, separated by a blank line;
* section entries sit one per line, with no separating commas;
* nested objects always expand across lines, `{}` being the only inline form;
* arrays stay inline while they fit inside `width` (default 88), then break one
  element per line;
* `None` is written as an empty value inside mappings (`key:`) and as `null`
  inside arrays, since an array element cannot be empty;
* insertion order is preserved unless `sort_keys=True`.

Two things do not survive a rewrite:

* **Comments are dropped.** Rewriting a hand-annotated file loses its notes.
* **Root-level scalars move above the first section**, because anything after a
  header would be read back as part of that section.

---

## Organising your configs

Nothing is enforced, but this layout is what `load_dir` is built for:

```
your-project/
├─ data/
│  ├─ servers.jp            # one file per concern
│  ├─ roles.jp
│  ├─ servers.example.jp    # committed template, safe to publish
│  └─ guilds/               # optional: one file per entity
│     ├─ 1234567890.jp
│     └─ 9876543210.jp
└─ src/
```

A few habits that save pain later:

1. **One file per concern.** A parse error then takes out one feature, not
   everything.
2. **Keep live data out of git**, and commit a template instead:
   ```gitignore
   data/*.jp
   !data/*.example.jp
   ```
3. **Use IDs as section names.** `[1234567890]` parses to the string key
   `"1234567890"`, and integer keys are stringified on write, so
   `{1234567890: {...}}` round-trips.
4. **Write through `JPConfig.save()`** rather than by hand, so an interrupted
   write cannot truncate a live config.
5. **Validate in CI** with `jpml check data/*.jp`.

---

## Licence

MIT. Contributing, tests and release process: [CONTRIBUTING.md](CONTRIBUTING.md).
