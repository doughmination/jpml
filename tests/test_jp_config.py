"""Tests for the .jp parser, writer and config object."""

from __future__ import annotations

import json
import math

import pytest

import jpml
import jpml.cli
from jpml import JPConfig, JPDecodeError, JPEncodeError

SAMPLE = """\
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
"""

SAMPLE_DATA = {
    "SERVER_ID": {
        "config": {
            "disabled_channels": None,
            "disabled_users": [9892, 82082, 8209],
        }
    },
    "SERVER_ID_2": {
        "prefix": "!",
        "modules": {"moderation": True, "fun": False},
    },
}


# -- reading ---------------------------------------------------------------


def test_parses_the_reference_document():
    assert jpml.loads(SAMPLE) == SAMPLE_DATA


def test_empty_value_becomes_none():
    assert jpml.loads("[s]\na:,\nb:\nc: 1\n")["s"] == {"a": None, "b": None, "c": 1}


def test_comments_and_blank_lines_are_ignored():
    text = """
    # leading comment

    [s]   # after a header
      a: 1  # after a value
      # between entries
      b: {
        # inside an object
        c: [1, 2]  # inside, after a value
      }
    """
    assert jpml.loads(text) == {"s": {"a": 1, "b": {"c": [1, 2]}}}


def test_trailing_commas_are_allowed():
    text = "[s]\no: {a: 1, b: 2,}\nl: [1, 2, 3,]\n"
    assert jpml.loads(text)["s"] == {"o": {"a": 1, "b": 2}, "l": [1, 2, 3]}


def test_repeated_and_leading_commas_are_tolerated():
    assert jpml.loads("[s]\no: {,a: 1,, b: 2,}\nl: [,1,,2,]\n")["s"] == {
        "o": {"a": 1, "b": 2},
        "l": [1, 2],
    }


def test_entries_may_be_separated_by_newlines_commas_or_both():
    text = "[s]\no: {\n  a: 1\n  b: 2,\n  c: 3,\n}\nl: [\n  1\n  2,\n]\n"
    assert jpml.loads(text)["s"] == {"o": {"a": 1, "b": 2, "c": 3}, "l": [1, 2]}


def test_multiple_keys_per_section_keep_order():
    data = jpml.loads("[s]\nz: 1\na: 2\nm: 3\n")
    assert list(data["s"]) == ["z", "a", "m"]


def test_scalar_types():
    text = (
        "[s]\n"
        "i: 42\n"
        "neg: -7\n"
        "f: 3.5\n"
        "exp: 1e3\n"
        "under: 1_000\n"
        "hex: 0xff\n"
        "t: true\n"
        "f2: False\n"
        "n: null\n"
        "s: \"quoted\"\n"
        "s2: 'single'\n"
        "bare: hello world\n"
    )
    section = jpml.loads(text)["s"]
    assert section == {
        "i": 42,
        "neg": -7,
        "f": 3.5,
        "exp": 1000.0,
        "under": 1000,
        "hex": 255,
        "t": True,
        "f2": False,
        "n": None,
        "s": "quoted",
        "s2": "single",
        "bare": "hello world",
    }


def test_non_finite_floats_round_trip():
    section = jpml.loads("[s]\na: inf\nb: -inf\nc: nan\n")["s"]
    assert section["a"] == math.inf
    assert section["b"] == -math.inf
    assert math.isnan(section["c"])


def test_string_escapes():
    text = r'[s]' "\n" r'a: "tab\there\nline \u00e9 \U0001F600 \"q\" \\"' "\n"
    assert jpml.loads(text)["s"]["a"] == 'tab\there\nline é 😀 "q" \\'


def test_surrogate_pair_escape():
    assert jpml.loads(r'[s]' "\n" r'a: "\ud83d\ude00"' "\n")["s"]["a"] == "😀"


def test_backslash_newline_continues_a_string():
    assert jpml.loads('[s]\na: "one \\\n     two"\n')["s"]["a"] == "one two"


def test_quoted_keys_allow_any_character():
    assert jpml.loads('[s]\n"a b: c": 1\n')["s"] == {"a b: c": 1}


