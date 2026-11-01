import unittest

from caokit.gitignore import BEGIN, END, merge_gitignore


class MergeGitignoreTests(unittest.TestCase):
    def test_empty_gets_block(self):
        out = merge_gitignore("")
        self.assertIn(BEGIN, out)
        self.assertIn(".company/*", out)
        self.assertIn("!.company/contracts/", out)
        self.assertIn(END, out)
        self.assertTrue(out.endswith("\n"))

    def test_existing_rules_preserved_in_order(self):
        existing = "node_modules/\n.env\n"
        out = merge_gitignore(existing)
        self.assertTrue(out.startswith(existing))
        self.assertIn(BEGIN, out)

    def test_no_trailing_newline(self):
        out = merge_gitignore("dist")
        self.assertTrue(out.startswith("dist\n"))
        self.assertIn(BEGIN, out)

    def test_crlf_preserved(self):
        out = merge_gitignore("a\r\nb\r\n")
        self.assertTrue(out.startswith("a\r\nb\r\n"))
        self.assertNotIn("\n", out.replace("\r\n", ""))

    def test_idempotent(self):
        once = merge_gitignore("a\n")
        self.assertEqual(merge_gitignore(once), once)

    def test_block_replaced_in_place(self):
        old = f"a\n{BEGIN}\n.company/old\n{END}\nb\n"
        out = merge_gitignore(old)
        self.assertNotIn(".company/old", out)
        self.assertTrue(out.startswith("a\n"))
        self.assertTrue(out.endswith("b\n"))
        self.assertEqual(out.count(BEGIN), 1)

    def test_user_rule_untouched_when_user_already_ignores_company(self):
        out = merge_gitignore(".company/\n")
        self.assertTrue(out.startswith(".company/\n"))


if __name__ == "__main__":
    unittest.main()
