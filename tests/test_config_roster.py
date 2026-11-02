import copy
import os
import tempfile
import tomllib
import unittest
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from unittest import mock

from caokit.adapters import (
    AdapterError,
    adapter_ids,
    list_models,
    load_adapter,
    validate_model,
    vendor_of,
)
from caokit.config import (
    Config,
    ConfigError,
    default_path,
    dump_config,
    load_config,
    parse_config,
)
from caokit.roster import check_roster

GOOD: dict[str, Any] = {
    "schema": 1,
    "roles": {
        "general": {"tool": "claude", "model": "sonnet"},
        "engineer": {"tool": "claude", "model": "opus"},
        "scout": {"tool": "antigravity", "model": "gemini-3.8-flash-medium"},
        "inspector": {"tool": "antigravity", "model": "gemini-4-argon-high"},
    },
    "policy": {"allow_soft_engineer": False},
}


def cfg(**over: str | None) -> Config:
    """Build a Config from GOOD, overriding ``<role>__<field>`` (None removes the field)."""
    d = copy.deepcopy(GOOD)
    for k, v in over.items():
        role, field = k.split("__")
        if v is None:
            d["roles"][role].pop(field, None)
        else:
            d["roles"][role][field] = v
    return parse_config(d)


class ConfigTests(unittest.TestCase):
    def test_roundtrip(self):
        c = parse_config(GOOD)
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "caokit.toml"
            p.write_text(dump_config(c))
            self.assertEqual(load_config(p), c)

    def test_model_optional(self):
        c = cfg(general__model=None)
        self.assertIsNone(c.roles["general"].model)

    def test_unknown_role(self):
        d = {**GOOD, "roles": {**GOOD["roles"], "colonel": {"tool": "claude"}}}
        with self.assertRaisesRegex(ConfigError, "roles.colonel"):
            parse_config(d)

    def test_missing_role(self):
        d = {**GOOD, "roles": {k: v for k, v in GOOD["roles"].items() if k != "scout"}}
        with self.assertRaisesRegex(ConfigError, "roles.scout"):
            parse_config(d)

    def test_unknown_key(self):
        d = {**GOOD, "roles": {**GOOD["roles"], "scout": {"tool": "claude", "modle": "x"}}}
        with self.assertRaisesRegex(ConfigError, "roles.scout.modle"):
            parse_config(d)

    def test_bad_schema(self):
        with self.assertRaisesRegex(ConfigError, "schema"):
            parse_config({**GOOD, "schema": 2})

    def test_missing_file(self):
        with self.assertRaisesRegex(ConfigError, "not found"):
            load_config(Path("/nonexistent/caokit.toml"))


class RosterTests(unittest.TestCase):
    def test_valid(self):
        r = check_roster(cfg())
        self.assertEqual(r.errors, [])

    def test_soft_engineer_requires_flag(self):
        c = cfg(
            engineer__tool="antigravity",
            engineer__model="gemini-4-argon-high",
            inspector__tool="claude",
            inspector__model="sonnet",
        )
        self.assertTrue(any("allow-soft-engineer" in e for e in check_roster(c).errors))
        c.allow_soft_engineer = True
        r = check_roster(c)
        self.assertEqual(r.errors, [])
        self.assertTrue(any("advisory" in w for w in r.warnings))

    def test_soft_general_requires_flag(self):
        c = cfg(general__tool="antigravity", general__model="gemini-4-argon-high")
        self.assertTrue(any("allow-soft-general" in e for e in check_roster(c).errors))
        c.allow_soft_general = True
        r = check_roster(c)
        self.assertEqual(r.errors, [])
        self.assertTrue(any(w.startswith("general uses") for w in r.warnings))

    def test_parked_tool_still_cannot_be_general(self):
        c = cfg(general__tool="codex", general__model=None)
        self.assertTrue(any("parked" in e for e in check_roster(c).errors))

    def test_soft_general_policy_round_trips(self):
        c = cfg()
        c.allow_soft_general = True
        self.assertTrue(parse_config(tomllib.loads(dump_config(c))).allow_soft_general)

    def test_same_tool_inspector_errors(self):
        c = cfg(inspector__tool="claude", inspector__model="sonnet")
        self.assertTrue(any("cross-provider" in e for e in check_roster(c).errors))

    def test_same_vendor_via_other_tool_errors(self):
        c = cfg(inspector__model="claude-opus-5-5-high")
        errs = check_roster(c).errors
        self.assertTrue(any("vendor" in e for e in errs), errs)

    def test_single_provider_flag_downgrades(self):
        c = cfg(
            scout__tool="claude",
            scout__model="sonnet",
            inspector__tool="claude",
            inspector__model="sonnet",
        )
        self.assertTrue(check_roster(c).errors)
        c.allow_single_provider = True
        r = check_roster(c)
        self.assertEqual(r.errors, [])
        self.assertTrue(any("single provider" in w.lower() for w in r.warnings))

    def test_general_must_be_claude(self):
        c = cfg(general__tool="antigravity", general__model="gemini-4-argon-high")
        self.assertTrue(any("general" in e and "antigravity" in e for e in check_roster(c).errors))

    def test_codex_parked(self):
        c = cfg(scout__tool="codex", scout__model=None)
        self.assertTrue(any("parked" in e for e in check_roster(c).errors))

    def test_unknown_tool(self):
        c = cfg(scout__tool="nope")
        self.assertTrue(any("unknown tool" in e for e in check_roster(c).errors))