def test_keys_before_any_header_land_at_the_root():
    data = jpml.loads('version: 2\n\n[s]\na: 1\n')
    assert data == {"version": 2, "s": {"a": 1}}


def test_dotted_headers_nest():
    data = jpml.loads("[a.b.c]\nx: 1\n\n[a.d]\ny: 2\n")
    assert data == {"a": {"b": {"c": {"x": 1}}, "d": {"y": 2}}}


def test_quoted_header_segment_is_not_split():
    assert jpml.loads('["a.b"]\nx: 1\n') == {"a.b": {"x": 1}}


def test_deeply_nested_containers():
    data = jpml.loads("[s]\na: {b: [{c: [1, {d: 2}]}]}\n")
    assert data["s"]["a"]["b"][0]["c"][1]["d"] == 2


def test_empty_containers():
    assert jpml.loads("[s]\na: {}\nb: []\n")["s"] == {"a": {}, "b": []}


def test_empty_document():
    assert jpml.loads("") == {}
    assert jpml.loads("# just a comment\n\n") == {}


def test_empty_section():
    assert jpml.loads("[a]\n\n[b]\nx: 1\n") == {"a": {}, "b": {"x": 1}}


def test_crlf_and_bom_are_handled():
    assert jpml.loads("\ufeff[s]\r\na: 1\r\n") == {"s": {"a": 1}}


# -- duplicate keys --------------------------------------------------------


def test_duplicate_key_raises_by_default():
    with pytest.raises(JPDecodeError, match="duplicate key 'a'"):
        jpml.loads("[s]\na: 1\na: 2\n")


def test_duplicate_key_policies():
    text = "[s]\na: 1\na: 2\n"
    assert jpml.loads(text, duplicate_keys="first")["s"]["a"] == 1
    assert jpml.loads(text, duplicate_keys="last")["s"]["a"] == 2


def test_duplicate_section_raises():
    with pytest.raises(JPDecodeError, match=r"section '\[s\]' is defined twice"):
        jpml.loads("[s]\na: 1\n\n[s]\nb: 2\n")


def test_duplicate_section_merges_under_last_policy():
    data = jpml.loads("[s]\na: 1\n\n[s]\nb: 2\n", duplicate_keys="last")
    assert data == {"s": {"a": 1, "b": 2}}


def test_invalid_duplicate_policy_rejected():
    with pytest.raises(ValueError, match="duplicate_keys"):
        jpml.loads("", duplicate_keys="nope")


# -- errors ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text, message",
    [
        ("[s]\na 1\n", "expected ':' after key"),
        ("[s]\na: {b: 1\n", "unterminated object"),
        ("[s]\na: [1, 2\n", "unterminated array"),
        ("[s\na: 1\n", "unterminated section header"),
        ("[]\na: 1\n", "section header cannot be empty"),
        ('[s]\na: "open\n', "unterminated string"),
        (r'[s]' "\n" r'a: "\q"' "\n", "invalid escape sequence"),
        (r'[s]' "\n" r'a: "\u12"' "\n", "escape needs 4 hex digits"),
        ('[s]\na: "x" "y"\n', "expected ',' or a line break"),
        ('[s]\na: {b: "1" extra}\n', "expected ',', a line break or '}'"),
        ("[s]\n: 1\n", "expected a key"),
        ("[s] junk\na: 1\n", "unexpected 'j' after section header"),
        ("version: 1\n[s.]\na: 1\n", "section header segment cannot be empty"),
    ],
)
def test_syntax_errors(text, message):
    with pytest.raises(JPDecodeError, match=message):
        jpml.loads(text)


def test_error_reports_line_column_and_source():
    with pytest.raises(JPDecodeError) as info:
        jpml.loads("[s]\nprefix \"!\"\n", filename="servers.jp")
    error = info.value
    assert (error.line, error.col) == (2, 8)
    assert error.filename == "servers.jp"
    assert 'prefix "!"' in str(error)
    assert "^" in str(error)


def test_section_cannot_shadow_a_scalar():
    with pytest.raises(JPDecodeError, match="already a non-section value"):
        jpml.loads("a: 1\n\n[a.b]\nx: 1\n")


def test_nesting_depth_is_capped():
    with pytest.raises(JPDecodeError, match="nesting deeper than"):
        jpml.loads("[s]\na: " + "[" * 500 + "]" * 500 + "\n")


