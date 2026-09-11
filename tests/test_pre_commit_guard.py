"""Exercise staged-change protection with synthetic terms in disposable repos."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/git-hooks"))
import pre_commit_guard as guard  # noqa: E402


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Guard Test")
        self.git("config", "user.email", "guard@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.terms = self.root / ".git/info/bashi-sensitive-terms.txt"
        self.terms.write_text("# Synthetic entries only\nPRIVATE_SENTINEL_9X\n", encoding="utf-8")

    def git(self, *args):
        env = {k: v for k, v in os.environ.items()
               if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
        return subprocess.check_output(["git", "-C", str(self.root), *args],
                                       stderr=subprocess.PIPE, env=env)

    def stage(self, name="ordinary.txt", content="ordinary content\n", force=False):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        self.git("add", *(["-f"] if force else []), "--", name)
        return path

    def check(self):
        return guard.check_staged(self.root, self.terms)

    def test_ordinary_change_passes(self):
        self.stage()
        self.assertEqual(self.check(), [])

    def test_force_added_ignored_path_is_blocked(self):
        self.stage(".gitignore", "local-only/\n")
        self.stage("local-only/private.txt", force=True)
        self.assertTrue(any("Ignored staged path" in x for x in self.check()))

    def test_real_ignore_rules_need_no_second_allowlist(self):
        self.stage(".gitignore", (ROOT / ".gitignore").read_bytes())
        paths = ["tests/brand_new_helper.py", "tests/run_clone_blind_a.py",
                 "tests/test_new_feature.py", "tests/test_m1a_base_icl_longform.py"]
        for path in paths:
            self.stage(path, force=True)
        self.assertEqual(set(guard.ignored_paths(self.root, paths)),
                         {paths[0], paths[3]})

    def test_ignore_check_covers_already_tracked_files(self):
        self.stage()
        self.git("commit", "-qm", "initial")
        self.stage(".gitignore", "ordinary.txt\n")
        self.stage(content="changed\n", force=True)
        self.assertIn("ordinary.txt", guard.ignored_paths(self.root, ["ordinary.txt"]))

    def test_added_residue_is_blocked(self):
        for word in ("ChatGPT", "Claude", "DeepSeek", "OneDrive", "scratchpad",
                     r"C:\Users\example\data", r"C:\Temp\data",
                     "files.fm", "markdownpanel-virtualhost",
                     "01234567-89ab-cdef-0123-456789abcdef"):
            with self.subTest(word=word):
                self.stage(content=word + "\n")
                self.assertTrue(any("residue" in x for x in self.check()))

    def test_product_model_name_is_not_residue(self):
        self.stage(content="Qwen3-TTS is the bundled model name\n")
        self.assertEqual(self.check(), [])

    def test_old_residue_does_not_block_unrelated_addition(self):
        self.stage(content="ChatGPT in a historical line\n")
        self.git("commit", "-qm", "initial")
        self.stage(content="ChatGPT in a historical line\nordinary addition\n")
        self.assertEqual(self.check(), [])

    def test_removed_residue_does_not_block(self):
        self.stage(content="ChatGPT\nretained\n")
        self.git("commit", "-qm", "initial")
        self.stage(content="retained\n")
        self.assertEqual(self.check(), [])

    def test_rename_retains_added_line_semantics(self):
        self.stage(content="ChatGPT in a historical line\n")
        self.git("commit", "-qm", "initial")
        self.git("mv", "ordinary.txt", "renamed.txt")
        self.assertEqual(self.check(), [])

    def test_new_lines_starting_plus_are_not_mistaken_for_headers(self):
        self.stage(content="++ChatGPT\n")
        self.assertTrue(self.check())

    def test_staged_bad_worktree_clean_is_blocked(self):
        path = self.stage(content="ChatGPT\n")
        path.write_text("clean worktree\n", encoding="utf-8")
        self.assertTrue(self.check())

    def test_staged_clean_worktree_bad_passes(self):
        path = self.stage()
        path.write_text("ChatGPT\n", encoding="utf-8")
        self.assertEqual(self.check(), [])

    def test_trace_allowlist(self):
        for path in guard.TRACE_ALLOWLIST:
            self.stage(path, "ChatGPT files.fm C:/Users/example\n")
        self.assertEqual(self.check(), [])

    def test_pdf_only_patterns_and_hardware_name_are_allowed(self):
        self.stage(content="file: /tmp/a /home/user /Users/example Copilot+ PC\n")
        self.assertEqual(self.check(), [])

    def test_binary_residue_is_blocked(self):
        self.stage("payload.bin", b"\x00prefix ChatGPT suffix")
        self.assertTrue(any("binary" in x for x in self.check()))

    def test_forced_binary_attribute_is_respected(self):
        self.stage(".gitattributes", "*.dat -diff\n")
        self.stage("payload.dat", "historical ChatGPT\n")
        self.git("commit", "-qm", "initial")
        self.stage("payload.dat", "historical ChatGPT\nnew ordinary data\n")
        self.assertTrue(any("binary" in x for x in self.check()))

    def test_sensitive_added_content_is_blocked_without_echoing_term(self):
        self.stage(content="private_sentinel_9x\n")
        issues = self.check()
        self.assertTrue(any("sensitive" in x for x in issues))
        self.assertNotIn("private_sentinel_9x", str(issues).lower())

    def test_sensitive_filename_is_blocked_and_withheld(self):
        self.stage("PRIVATE_SENTINEL_9X.txt")
        issues = self.check()
        self.assertTrue(any("staged path" in x for x in issues))
        self.assertNotIn("PRIVATE_SENTINEL_9X", str(issues))

    def test_sensitive_content_has_no_trace_allowlist(self):
        self.stage("tests/test_pre_commit_guard.py", "PRIVATE_SENTINEL_9X\n")
        self.assertTrue(any("sensitive" in x for x in self.check()))

    def test_sensitive_binary_is_blocked(self):
        self.stage("payload.bin", b"\x00PRIVATE_SENTINEL_9X")
        self.assertTrue(any("sensitive" in x for x in self.check()))

    def test_sensitive_old_line_does_not_block_unrelated_addition(self):
        self.stage(content="PRIVATE_SENTINEL_9X\n")
        self.git("commit", "-qm", "initial")
        self.stage(content="PRIVATE_SENTINEL_9X\nordinary addition\n")
        self.assertEqual(self.check(), [])

    def test_missing_terms_fail_closed_even_with_empty_index(self):
        self.terms.unlink()
        with self.assertRaisesRegex(guard.GuardError, "Restore"):
            self.check()

    def test_empty_comments_only_and_invalid_utf8_fail_closed(self):
        for data in (b"", b" # only a comment\n\n", b"\xff"):
            with self.subTest(data=data):
                self.terms.write_bytes(data)
                with self.assertRaises(guard.GuardError):
                    self.check()

    def test_bom_crlf_and_comments_supported(self):
        self.terms.write_bytes(b"\xef\xbb\xbf# local\r\nPRIVATE_SENTINEL_9X\r\n")
        self.stage(content="private_sentinel_9x\n")
        self.assertTrue(self.check())

    def test_default_local_terms_path(self):
        self.stage()
        self.assertEqual(guard.load_terms(self.root, self.terms), ("private_sentinel_9x",))

    def test_env_override_via_actual_cli(self):
        override = self.root / ".git/info/alternate.txt"
        override.write_text("ALTERNATE_SENTINEL\n", encoding="utf-8")
        self.stage(content="ALTERNATE_SENTINEL\n")
        p = subprocess.run([sys.executable, str(ROOT / "scripts/git-hooks/pre_commit_guard.py")],
                           cwd=self.root, env={**os.environ, guard.TERMS_ENV: str(override)},
                           capture_output=True)
        self.assertEqual(p.returncode, 1)
        self.assertIn(b"sensitive", p.stderr)

    def guard_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/git-hooks/pre_commit_guard.py"), *args],
            cwd=self.root, env={**os.environ, guard.TERMS_ENV: str(self.terms)},
            capture_output=True)

    def commit_msg(self, text):
        message = self.root / "COMMIT_EDITMSG"
        message.write_text(text, encoding="utf-8")
        return self.guard_cli("--commit-msg", str(message))

    def test_commit_msg_cli_exit_codes(self):
        self.assertEqual(self.commit_msg("build: ordinary subject\n").returncode, 0)
        trailer = self.commit_msg(
            "build: ordinary subject\n\nCo-Authored-By: Someone <someone@example.invalid>\n")
        self.assertEqual(trailer.returncode, 1)
        named = self.commit_msg("build: mentions DeepSeek\n")
        self.assertEqual(named.returncode, 1)
        self.assertNotIn(b"DeepSeek", named.stderr)

    def test_commit_msg_cli_fails_closed_without_terms(self):
        self.terms.unlink()
        blocked = self.commit_msg("build: ordinary subject\n")
        self.assertEqual(blocked.returncode, 1)
        self.assertIn(b"Restore", blocked.stderr)

    def test_deleted_ignored_file_is_not_checked(self):
        self.stage()
        self.git("commit", "-qm", "initial")
        self.stage(".gitignore", "ordinary.txt\n")
        self.git("rm", "ordinary.txt")
        self.assertEqual(self.check(), [])

    def test_spaces_and_literal_pathspec_characters(self):
        self.stage("space [a] name.txt", "ChatGPT\n")
        self.assertTrue(self.check())


class MessageTests(unittest.TestCase):
    TERMS = ("private_sentinel_9x",)

    def check(self, text):
        return guard.check_message(text, self.TERMS)

    def test_ordinary_message_passes(self):
        self.assertEqual(self.check("build: ordinary subject\n"), [])

    def test_attribution_trailer_is_blocked(self):
        for trailer in ("Co-Authored-By: Someone <someone@example.invalid>",
                        "co-authored-by: someone <someone@example.invalid>"):
            with self.subTest(trailer=trailer):
                text = "build: ordinary subject\n\n" + trailer + "\n"
                self.assertTrue(any("trailer" in issue.lower() for issue in self.check(text)))

    def test_agent_name_in_subject_or_body_is_blocked(self):
        for name in ("ChatGPT", "Claude", "Codex", "DeepSeek", "Gemini", "OpenAI"):
            with self.subTest(name=name):
                for text in (f"{name}: tidy the docs\n",
                             f"build: tidy the docs\n\n{name}\n"):
                    with self.subTest(text=text):
                        self.assertTrue(self.check(text))

    def test_agent_name_only_in_a_comment_line_passes(self):
        self.assertEqual(self.check("build: tidy the docs\n\n# DeepSeek was not involved\n"), [])

    def test_agent_name_only_after_scissors_passes(self):
        text = "build: tidy the docs\n\n" + guard.SCISSORS + "\n+DeepSeek appears in the diff\n"
        self.assertEqual(self.check(text), [])

    def test_sensitive_term_is_blocked_without_echoing_it(self):
        issues = self.check("build: tidy the docs\n\nPRIVATE_SENTINEL_9X\n")
        self.assertTrue(any("sensitive" in issue for issue in issues))
        self.assertNotIn("private_sentinel_9x", str(issues).lower())

    def test_product_model_name_passes(self):
        self.assertEqual(self.check("docs: describe Qwen3-TTS support\n"), [])


class PatternTests(unittest.TestCase):
    def test_pdf_pattern_composition_is_exactly_preserved(self):
        import check_pdf_links as pdf
        sep = "[" + chr(92) + chr(92) + "/]"
        expected = ("file:|[A-Za-z]:" + sep + "{1,2}Users" + sep
                    + "|/home/[a-z]|/Users/[A-Za-z]|OneDrive|scratchpad|"
                    + sep + "Temp" + sep + "|[A-Za-z]:" + sep + "{1,2}tmp" + sep
                    + "|" + sep + "tmp" + sep
                    + r"|markdownpanel-virtualhost|files\.fm"
                    + r"|claude|codex|anthropic|chatgpt|openai|gemini|copilot(?!\+)"
                    + r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
        self.assertEqual(pdf.FORBIDDEN.pattern.encode(), expected.encode())


if __name__ == "__main__":
    unittest.main()
