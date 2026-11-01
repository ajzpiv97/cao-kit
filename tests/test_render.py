import re
import unittest

from caokit.adapters import load_adapter
from caokit.render import PROFILE_NAME_RE, profile_name, render_profile

ROLES = ("general", "engineer", "scout", "inspector")


class RenderTests(unittest.TestCase):
    """Profiles render deterministically, validly and tool-agnostically."""

    def test_names_valid_for_cao(self):
        for r in ROLES:
            for t in ("claude", "antigravity"):
                n = profile_name(r, t)
                self.assertRegex(n, PROFILE_NAME_RE)
        self.assertEqual(profile_name("inspector", "antigravity"), "inspector-antigravity")

    def test_name_rejects_bad_parts(self):
        with self.assertRaises(ValueError):
            profile_name("inspector", "a.b")

    def test_claude_engineer(self):
        out = render_profile("engineer", load_adapter("claude"), "opus")
        self.assertTrue(out.startswith("---\nname: engineer-claude\n"))
        self.assertIn("provider: claude_code\n", out)
        self.assertIn('model: "opus"\n', out)
        self.assertIn("permissionMode: auto\n", out)
        self.assertNotIn("Tool notes", out)

    def test_model_omitted_when_unset(self):
        out = render_profile("scout", load_adapter("claude"), None)
        self.assertNotRegex(out, r"(?m)^model:")

    def test_antigravity_inspector_has_notes_and_model(self):
        out = render_profile("inspector", load_adapter("antigravity"), "gemini-4-argon-high")
        self.assertIn("provider: antigravity_cli\n", out)
        self.assertIn('model: "gemini-4-argon-high"\n', out)
        self.assertIn("## Tool notes", out)
        self.assertIn("advisory", out)
        self.assertNotIn("permissionMode", out)

    def test_deterministic(self):
        a = load_adapter("claude")
        self.assertEqual(
            render_profile("general", a, "sonnet"), render_profile("general", a, "sonnet")
        )

    def test_role_bodies_tool_and_legacy_agnostic(self):
        for r in ROLES:
            out = render_profile(r, load_adapter("claude"), None)
            for bad in ("captain", "startup_", "claude_engineer", "agy_", "__AGY"):
                self.assertNotIn(bad, out.lower(), (r, bad))

    def test_no_wildcard_tools(self):
        for r in ROLES:
            self.assertNotIn('"*"', render_profile(r, load_adapter("claude"), None))

    def test_frontmatter_delimited(self):
        out = render_profile("general", load_adapter("claude"), None)
        self.assertEqual(len(re.findall(r"(?m)^---$", out.split("\n# ")[0])), 2)


if __name__ == "__main__":
    unittest.main()