# -- writing ---------------------------------------------------------------


def test_dumps_matches_the_reference_style():
    assert jpml.dumps(SAMPLE_DATA) == SAMPLE


def test_round_trip_is_stable():
    once = jpml.dumps(jpml.loads(SAMPLE))
    assert jpml.dumps(jpml.loads(once)) == once


def test_none_is_empty_in_mappings_and_null_in_arrays():
    text = jpml.dumps({"s": {"a": None, "b": [None, 1]}})
    assert "a:\n" in text
    assert "b: [null, 1]" in text
    assert jpml.loads(text) == {"s": {"a": None, "b": [None, 1]}}


def test_long_arrays_break_onto_multiple_lines():
    text = jpml.dumps({"s": {"ids": list(range(30))}})
    assert "ids: [\n" in text
    assert jpml.loads(text)["s"]["ids"] == list(range(30))


def test_scalar_roots_are_hoisted_above_sections():
    text = jpml.dumps({"s": {"a": 1}, "version": 2})
    assert text.index("version: 2") < text.index("[s]")
    assert jpml.loads(text) == {"version": 2, "s": {"a": 1}}


def test_keys_are_quoted_only_when_necessary():
    text = jpml.dumps({"ok_key-1": {"plain": 1, "needs quotes": 2, "": 3}})
    assert "[ok_key-1]" in text
    assert '"needs quotes": 2' in text
    assert '"": 3' in text
    assert jpml.loads(text) == {"ok_key-1": {"plain": 1, "needs quotes": 2, "": 3}}


def test_integer_keys_are_stringified():
    assert jpml.loads(jpml.dumps({123: {"a": 1}})) == {"123": {"a": 1}}


def test_string_values_are_escaped():
    value = 'quote " backslash \\ newline \n tab \t bell \x07'
    text = jpml.dumps({"s": {"a": value}})
    assert jpml.loads(text)["s"]["a"] == value


def test_ensure_ascii_option():
    assert "\\u00e9" in jpml.dumps({"s": {"a": "é"}}, ensure_ascii=True)
    assert "é" in jpml.dumps({"s": {"a": "é"}})


def test_indent_width_and_sort_keys_options():
    text = jpml.dumps({"s": {"b": 1, "a": {"z": 1}}}, indent=4, sort_keys=True)
    assert text.index("a: {") < text.index("b: 1")
    assert "\n    z: 1" in text


def test_tuples_are_written_as_arrays():
    assert jpml.loads(jpml.dumps({"s": {"a": (1, 2)}}))["s"]["a"] == [1, 2]


def test_unserialisable_type_raises():
    with pytest.raises(JPEncodeError, match="not serialisable"):
        jpml.dumps({"s": {"a": object()}})


def test_default_hook_converts_unknown_types():
    import datetime

    stamp = datetime.date(2026, 9, 12)
    text = jpml.dumps({"s": {"when": stamp}}, default=str)
    assert jpml.loads(text)["s"]["when"] == "2026-09-12"


def test_bytes_are_rejected_with_a_hint():
    with pytest.raises(JPEncodeError, match="binary data"):
        jpml.dumps({"s": {"a": b"x"}})


def test_circular_reference_is_detected():
    section: dict = {}
    section["self"] = section
    with pytest.raises(JPEncodeError, match="circular reference"):
        jpml.dumps({"s": section})


def test_top_level_must_be_a_mapping():
    with pytest.raises(JPEncodeError, match="must be a mapping"):
        jpml.dumps([1, 2])


def test_dumps_of_empty_document():
    assert jpml.dumps({}) == ""


# -- files -----------------------------------------------------------------


def test_load_and_dump_paths(tmp_path):
    path = tmp_path / "servers.jp"
    path.write_text(SAMPLE, encoding="utf-8")
    data = jpml.load(path)
    assert data == SAMPLE_DATA
    out = tmp_path / "copy.jp"
    jpml.dump(data, out)
    assert out.read_text(encoding="utf-8") == SAMPLE


def test_dump_is_atomic_and_leaves_no_temp_files(tmp_path):
    path = tmp_path / "a.jp"
    jpml.dump({"s": {"a": 1}}, path)
    assert [p.name for p in tmp_path.iterdir()] == ["a.jp"]


