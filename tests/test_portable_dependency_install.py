import re
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]


class PortableDependencyInstallTests(unittest.TestCase):
    def test_qwen_tts_dependencies_are_explicit_without_gradio(self) -> None:
        requirements = (APP_ROOT / "requirements.txt").read_text(encoding="utf-8")

        self.assertNotIn("qwen-tts==", requirements)
        for dependency in ("librosa", "torchaudio", "sox", "einops"):
            with self.subTest(dependency=dependency):
                self.assertIn(f"{dependency}==", requirements)
        self.assertNotIn("gradio==", requirements)

    def test_launcher_installs_qwen_without_deps_then_restores_directml(self) -> None:
        launcher = (APP_ROOT / "run_portable.ps1").read_text(encoding="utf-8")
        qwen_install = "pip install qwen-tts==0.1.1 --no-deps"
        directml_install = (
            "pip install --force-reinstall --no-deps "
            "onnxruntime-directml==1.23.0"
        )

        self.assertIn(qwen_install, launcher)
        self.assertIn(directml_install, launcher)
        self.assertIn("setuptools==79.0.1 wheel==0.45.1", launcher)
        self.assertIn("-r requirements.txt --no-build-isolation", launcher)
        self.assertLess(launcher.index(qwen_install), launcher.index(directml_install))
        self.assertIn("assert 'DmlExecutionProvider' in ps", launcher)

    def test_launcher_protects_and_diagnoses_the_dependency_gate(self) -> None:
        launcher = (APP_ROOT / "run_portable.ps1").read_text(encoding="utf-8")
        kmp_assignment = '$env:KMP_DUPLICATE_LIB_OK = "TRUE"'
        dml_gate = "assert 'DmlExecutionProvider' in ps"

        self.assertLess(launcher.index(kmp_assignment), launcher.index(dml_gate))
        self.assertEqual(1, launcher.count(kmp_assignment))
        self.assertNotIn("--no-cache-dir", launcher)
        self.assertIn("The mirror refused this IP", launcher)
        self.assertIn("Configured package indexes were unreachable", launcher)
        self.assertIn("configured package indexes", launcher)
        self.assertIn("PackageNotFoundError|No package metadata was found", launcher)
        self.assertIn("Installing dependencies for the first time", launcher)
        self.assertIn("首次安装依赖", launcher)
        self.assertIn("Dependency check failed; details were saved", launcher)

    def test_launcher_isolates_pip_and_uses_explicit_index_fallback_chain(self) -> None:
        launcher = (APP_ROOT / "run_portable.ps1").read_text(encoding="utf-8")
        indexes = (
            "https://mirrors.aliyun.com/pypi/simple/",
            "https://pypi.tuna.tsinghua.edu.cn/simple/",
            "https://pypi.org/simple/",
        )

        self.assertLess(launcher.index(indexes[0]), launcher.index(indexes[1]))
        self.assertLess(launcher.index(indexes[1]), launcher.index(indexes[2]))
        pip_install_commands = re.findall(
            r"& \$Python -m pip install[^\r\n]+",
            launcher,
        )
        self.assertEqual(4, len(pip_install_commands))
        self.assertEqual(
            len(pip_install_commands),
            sum(command.count("--isolated") for command in pip_install_commands),
        )
        for command in pip_install_commands:
            with self.subTest(command=command):
                self.assertIn("--timeout 60", command)
                self.assertIn("@pipIndexArgs", command)

        pip_invocations = [
            line for line in launcher.splitlines() if "& $Python -m pip" in line
        ]
        self.assertTrue(pip_invocations)
        self.assertTrue(all("--isolated" in line for line in pip_invocations))
        get_pip_invocation = next(
            line for line in launcher.splitlines() if "& $Python $getPip" in line
        )
        self.assertIn("--isolated", get_pip_invocation)
        self.assertIn("--timeout 60", get_pip_invocation)
        self.assertNotIn("$pipArgs = @()", launcher)
        self.assertIn("BASHI_PIP_INDEX_URL", launcher)
        self.assertIn("(?i)403|Forbidden|denied by IP ACL", launcher)
        self.assertIn("$pipIndexUrls = @($officialPipIndexUrl)", launcher)
        self.assertIn("Get-PipIndexArguments -IndexUrl", launcher)
        self.assertIn("$uri.Host", launcher)
        self.assertIn("Detected user-level pip configuration", launcher)
        self.assertIn("已在本次安装中忽略", launcher)

    def test_pip_bootstrap_uses_the_index_chain_and_ascii_log_lines(self) -> None:
        launcher = (APP_ROOT / "run_portable.ps1").read_text(encoding="utf-8")
        ensure_start = launcher.index("function Ensure-Pip")
        ensure_end = launcher.index('\n}\n\nWrite-Host "====', ensure_start)
        ensure_pip = launcher[ensure_start:ensure_end]

        self.assertIn("$pipIndexUrls", ensure_pip)
        self.assertIn("for ($attempt = 1", ensure_pip)
        self.assertIn(
            "Get-PipIndexArguments -IndexUrl $currentPipIndexUrl",
            ensure_pip,
        )
        self.assertIn("@bootstrapPipIndexArgs", ensure_pip)
        self.assertNotIn("@pipIndexArgs", ensure_pip)
        self.assertIn("$pipBootstrapBackoffSeconds = @(2, 5)", ensure_pip)
        self.assertNotIn("$pipBackoffSeconds", ensure_pip)
        self.assertIn("try {", ensure_pip)
        self.assertIn("catch {", ensure_pip)
        self.assertIn("https://bootstrap.pypa.io/get-pip.py", ensure_pip)
        self.assertIn("BASHI_PIP_INDEX_URL", ensure_pip)

        lines = launcher.splitlines()
        log_write_statements = []
        for index, line in enumerate(lines):
            if "$LogFile" not in line or not re.search(
                r"(?:Add|Set)-Content",
                line,
            ):
                continue
            statement = line
            if index > 0 and lines[index - 1].rstrip().endswith("|"):
                statement = lines[index - 1] + "\n" + statement
            log_write_statements.append(statement)

        self.assertTrue(log_write_statements)
        for statement in log_write_statements:
            with self.subTest(statement=statement):
                self.assertNotRegex(statement, r"[^\x00-\x7F]")

    def test_launcher_python_c_snippets_use_ps51_safe_single_quotes(self) -> None:
        launcher = (APP_ROOT / "run_portable.ps1").read_text(encoding="utf-8")
        dependency_line = next(
            line for line in launcher.splitlines() if line.startswith("$dependencyCheckCode = ")
        )
        directml_line = next(
            line for line in launcher.splitlines() if "$directMlProbeCode = " in line
        )

        self.assertIn("'Flask'", dependency_line)
        self.assertIn("'DmlExecutionProvider'", dependency_line)
        self.assertIn("'DmlExecutionProvider'", directml_line)
        self.assertNotIn('"Flask"', dependency_line)
        self.assertNotIn('"DmlExecutionProvider"', dependency_line)
        self.assertNotIn('f"Missing DML', dependency_line)
        self.assertNotIn('"DmlExecutionProvider"', directml_line)
        self.assertIn("-c $dependencyCheckCode", launcher)
        self.assertIn("-c $directMlProbeCode", launcher)

    def test_launcher_checks_configured_port_before_starting_app(self) -> None:
        launcher = (APP_ROOT / "run_portable.ps1").read_text(encoding="utf-8")
        precheck_start = launcher.index("$existingAppUrl =")
        launcher_log_start = launcher.index("Privacy launcher started")
        app_start = launcher.index("('[STEP] Starting app.py")
        precheck = launcher[precheck_start:app_start]

        self.assertLess(precheck_start, launcher_log_start)
        self.assertLess(precheck_start, app_start)
        self.assertIn("Test-LocalPortListening -TargetPort $Port", precheck)
        self.assertIn('"http://127.0.0.1:$Port"', precheck)
        self.assertIn("Start-Process $existingAppUrl", precheck)
        self.assertIn("exit 0", precheck)
        self.assertNotIn("5050", precheck)

    def test_embed_precheck_has_independent_dml_provider_gate(self) -> None:
        precheck = (APP_ROOT / "scripts" / "precheck_py312_embed.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("02b-qwen-tts-no-deps.log", precheck)
        self.assertIn("02c-directml-force-reinstall.log", precheck)
        self.assertIn("01b-build-tooling.log", precheck)
        self.assertIn("--no-build-isolation", precheck)
        self.assertIn("04b-dml-provider-check.log", precheck)
        self.assertIn("'DmlExecutionProvider' in ps", precheck)
        self.assertIn("(gradio|onnxruntime)", precheck)
        self.assertLess(
            precheck.index('$env:KMP_DUPLICATE_LIB_OK = "TRUE"'),
            precheck.index('Invoke-Logged -Step "import smoke"'),
        )


if __name__ == "__main__":
    unittest.main()
