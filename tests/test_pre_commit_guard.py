"""Exercise staged-change protection with synthetic terms in disposable repos."""

import io
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

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
        # The rules under test are the repository's own. This machine also mirrors
        # several of them in its global exclude file, unanchored, where they match
        # at every level and shadow the anchored repository rules; pin the exclude
        # file to an empty one so each case exercises the repository alone.
        self.excludes = self.root / ".git/empty-excludes"
        self.excludes.write_text("", encoding="utf-8")
        self.git("config", "core.excludesFile", str(self.excludes))
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

    def stage_gitignore(self):
        self.stage(".gitignore", (ROOT / ".gitignore").read_bytes())

    def test_internal_document_rules_are_root_anchored(self):
        self.stage_gitignore()
        names = ["TASK_05_x.md", "GLM_TASK_01_x.md", "DEEPSEEK_TASK_15_x.md",
                 "CODEX_X.md", "OS2026_x.md", "ACCEPTANCE_v0.1.3.md",
                 "CodeBuddy_plan.md", "TIMBRE_DRIFT_FINDINGS.md"]
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(guard.ignored_paths(self.root, [name]), [name])
                for parent in ("release_docs/", "docs/"):
                    self.assertEqual(guard.ignored_paths(self.root, [parent + name]), [])

    def test_publishable_documents_are_not_blocked(self):
        self.stage_gitignore()
        allowed = ["README.md", "THIRD_PARTY.md", "CONTRIBUTING.md", "CHANGELOG.md",
                   "docs/evidence/method.md", "release_docs/ACCEPTANCE_v0.1.4.md"]
        for path in allowed:
            with self.subTest(path=path):
                self.stage(path, "ordinary content\n", force=True)
        self.assertEqual(self.check(), [])

    def test_extended_agent_names_are_caught(self):
        for name in ("GLM", "Zhipu", "ChatGLM"):
            with self.subTest(name=name):
                self.stage(content=name + "\n")
                self.assertTrue(any("residue" in issue for issue in self.check()))

    def test_ignore_check_covers_already_tracked_files(self):
        self.stage()
        self.git("commit", "-qm", "initial")
        self.stage(".gitignore", "ordinary.txt\n")
        self.stage(content="changed\n", force=True)
        self.assertIn("ordinary.txt", guard.ignored_paths(self.root, ["ordinary.txt"]))

    def test_added_residue_is_blocked(self):
        for word in ("ChatGPT", "Claude", "DeepSeek", "CodeBuddy", "Qoder",
                     "OneDrive", "scratchpad",
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
        for name in ("ChatGPT", "Claude", "Codex", "DeepSeek", "CodeBuddy", "Qoder",
                     "Gemini", "OpenAI"):
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


class PrePushTests(unittest.TestCase):
    """Publish-time gating, exercised against a throwaway local remote.

    The disposable repositories set no ``core.hooksPath``, so the real pushes
    below only establish remote-tracking references; the guard itself is called
    directly with the records Git would hand a pre-push hook.
    """

    ZERO = "0" * 40
    PLATFORM_URLS = (
        (
            "GitHub",
            "https://github.com/gtree965/bashi-voice-factory-privacy.git",
            "https://github.com/contributor/bashi-voice-factory-privacy.git",
        ),
        (
            "Gitee",
            "https://gitee.com/gtree965/bashi-voice-factory-privacy.git",
            "https://gitee.com/contributor/bashi-voice-factory-privacy.git",
        ),
    )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "work"
        self.remote = self.base / "remote.git"
        self.base.mkdir(parents=True, exist_ok=True)
        self.git_run("init", "-q", "--initial-branch=main", str(self.root), cwd=self.base)
        self.git_run("init", "-q", "--bare", str(self.remote), cwd=self.base)
        self.git("config", "user.name", "Alex Li")
        self.git("config", "user.email", "ncorecpu@gmail.com")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "commit.gpgsign", "false")
        self.git("remote", "add", "origin", self.remote.as_uri())
        self.terms = self.root / ".git/info/bashi-sensitive-terms.txt"
        self.terms.write_text("# Synthetic entries only\nPRIVATE_SENTINEL_9X\n", encoding="utf-8")

    def git_run(self, *args, cwd=None, env=None):
        environment = {k: v for k, v in os.environ.items()
                       if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
        if env:
            environment.update(env)
        return subprocess.run(["git", *args], cwd=str(cwd or self.root),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)

    def git(self, *args, **kwargs):
        result = self.git_run(*args, **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        return result

    def commit(self, name, content, *message, env=None):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        self.git("add", "--", name)
        args = ["commit", "-q"]
        for part in message:
            args.extend(("-m", part))
        self.git(*args, env=env)
        return self.git("rev-parse", "HEAD").stdout.strip().decode()

    def publish(self):
        return self.git("push", "-q", "origin", "refs/heads/main:refs/heads/main")

    def baseline(self):
        """A commit that is genuinely on the remote before the case under test."""
        sha = self.commit("baseline.txt", "published content\n", "build: baseline")
        self.publish()
        return sha

    def records(self, local_sha, local_ref="refs/heads/main", remote_sha=None,
                remote_ref=None):
        return [(local_ref, local_sha, remote_ref or local_ref,
                 self.ZERO if remote_sha is None else remote_sha)]

    def check(self, records, remote_name=None, remote_url=None):
        return guard.check_pre_push(
            self.root,
            records,
            self.terms,
            remote_name=remote_name,
            remote_url=remote_url,
        )

    def test_official_url_normalization_covers_supported_git_forms(self):
        forms = {
            "GitHub": (
                "https://github.com/gtree965/bashi-voice-factory-privacy",
                "https://user@GITHUB.COM:443/GTREE965/BASHI-VOICE-FACTORY-PRIVACY.git/",
                "git@github.com:gtree965/bashi-voice-factory-privacy.git",
                "ssh://git@github.com:22/gtree965/bashi-voice-factory-privacy.git",
            ),
            "Gitee": (
                "https://gitee.com/gtree965/bashi-voice-factory-privacy",
                "https://user@GITEE.COM:443/GTREE965/BASHI-VOICE-FACTORY-PRIVACY.git/",
                "git@gitee.com:gtree965/bashi-voice-factory-privacy.git",
                "ssh://git@gitee.com:22/gtree965/bashi-voice-factory-privacy.git",
            ),
        }
        for platform, urls in forms.items():
            for url in urls:
                with self.subTest(platform=platform, url=url):
                    self.assertIs(guard.is_official_repository(url), True)

    def test_origin_named_fork_disables_commit_and_tag_identity_on_both_platforms(self):
        base = self.baseline()
        head = self.commit(
            "work.txt",
            "ordinary\n",
            "build: ordinary",
            env={"GIT_AUTHOR_NAME": "Someone", "GIT_COMMITTER_EMAIL": "someone@example.invalid"},
        )
        self.git("tag", "-a", "fork-probe", "-m", "ordinary release notes", base,
                 env={"GIT_COMMITTER_NAME": "Someone"})
        tag_sha = self.git("rev-parse", "fork-probe").stdout.strip().decode()
        records = self.records(head, remote_sha=base) + self.records(
            tag_sha, "refs/tags/fork-probe", remote_ref="refs/tags/fork-probe")
        for platform, _official, fork in self.PLATFORM_URLS:
            with self.subTest(platform=platform):
                self.assertEqual(
                    self.check(records, remote_name="origin", remote_url=fork),
                    [],
                )

    def test_non_origin_official_keeps_commit_identity_gate_on_both_platforms(self):
        base = self.baseline()
        head = self.commit("work.txt", "ordinary\n", "build: ordinary",
                           env={"GIT_AUTHOR_NAME": "Someone"})
        for platform, official, _fork in self.PLATFORM_URLS:
            with self.subTest(platform=platform):
                issues = self.check(
                    self.records(head, remote_sha=base),
                    remote_name="upstream",
                    remote_url=official,
                )
                self.assertTrue(any("author" in issue for issue in issues))

    def test_missing_and_malformed_urls_fail_closed(self):
        base = self.baseline()
        head = self.commit("work.txt", "ordinary\n", "build: ordinary",
                           env={"GIT_AUTHOR_NAME": "Someone"})
        cases = (
            ("missing", None),
            ("GitHub missing path", "https://github.com"),
            ("Gitee missing path", "https://gitee.com"),
            ("malformed", "not a remote url"),
        )
        for label, url in cases:
            with self.subTest(case=label):
                issues = self.check(
                    self.records(head, remote_sha=base),
                    remote_name="origin",
                    remote_url=url,
                )
                self.assertTrue(any("author" in issue for issue in issues))

    def test_official_targets_check_commit_and_tag_identity_on_both_platforms(self):
        base = self.baseline()
        head = self.commit("work.txt", "ordinary\n", "build: ordinary",
                           env={"GIT_AUTHOR_NAME": "Someone",
                                "GIT_COMMITTER_EMAIL": "someone@example.invalid"})
        self.git("tag", "-a", "official-probe", "-m", "ordinary release notes", base,
                 env={"GIT_COMMITTER_NAME": "Someone"})
        tag_sha = self.git("rev-parse", "official-probe").stdout.strip().decode()
        records = self.records(head, remote_sha=base) + self.records(
            tag_sha, "refs/tags/official-probe", remote_ref="refs/tags/official-probe")
        for platform, official, _fork in self.PLATFORM_URLS:
            with self.subTest(platform=platform):
                issues = self.check(records, remote_name="mirror", remote_url=official)
                self.assertTrue(any("author" in issue for issue in issues))
                self.assertTrue(any("committer" in issue for issue in issues))
                self.assertTrue(any("tagger" in issue for issue in issues))

    def test_fork_targets_still_reject_messages_and_content_on_both_platforms(self):
        base = self.baseline()
        head = self.commit("notes.txt", "ChatGPT wrote this\n", "build: drafted by CodeBuddy")
        for platform, _official, fork in self.PLATFORM_URLS:
            with self.subTest(platform=platform):
                issues = self.check(
                    self.records(head, remote_sha=base),
                    remote_name="origin",
                    remote_url=fork,
                )
                self.assertTrue(any("message" in issue for issue in issues))
                self.assertTrue(any("residue" in issue for issue in issues))

    def test_cli_passes_remote_and_url_to_policy(self):
        urls = [url for _platform, official, fork in self.PLATFORM_URLS
                for url in (official, fork)]
        urls.append(None)
        for url in urls:
            with self.subTest(url=url), \
                    patch.object(guard, "git", return_value=(str(self.root) + "\n").encode()), \
                    patch.object(guard, "read_push_records", return_value=[]), \
                    patch.object(guard, "check_pre_push", return_value=[]) as check_policy, \
                    patch.object(sys, "stdin", io.BytesIO(b"")):
                args = ["--pre-push", "origin"] + ([] if url is None else [url])
                self.assertEqual(guard.main(args), 0)
                check_policy.assert_called_once_with(
                    self.root,
                    [],
                    remote_name="origin",
                    remote_url=url,
                )

    def test_near_match_targets_are_not_official_on_both_platforms(self):
        cases = (
            "https://github.com.evil.example/gtree965/bashi-voice-factory-privacy",
            "https://github.com/gtree965/bashi-voice-factory-privacy-fork",
            "https://gitee.com.evil.example/gtree965/bashi-voice-factory-privacy",
            "https://gitee.com/gtree965/bashi-voice-factory-privacy-fork",
        )
        for url in cases:
            with self.subTest(url=url):
                self.assertIs(guard.is_official_repository(url), False)

    def test_clean_commit_on_a_published_baseline_passes(self):
        base = self.baseline()
        head = self.commit("work.txt", "ordinary\n", "build: ordinary")
        self.assertEqual(self.check(self.records(head, remote_sha=base)), [])

    def test_comment_line_in_a_pushed_message_is_blocked(self):
        base = self.baseline()
        head = self.commit("work.txt", "ordinary\n", "build: tidy", "# DeepSeek was here")
        self.assertIn("# DeepSeek", self.git("log", "-1", "--format=%B").stdout.decode())
        self.assertTrue(any("message" in issue for issue in
                            self.check(self.records(head, remote_sha=base))))

    def test_attribution_trailer_and_new_agent_names_are_blocked(self):
        base = self.baseline()
        for index, text in enumerate(("Co-Authored-By: Someone <someone@example.invalid>",
                                      "summarised by CodeBuddy",
                                      "drafted with Qoder")):
            with self.subTest(text=text):
                head = self.commit(f"work-{index}.txt", "ordinary\n", "build: tidy", text)
                self.assertTrue(self.check(self.records(head, remote_sha=base)))

    def test_unexpected_author_is_blocked(self):
        base = self.baseline()
        head = self.commit("work.txt", "ordinary\n", "build: tidy",
                           env={"GIT_AUTHOR_NAME": "Someone"})
        self.assertTrue(any("author" in issue for issue in
                            self.check(self.records(head, remote_sha=base))))

    def test_unexpected_committer_is_blocked(self):
        base = self.baseline()
        head = self.commit("work.txt", "ordinary\n", "build: tidy",
                           env={"GIT_COMMITTER_EMAIL": "someone@example.invalid"})
        self.assertTrue(any("committer" in issue for issue in
                            self.check(self.records(head, remote_sha=base))))

    def test_residue_in_a_new_file_is_blocked(self):
        base = self.baseline()
        head = self.commit("notes.txt", "ChatGPT wrote this\n", "build: notes")
        self.assertTrue(any("residue" in issue for issue in
                            self.check(self.records(head, remote_sha=base))))

    def test_residue_in_an_allowlisted_file_passes(self):
        base = self.baseline()
        head = self.commit("scripts/check_pdf_links.py", "ChatGPT\n", "build: pattern")
        self.assertEqual(self.check(self.records(head, remote_sha=base)), [])

    def test_sensitive_term_is_blocked_without_echoing_it(self):
        base = self.baseline()
        head = self.commit("notes.txt", "PRIVATE_SENTINEL_9X\n", "build: notes")
        issues = self.check(self.records(head, remote_sha=base))
        self.assertTrue(any("sensitive" in issue for issue in issues))
        self.assertNotIn("private_sentinel_9x", str(issues).lower())
        self.publish()
        head2 = self.commit("other.txt", "ordinary\n", "build: PRIVATE_SENTINEL_9X")
        issues = self.check(self.records(head2, remote_sha=head))
        self.assertTrue(any("sensitive" in issue for issue in issues))
        self.assertNotIn("private_sentinel_9x", str(issues).lower())

    def test_added_then_removed_sensitive_line_is_still_blocked(self):
        base = self.baseline()
        first = self.commit("notes.txt", "PRIVATE_SENTINEL_9X\n", "build: add")
        second = self.commit("notes.txt", "ordinary\n", "build: remove")
        issues = self.check(self.records(second, remote_sha=base))
        self.assertTrue(any("sensitive" in issue for issue in issues))
        self.assertTrue(any(first[:8] in issue for issue in issues))
        self.assertNotIn("private_sentinel_9x", str(issues).lower())

    def test_published_residue_does_not_block_a_later_push(self):
        base = self.commit("old.txt", "ChatGPT legacy line\n", "build: legacy")
        self.publish()
        head = self.commit("new.txt", "ordinary\n", "build: new")
        self.assertEqual(self.check(self.records(head, remote_sha=base)), [])

    def test_new_branch_scans_only_unpublished_commits(self):
        self.commit("old.txt", "ChatGPT legacy line\n", "build: legacy")
        self.publish()
        head = self.commit("new.txt", "ordinary\n", "build: new")
        self.git("branch", "topic")
        self.assertEqual(
            self.check(self.records(head, "refs/heads/topic",
                                    remote_ref="refs/heads/topic")), [])

    def test_deletion_publishes_nothing(self):
        base = self.baseline()
        self.commit("notes.txt", "ChatGPT\n", "build: notes")
        records = [("refs/heads/gone", self.ZERO, "refs/heads/gone", base)]
        self.assertEqual(self.check(records), [])

    def test_annotated_tag_message_is_blocked(self):
        base = self.baseline()
        self.git("tag", "-a", "probe-tag", "-m", "release notes by Codex", base)
        sha = self.git("rev-parse", "probe-tag").stdout.strip().decode()
        self.assertEqual(self.git("cat-file", "-t", sha).stdout.strip(), b"tag")
        self.assertTrue(any("tag" in issue for issue in
                            self.check(self.records(sha, "refs/tags/probe-tag",
                                                    remote_ref="refs/tags/probe-tag"))))

    def test_annotated_tag_tagger_is_blocked(self):
        base = self.baseline()
        self.git("tag", "-a", "probe-tag", "-m", "ordinary release notes", base,
                 env={"GIT_COMMITTER_NAME": "Someone"})
        sha = self.git("rev-parse", "probe-tag").stdout.strip().decode()
        self.assertTrue(any("tagger" in issue for issue in
                            self.check(self.records(sha, "refs/tags/probe-tag",
                                                    remote_ref="refs/tags/probe-tag"))))

    def test_lightweight_tag_on_a_published_commit_passes(self):
        base = self.baseline()
        self.git("tag", "probe-lw", base)
        sha = self.git("rev-parse", "probe-lw").stdout.strip().decode()
        self.assertEqual(self.git("cat-file", "-t", sha).stdout.strip(), b"commit")
        self.assertEqual(self.check(self.records(sha, "refs/tags/probe-lw",
                                                 remote_ref="refs/tags/probe-lw")), [])

    def test_forced_ignored_path_in_a_commit_is_blocked(self):
        base = self.baseline()
        self.commit(".gitignore", "local-only/\n", "build: ignore")
        path = self.root / "local-only/private.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ordinary\n", encoding="utf-8")
        self.git("add", "-f", "--", "local-only/private.txt")
        self.git("commit", "-q", "-m", "build: forced")
        head = self.git("rev-parse", "HEAD").stdout.strip().decode()
        self.assertTrue(any("Ignored" in issue for issue in
                            self.check(self.records(head, remote_sha=base))))

    def test_binary_residue_in_a_commit_is_blocked(self):
        base = self.baseline()
        head = self.commit("payload.bin", b"\x00prefix ChatGPT suffix", "build: payload")
        self.assertTrue(any("binary" in issue for issue in
                            self.check(self.records(head, remote_sha=base))))

    def test_merge_commit_is_read_from_its_first_parent(self):
        base = self.baseline()
        self.git("checkout", "-q", "-b", "side")
        self.commit("side.txt", "ordinary side\n", "build: side")
        self.git("checkout", "-q", "main")
        self.commit("main.txt", "ordinary main\n", "build: main")
        self.git("merge", "-q", "--no-ff", "-m", "build: merge", "side")
        head = self.git("rev-parse", "HEAD").stdout.strip().decode()
        self.assertTrue(self.git("show", "-s", "--format=%P", head).stdout.strip().count(b" "))
        self.assertEqual(self.check(self.records(head, remote_sha=base)), [])

    def test_missing_terms_fail_closed(self):
        base = self.baseline()
        head = self.commit("work.txt", "ordinary\n", "build: ordinary")
        self.terms.unlink()
        with self.assertRaisesRegex(guard.GuardError, "Restore"):
            self.check(self.records(head, remote_sha=base))

    def test_unparsable_push_input_is_refused(self):
        with self.assertRaisesRegex(guard.GuardError, "pre-push"):
            guard.read_push_records("refs/heads/main only-three-fields\n")

    def test_cli_exit_codes(self):
        base = self.baseline()
        clean = self.commit("clean.txt", "ordinary\n", "build: ordinary")
        cli = [sys.executable, str(ROOT / "scripts/git-hooks/pre_commit_guard.py"),
               "--pre-push", "origin", "https://example.invalid/repo.git"]
        env = {**os.environ, guard.TERMS_ENV: str(self.terms)}
        line = f"refs/heads/main {clean} refs/heads/main {base}\n"
        allowed = subprocess.run(cli, cwd=self.root, input=line.encode(),
                                 capture_output=True, env=env)
        self.assertEqual(allowed.returncode, 0)
        dirty = self.commit("dirty.txt", "ChatGPT\n", "build: dirty")
        line = f"refs/heads/main {dirty} refs/heads/main {clean}\n"
        blocked = subprocess.run(cli, cwd=self.root, input=line.encode(),
                                 capture_output=True, env=env)
        self.assertEqual(blocked.returncode, 1)
        self.assertIn(b"residue", blocked.stderr)


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

    def test_ai_tool_names_and_the_guard_extra_names_are_separate(self):
        import check_pdf_links as pdf
        self.assertEqual(
            pdf.AI_TOOL_NAMES,
            r"claude|codex|anthropic|chatgpt|openai|gemini|copilot(?!\+)")
        self.assertEqual(
            pdf.COMMIT_GUARD_EXTRA_AI_NAMES,
            "deepseek|codebuddy|qoder|glm|zhipu|chatglm")
        # re.UNICODE is added automatically for str patterns.
        self.assertEqual(pdf.FORBIDDEN.flags, re.IGNORECASE | re.UNICODE)

    def test_gitignore_residue_exemption_stays_narrow(self):
        lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertEqual({line for line in lines if guard.TRACE_TEXT.search(line)},
                         {"/GLM_TASK_*.md", "/DEEPSEEK_TASK_*.md", "/CODEX_*.md",
                          "/CodeBuddy_plan.md"})


if __name__ == "__main__":
    unittest.main()
