import os
import ast
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from backend_probe import BackendOverrideConflictError, BackendProbeError, BackendSelection

import app


class AppBootstrapTests(unittest.TestCase):
    def test_locked_probe_failure_puts_running_copy_cause_first(self) -> None:
        english, chinese = app._probe_failure_causes("[LOCKED] GGUF probe failed")

        self.assertIn("Another copy", english[0])
        self.assertIn("另一个副本", chinese[0])

    def test_regular_probe_failure_causes_remain_unchanged(self) -> None:
        english, chinese = app._probe_failure_causes("ordinary probe failure")

        self.assertEqual(
            [
                "  - GGUF runtime model files missing or corrupted -",
                "    re-run the launcher to re-download from ModelScope.",
                "  - Vulkan / DirectML drivers outdated - update GPU driver.",
                "  - Insufficient RAM (need >= 8 GB free for 1.7B model).",
            ],
            english,
        )
        self.assertEqual(
            [
                "  - GGUF 运行模型文件缺失或损坏 —— 请重新运行启动器从 ModelScope 下载。",
                "  - Vulkan / DirectML 驱动过旧 —— 请更新显卡驱动。",
                "  - 内存不足（1.7B 模型需要至少 8 GB 可用内存）。",
            ],
            chinese,
        )
        self.assertNotIn("Another copy", "\n".join(english))
        self.assertNotIn("另一个副本", "\n".join(chinese))

    def test_probe_failure_logs_ascii_and_prints_localized_console_detail(self) -> None:
        localized_error = BackendProbeError("[LOCKED] PermissionError: 拒绝访问。")
        with patch(
            "app.bootstrap_backend_selection",
            side_effect=localized_error,
        ), patch.object(app.logger, "error") as error_mock, patch(
            "builtins.print"
        ) as print_mock:
            with self.assertRaises(SystemExit):
                app._bootstrap_backend_or_exit()

        rendered_log_lines = []
        for call in error_mock.call_args_list:
            rendered_log_lines.append(call.args[0] % call.args[1:])
        self.assertTrue(all(line.isascii() for line in rendered_log_lines))
        console_text = "\n".join(str(call.args[0]) for call in print_mock.call_args_list)
        self.assertIn("拒绝访问", console_text)
        self.assertIn("另一个副本", console_text)

    def test_app_logger_string_literals_are_ascii(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        logger_literals = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if not isinstance(node.func.value, ast.Name) or node.func.value.id != "logger":
                continue
            logger_literals.extend(
                arg.value
                for arg in node.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            )

        self.assertTrue(logger_literals)
        for literal in logger_literals:
            with self.subTest(literal=literal):
                self.assertTrue(literal.isascii())

    def test_openmp_workaround_is_set_before_runtime_imports(self) -> None:
        self.assertEqual("TRUE", os.environ.get("KMP_DUPLICATE_LIB_OK"))
        self.assertEqual("utf-8", os.environ.get("PYTHONIOENCODING"))

        source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
        self.assertLess(
            source.index('os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")'),
            source.index("import argparse"),
        )
        self.assertLess(
            source.index('os.environ.setdefault("PYTHONIOENCODING", "utf-8")'),
            source.index("import argparse"),
        )

    def test_app_environment_hardening_reaches_spawned_python(self) -> None:
        child_env = dict(os.environ)
        child_env.pop("PYTHONIOENCODING", None)
        child = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import app, subprocess, sys; "
                    "r=subprocess.run([sys.executable, '-c', "
                    "'import sys; print(sys.stdout.encoding); print(chr(0x1f50a))'], "
                    "capture_output=True, check=True); "
                    "sys.stdout.buffer.write(r.stdout)"
                ),
            ],
            capture_output=True,
            encoding="utf-8",
            check=True,
            env=child_env,
        )

        self.assertEqual(["utf-8", "🔊"], child.stdout.strip().splitlines())

    def test_portable_launcher_sets_openmp_workaround_before_app(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "run_portable.ps1").read_text(
            encoding="utf-8"
        )
        self.assertLess(
            source.index('$env:KMP_DUPLICATE_LIB_OK = "TRUE"'),
            source.index("('[STEP] Starting app.py"),
        )
        self.assertLess(source.index("Ensure-Pip"), source.index("chcp 65001"))
        self.assertLess(
            source.index("chcp 65001"),
            source.index("('[STEP] Starting app.py"),
        )

    def test_bootstrap_logs_selection_log_line(self) -> None:
        selection = BackendSelection(
            backend="gguf",
            reason="USE_GGUF_BACKEND=1 override",
            source="override",
        )

        with patch("app.bootstrap_backend_selection", return_value=type("R", (), {"selection": selection})()):
            with patch.object(app.logger, "info") as info_mock:
                app._bootstrap_backend_or_exit()

        info_mock.assert_called_once_with(
            "Selected backend: gguf (reason: USE_GGUF_BACKEND=1 override)"
        )

    def test_logging_is_configured_before_backend_bootstrap_and_server(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
        main_source = source[source.index('if __name__ == "__main__":') :]

        self.assertLess(main_source.index("setup_logging()"), main_source.index("_bootstrap_backend_or_exit()"))
        self.assertLess(main_source.index("setup_logging()"), main_source.index("app.run("))

    def test_bootstrap_exits_cleanly_on_override_conflict(self) -> None:
        with patch(
            "app.bootstrap_backend_selection",
            side_effect=BackendOverrideConflictError(
                "Conflicting backend overrides: USE_GGUF_BACKEND=1, USE_PYTORCH_BACKEND=1. Unset one."
            ),
        ):
            with self.assertRaises(SystemExit) as ctx:
                app._bootstrap_backend_or_exit()

        self.assertEqual(ctx.exception.code, 2)

    def test_bootstrap_exits_cleanly_on_probe_failure(self) -> None:
        with patch(
            "app.bootstrap_backend_selection",
            side_effect=BackendProbeError("No backend passed preflight probe."),
        ):
            with self.assertRaises(SystemExit) as ctx:
                app._bootstrap_backend_or_exit()

        self.assertEqual(ctx.exception.code, 3)


if __name__ == "__main__":
    unittest.main()
