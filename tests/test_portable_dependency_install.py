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
        self.assertNotIn("Start-Process", launcher)
        self.assertIn("Add-Content -Path $LogFile", precheck)
        self.assertIn("launcher exited early", precheck)
        self.assertIn("[Globalization.CultureInfo]::InvariantCulture", precheck)
        early_log_line = next(
            line for line in precheck.splitlines() if "$earlyExitLogLine =" in line
        )
        self.assertTrue(early_log_line.isascii())
        self.assertIn('Read-Host "Press Enter to exit / 按回车退出"', precheck)
        self.assertIn("exit 0", precheck)
        self.assertNotIn("5050", precheck)

    def test_launcher_rebuilds_portable_pth_entries_without_absolute_paths(self) -> None:
        launcher = (APP_ROOT / "run_portable.ps1").read_text(encoding="utf-8")
        function_start = launcher.index("function Set-PortablePthEntries")
        function_end = launcher.index("function Configure-EmbeddedPython", function_start)
        pth_rewrite = launcher[function_start:function_end]

        self.assertNotIn("GetFullPath", pth_rewrite)
        self.assertIn("'^[A-Za-z]:\\\\'", pth_rewrite)
        self.assertIn("'^\\\\\\\\'", pth_rewrite)
        self.assertIn('".."', pth_rewrite)
        self.assertIn(
            '"..\\..\\vulkan_backend_spike\\Qwen3-TTS-GGUF"',
            pth_rewrite,
        )
        self.assertIn("bashi-privacy-app|Qwen3-TTS-GGUF", pth_rewrite)
        self.assertIn("Set-PortablePthEntries", launcher)

    def test_launcher_exit_prompt_keeps_read_host_without_batch_confirmation(self) -> None:
        launcher = (APP_ROOT / "run_portable.ps1").read_text(encoding="utf-8")
        finalizer_start = launcher.index("finally {", launcher.index("$exitCode = -1"))
        finalizer = launcher[finalizer_start:]

        self.assertIn('Read-Host "Press Enter to exit / 按回车退出"', finalizer)
        self.assertNotIn("Terminate batch job", finalizer)

    def test_batch_launcher_hands_off_to_a_separate_powershell_console(self) -> None:
        launcher = (APP_ROOT / "run_portable.bat").read_text(encoding="ascii")

        self.assertNotRegex(launcher, r"[^\x00-\x7F]")
        self.assertIn('start "Bashi Voice Factory" powershell.exe', launcher)
        self.assertNotIn('start ""', launcher)
        self.assertIn('-File "%SCRIPT_DIR%run_portable.ps1" %*', launcher)
        self.assertIn("if errorlevel 1 (", launcher)
        self.assertEqual(1, launcher.splitlines().count("    pause"))
        self.assertIn("Could not start PowerShell", launcher)
        self.assertIn("pre-UTF-8 launcher ASCII-only", launcher)
        self.assertIn("not a child that starts and immediately exits", launcher)
        self.assertIn("exit /b 0", launcher)
        self.assertNotIn("< nul", launcher)

    def test_gguf_runtime_path_is_promoted_and_source_checked(self) -> None:
        engine = (APP_ROOT / "local_tts_engine_gguf.py").read_text(encoding="utf-8")

        self.assertNotIn("if str(GGUF_DIR) not in sys.path", engine)
        self.assertIn("sys.path.insert(0, gguf_dir)", engine)
        self.assertIn('sys.modules.get("qwen3_tts_gguf")', engine)
        self.assertIn('getattr(runtime_module, "__file__", None)', engine)
        self.assertIn("Runtime source mismatch", engine)

    def test_build_rejects_polluted_staged_python_pth(self) -> None:
        build = (APP_ROOT / "scripts" / "build_portable_zip.ps1").read_text(
            encoding="utf-8"
        )
        gate_start = build.index("function Assert-PortablePthClean")
        gate_end = build.index("function Stage-Package", gate_start)
        gate = build[gate_start:gate_end]

        self.assertIn("python312._pth", gate)
        self.assertIn("'^[A-Za-z]:\\\\'", gate)
        self.assertIn("'^\\\\\\\\'", gate)
        self.assertIn("'(?i)dist'", gate)
        self.assertIn("$forbiddenEntries -join", gate)
        self.assertIn("Assert-PortablePthClean -AppDest $appDest", build)

    def test_build_gates_staged_style_previews_against_git_index(self) -> None:
        build = (APP_ROOT / "scripts" / "build_portable_zip.ps1").read_text(
            encoding="utf-8"
        )
        gate_start = build.index("function Assert-StagedStylePreviewsMatchGit")
        gate_end = build.index("function Stage-Package", gate_start)
        gate = build[gate_start:gate_end]

        self.assertIn('Get-ChildItem -LiteralPath $stagedRoot -Recurse -Force -File', gate)
        self.assertIn(
            '& git -C $AppRoot ls-files -- "static/audio/style_previews/**"', gate
        )
        self.assertIn("ToLowerInvariant()", gate)
        self.assertIn('Replace("\\", "/")', gate)
        self.assertIn("Unexpected staged files (not tracked by git):", gate)
        self.assertIn("Tracked files missing from staging:", gate)

        copy_index = build.index('"static\\audio\\style_previews"')
        call_index = build.index(
            "Assert-StagedStylePreviewsMatchGit -AppDest $appDest", copy_index
        )
        compress_index = build.index("function Compress-StagedPackage", call_index)
        self.assertLess(copy_index, call_index)
        self.assertLess(call_index, compress_index)

    def test_build_ships_the_bilingual_readmes_only_at_the_package_root(self) -> None:
        build = (APP_ROOT / "scripts" / "build_portable_zip.ps1").read_text(
            encoding="utf-8"
        )
        docs_start = build.index('foreach ($name in @("README.md", "README_CN.md"))')
        docs_end = build.index('foreach ($name in @("LICENSE", "VERSION"))', docs_start)
        docs_block = build[docs_start:docs_end]

        self.assertIn("Join-Path $StageRoot $name", docs_block)
        # The cross-link line at the top of each README only resolves when both
        # files sit side by side, so a second copy inside bashi-privacy-app/ was
        # duplication with a broken switcher. It must not come back.
        self.assertNotIn("Join-Path $appDest $name", docs_block)

        app_files_start = build.index("$appFiles = @(")
        app_files = build[app_files_start:build.index(")", app_files_start)]
        self.assertNotIn('"README.md"', app_files)
        # VERSION is read at runtime by tts_routes._read_app_version(); dropping
        # it as "another duplicate" would silently blank the reported version.
        self.assertIn('"VERSION"', app_files)

    def test_repository_python_pth_files_have_no_absolute_or_dist_entries(self) -> None:
        pth_files = [
            path
            for path in APP_ROOT.rglob("python312._pth")
            if ".tmp" not in path.parts and ".venv" not in path.parts
        ]

        for path in pth_files:
            with self.subTest(path=path):
                for line in path.read_text(encoding="ascii").splitlines():
                    if line.lstrip().startswith("#"):
                        continue
                    self.assertNotRegex(line, r"^[A-Za-z]:\\")
                    self.assertNotRegex(line, r"^\\\\")
                    self.assertNotRegex(line, r"(?i)dist")

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