class VendorTests(unittest.TestCase):
    def test_vendor_of(self):
        agy = load_adapter("antigravity")
        self.assertEqual(vendor_of(agy, "gemini-4-argon-high"), "google")
        self.assertEqual(vendor_of(agy, "claude-sonnet-5-5-low"), "anthropic")
        self.assertEqual(vendor_of(agy, "gpt-oss-120b-medium"), "openai")
        self.assertEqual(vendor_of(load_adapter("claude"), "sonnet"), "anthropic")
        self.assertEqual(vendor_of(agy, None), "google")


class FakeResult:
    """Minimal ProcessResult for runner fakes."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class AdapterTests(unittest.TestCase):
    def test_traversal_names_rejected(self):
        for bad in ("../x", "claude/../x", "", "Claude", "a.b"):
            with self.assertRaises(AdapterError, msg=bad):
                load_adapter(bad)

    def test_adapter_ids_include_codex_parked(self):
        self.assertIn("codex", adapter_ids())
        self.assertEqual(load_adapter("codex").status, "parked")

    def test_list_models_filters_banner(self):
        def runner(argv: Sequence[str]) -> FakeResult:
            return FakeResult(0, "Fetching available models...\ngemini-4-argon-high\tG\n")

        self.assertEqual(list_models(load_adapter("antigravity"), runner), ["gemini-4-argon-high"])

    def test_list_models_empty_output_errors(self):
        def runner(argv: Sequence[str]) -> FakeResult:
            return FakeResult(0, "Fetching available models...\n")

        with self.assertRaisesRegex(AdapterError, "listed no models"):
            list_models(load_adapter("antigravity"), runner)

    def test_list_models_failure_and_missing_binary(self):
        def failing(argv: Sequence[str]) -> FakeResult:
            return FakeResult(1, "", "not logged in")

        def missing(argv: Sequence[str]) -> FakeResult:
            raise FileNotFoundError("agy")

        agy = load_adapter("antigravity")
        with self.assertRaisesRegex(AdapterError, "logged in"):
            list_models(agy, failing)
        with self.assertRaisesRegex(AdapterError, "cannot run"):
            list_models(agy, missing)

    def test_shape_tool_has_no_model_list(self):
        self.assertEqual(list_models(load_adapter("claude")), [])

    def test_validate_model_claude_shapes(self):
        claude = load_adapter("claude")
        self.assertEqual(validate_model(claude, "opus"), ([], []))
        self.assertEqual(validate_model(claude, "claude-opus-5-5"), ([], []))
        errors, warnings = validate_model(claude, "mystery")
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)


class ConfigFileTests(unittest.TestCase):
    def test_dump_omits_model_when_none(self):
        text = dump_config(cfg(general__model=None))
        general = text.split("[roles.general]")[1].split("[roles.")[0]
        self.assertNotIn("model", general)

    def test_default_path_honours_caokit_home(self):
        with mock.patch.dict(os.environ, {"CAOKIT_HOME": "/somewhere"}):
            self.assertEqual(default_path(), Path("/somewhere/caokit.toml"))

    def test_default_path_falls_back_to_dot_config(self):
        env = {k: v for k, v in os.environ.items() if k != "CAOKIT_HOME"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(default_path(), Path.home() / ".config" / "caokit" / "caokit.toml")

    def test_invalid_toml_is_config_error(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "caokit.toml"
            p.write_text("this is = = not toml")
            with self.assertRaisesRegex(ConfigError, "invalid TOML"):
                load_config(p)

    def test_non_bool_policy_rejected(self):
        d = copy.deepcopy(GOOD)
        d["policy"] = {"allow_soft_engineer": "yes"}
        with self.assertRaisesRegex(ConfigError, "policy.allow_soft_engineer"):
            parse_config(d)


if __name__ == "__main__":
    unittest.main()