def test_dump_creates_missing_parent_directories(tmp_path):
    path = tmp_path / "nested" / "deep" / "a.jp"
    jpml.dump({"s": {"a": 1}}, path)
    assert jpml.load(path) == {"s": {"a": 1}}


def test_load_and_dump_file_objects(tmp_path):
    path = tmp_path / "a.jp"
    with path.open("w", encoding="utf-8") as handle:
        jpml.dump({"s": {"a": 1}}, handle)
    with path.open(encoding="utf-8") as handle:
        assert jpml.load(handle) == {"s": {"a": 1}}


def test_error_from_a_file_names_the_file(tmp_path):
    path = tmp_path / "broken.jp"
    path.write_text("[s]\na 1\n", encoding="utf-8")
    with pytest.raises(JPDecodeError) as info:
        jpml.load(path)
    assert "broken.jp" in str(info.value)


def test_load_dir(tmp_path):
    (tmp_path / "servers.jp").write_text(SAMPLE, encoding="utf-8")
    (tmp_path / "roles.jp").write_text("[r]\na: 1\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("nope", encoding="utf-8")
    loaded = jpml.load_dir(tmp_path)
    assert set(loaded) == {"servers", "roles"}
    assert loaded["servers"] == SAMPLE_DATA


def test_load_dir_recursive(tmp_path):
    nested = tmp_path / "guilds"
    nested.mkdir()
    (nested / "a.jp").write_text("[s]\nx: 1\n", encoding="utf-8")
    loaded = jpml.load_dir(tmp_path, recursive=True)
    assert loaded == {"guilds/a": {"s": {"x": 1}}}


def test_load_dir_missing_directory(tmp_path):
    with pytest.raises(NotADirectoryError):
        jpml.load_dir(tmp_path / "nope")


# -- JPConfig --------------------------------------------------------------


def test_config_behaves_like_a_mapping():
    config = JPConfig.loads(SAMPLE)
    assert len(config) == 2
    assert set(config) == {"SERVER_ID", "SERVER_ID_2"}
    assert config["SERVER_ID_2"]["prefix"] == "!"
    config["NEW"] = {"a": 1}
    assert "NEW" in config
    del config["NEW"]
    assert "NEW" not in config


def test_config_dotted_paths():
    config = JPConfig.loads(SAMPLE)
    assert config.get_path("SERVER_ID.config.disabled_users") == [9892, 82082, 8209]
    assert config.get_path("SERVER_ID.config.disabled_channels") is None
    assert config.get_path("nope.nope", "fallback") == "fallback"
    assert config.has_path("SERVER_ID.config.disabled_channels")
    assert not config.has_path("SERVER_ID.missing")


def test_config_set_path_creates_sections():
    config = JPConfig()
    config.set_path("A.b.c", [1])
    assert config.to_dict() == {"A": {"b": {"c": [1]}}}


def test_config_set_path_replaces_an_empty_value():
    config = JPConfig.loads("[s]\nconfig:\n")
    config.set_path("s.config.a", 1)
    assert config.to_dict() == {"s": {"config": {"a": 1}}}


def test_config_set_path_refuses_to_descend_into_a_scalar():
    config = JPConfig.loads("[s]\na: 1\n")
    with pytest.raises(TypeError, match="cannot descend"):
        config.set_path("s.a.b", 2)


def test_config_section_helper():
    config = JPConfig.loads(SAMPLE)
    assert config.section("SERVER_ID_2")["prefix"] == "!"
    with pytest.raises(KeyError):
        config.section("missing")
    assert config.section("missing", create=True) == {}


def test_config_merge_is_deep():
    config = JPConfig.loads(SAMPLE)
    config.merge({"SERVER_ID_2": {"modules": {"fun": True, "logs": True}}})
    assert config["SERVER_ID_2"]["modules"] == {
        "moderation": True,
        "fun": True,
        "logs": True,
    }
    assert config["SERVER_ID_2"]["prefix"] == "!"


def test_config_shallow_merge_replaces():
    config = JPConfig.loads(SAMPLE)
    config.merge({"SERVER_ID_2": {"prefix": "?"}}, deep=False)
    assert config["SERVER_ID_2"] == {"prefix": "?"}


def test_config_to_dict_is_a_deep_copy():
    config = JPConfig.loads(SAMPLE)
    snapshot = config.to_dict()
    snapshot["SERVER_ID"]["config"]["disabled_users"].append(1)
    assert config.get_path("SERVER_ID.config.disabled_users") == [9892, 82082, 8209]


def test_config_save_and_reload(tmp_path):
    path = tmp_path / "servers.jp"
    path.write_text(SAMPLE, encoding="utf-8")
    config = JPConfig.load(path)
    config.set_path("SERVER_ID_2.prefix", "?")
    config.save()
    assert JPConfig.load(path)["SERVER_ID_2"]["prefix"] == "?"
    config.set_path("SERVER_ID_2.prefix", "unsaved")
    config.reload()
    assert config["SERVER_ID_2"]["prefix"] == "?"


def test_config_load_missing_ok(tmp_path):
    path = tmp_path / "absent.jp"
    config = JPConfig.load(path, missing_ok=True)
    assert config.to_dict() == {}
    config.set_path("s.a", 1)
    assert config.save() == path
    assert jpml.load(path) == {"s": {"a": 1}}


def test_config_load_missing_raises_without_flag(tmp_path):
    with pytest.raises(OSError):
        JPConfig.load(tmp_path / "absent.jp")


def test_config_save_without_path():
    with pytest.raises(ValueError, match="no path"):
        JPConfig().save()


def test_config_remembers_write_options(tmp_path):
    path = tmp_path / "a.jp"
    config = JPConfig({"s": {"b": 1, "a": 2}}, path=path, indent=4, sort_keys=True)
    config.save()
    assert path.read_text(encoding="utf-8") == "[s]\na: 2\nb: 1\n"


def test_config_rejects_unknown_options():
    with pytest.raises(TypeError, match="unknown option"):
        JPConfig(nonsense=1)


def test_config_repr_mentions_sections():
    assert "SERVER_ID" in repr(JPConfig.loads(SAMPLE))


# -- command line ----------------------------------------------------------


def test_cli_check_ok(tmp_path, capsys):
    path = tmp_path / "a.jp"
    path.write_text(SAMPLE, encoding="utf-8")
    assert jpml.cli.main(["check", str(path)]) == 0
    assert "ok" in capsys.readouterr().out


def test_cli_check_failure(tmp_path, capsys):
    path = tmp_path / "a.jp"
    path.write_text("[s]\na 1\n", encoding="utf-8")
    assert jpml.cli.main(["check", str(path)]) == 1
    assert "expected ':'" in capsys.readouterr().err


def test_cli_fmt_writes_in_place(tmp_path):
    path = tmp_path / "a.jp"
    path.write_text("[s]\n  a:   {b:1,}\n", encoding="utf-8")
    assert jpml.cli.main(["fmt", "-w", str(path)]) == 0
    assert path.read_text(encoding="utf-8") == "[s]\na: {\n  b: 1\n}\n"


def test_cli_get(tmp_path, capsys):
    path = tmp_path / "a.jp"
    path.write_text(SAMPLE, encoding="utf-8")
    assert jpml.cli.main(["get", str(path), "SERVER_ID.config.disabled_users"]) == 0
    assert json.loads(capsys.readouterr().out) == [9892, 82082, 8209]


def test_cli_get_missing_path(tmp_path):
    path = tmp_path / "a.jp"
    path.write_text(SAMPLE, encoding="utf-8")
    assert jpml.cli.main(["get", str(path), "nope"]) == 1


def test_cli_json_conversions(tmp_path, capsys):
    source = tmp_path / "a.jp"
    source.write_text(SAMPLE, encoding="utf-8")
    target = tmp_path / "a.json"
    assert jpml.cli.main(["to-json", str(source), "-o", str(target)]) == 0
    assert json.loads(target.read_text(encoding="utf-8")) == SAMPLE_DATA
    back = tmp_path / "b.jp"
    assert jpml.cli.main(["from-json", str(target), "-o", str(back)]) == 0
    assert back.read_text(encoding="utf-8") == SAMPLE
