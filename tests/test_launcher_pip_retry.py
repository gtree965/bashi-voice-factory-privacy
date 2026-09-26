"""S4 on the launcher side.

Everything here runs the launcher's own text under Windows PowerShell 5.1:
the functions are extracted by AST, the pip command is replaced by a stub that
always fails, and the waits are recorded instead of slept. The retry loop, the
fallback order and the masking are the real code from run_portable.ps1.
"""

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = APP_ROOT / "run_portable.ps1"
POWERSHELL = "powershell.exe"

FUNCTIONS = (
    "Get-PipIndexArguments",
    "Get-PipIndexDisplayUrl",
    "Test-PipProbeEligible",
    "Invoke-NativeCommand",
    "ConvertTo-NativeOutputLine",
    "Invoke-NativeCommandCapture",
    "Invoke-PipMirrorProbeProcess",
    "Get-PipRankedPipIndexUrls",
)
VARIABLES = (
    "$pipBackoffSeconds",
    "$pipMirrorIndexUrls",
    "$chinaPipIndexUrls",
    "$officialPipIndexUrl",
    "$pipMirrorProbeCache",
)
# The whole retry loop, its failure message and the exit: from the point where
# the ranked list is resolved to the line before the dependency-ready stamp.
INSTALL_BLOCK_START = "$installPipIndexUrls = @(Get-PipRankedPipIndexUrls"
INSTALL_BLOCK_END = "$env:BASHI_DEPS_READY_EPOCH"
OVERRIDE_BLOCK_START = "$timeZone = (Get-TimeZone).Id"
OVERRIDE_BLOCK_END = "$pipProbeEligible = Test-PipProbeEligible"

READ_HOST_STUB = "function Read-Host { param([string]$Prompt = '') return '' }"
PROBE_VARIABLES = ("$pipMirrorIndexUrls", "$chinaPipIndexUrls", "$pipMirrorProbeCache")
PROBE_STUB = (
    "function Get-PipRankedPipIndexUrls {"
    " param([Parameter(Mandatory = $true)][string[]]$FallbackUrls,"
    " [Parameter(Mandatory = $true)][bool]$ProbeEligible,"
    " [int]$ProbeTimeoutSeconds = 15)"
    " return @($FallbackUrls) }"
)


def _launcher_source() -> str:
    return LAUNCHER.read_text(encoding="utf-8")


def _slice(start_marker: str, end_marker: str) -> str:
    source = _launcher_source()
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


def _override_block() -> str:
    """The locale/override index selection, including the probe eligibility flag."""
    source = _launcher_source()
    start = source.index(OVERRIDE_BLOCK_START)
    end = source.index("\nEnsure-Pip", start)
    return source[start:end]


def _install_block() -> str:
    """The real retry loop with balanced braces.

    The loop lives inside the dependency gate's else block, so the slice stops
    one line short of the brace that closes that block.
    """
    source = _launcher_source()
    start = source.index(INSTALL_BLOCK_START)
    end = source.index("\n}\n\n" + INSTALL_BLOCK_END, start)
    return source[start:end]


def _parser_setup() -> str:
    escaped = str(LAUNCHER).replace("'", "''")
    return (
        "$tokens=$null; $errors=$null\n"
        "$ast=[System.Management.Automation.Language.Parser]::ParseFile("
        "'%s', [ref]$tokens, [ref]$errors)" % escaped
    )


def _function_definitions(names) -> str:
    lines = [_parser_setup()]
    for name in names:
        lines.append(
            "$fn=$ast.Find({param($node) $node -is "
            "[System.Management.Automation.Language.FunctionDefinitionAst] -and "
            "$node.Name -eq '%s'}, $true); Invoke-Expression $fn.Extent.Text" % name
        )
    return "\n".join(lines)


def _variable_definitions(names) -> str:
    lines = []
    for name in names:
        lines.append(
            "$assignment=$ast.Find({param($node) $node -is "
            "[System.Management.Automation.Language.AssignmentStatementAst] -and "
            "$node.Left.Extent.Text -eq '%s'}, $true); "
            "Invoke-Expression $assignment.Extent.Text" % name
        )
    return "\n".join(lines)


def _run_harness(script: str, timeout: float = 180):
    with tempfile.TemporaryDirectory() as directory:
        script_path = Path(directory) / "harness.ps1"
        script_path.write_text(script, encoding="utf-8-sig")
        started = time.monotonic()
        result = subprocess.run(
            [
                POWERSHELL,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
            ],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
        elapsed = time.monotonic() - started
    return result, elapsed


def _variable_json(name: str):
    result, _elapsed = _run_harness(
        "\n".join(
            [
                _parser_setup(),
                _variable_definitions((name,)),
                "%s | ConvertTo-Json -Compress" % name,
            ]
        )
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip())


def _chain_and_catalog():
    """The mirror catalog and the fixed Chinese chain, read out of the launcher."""
    result, _elapsed = _run_harness(
        "\n".join(
            [
                _parser_setup(),
                _variable_definitions(PROBE_VARIABLES),
                "[pscustomobject]@{ catalog = $pipMirrorIndexUrls; chain = $chinaPipIndexUrls } "
                "| ConvertTo-Json -Compress",
            ]
        )
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip())
    return payload["catalog"], payload["chain"]


def _china_chain():
    """The fixed Chinese chain, read out of the launcher itself."""
    return _chain_and_catalog()[1]


def _write_fake_python(directory: Path) -> Path:
    path = directory / "fake_python.cmd"
    path.write_text("@echo off\r\nexit /b 1\r\n", encoding="ascii")
    return path


def _read_lines(path: Path):
    if not path.exists():
        return []
    # utf-8-sig: Add-Content -Encoding utf8 writes a BOM on a new file.
    return [
        line for line in path.read_text(encoding="utf-8-sig").splitlines() if line
    ]


def _emitted_values(result):
    """The ';'-joined list the harness printed last, after any console lines."""
    return result.stdout.strip().splitlines()[-1].split(";")


def _install_harness(directory: Path, index_urls) -> str:
    """Script that runs the real install retry loop with a failing pip."""
    waits = directory / "waits.txt"
    log = directory / "launch_log.txt"
    urls = ", ".join("'%s'" % url for url in index_urls)
    return "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            _function_definitions(FUNCTIONS),
            _variable_definitions(VARIABLES),
            "function Start-Sleep {",
            "    param([Parameter(Position = 0)]$Seconds = 0, [int]$Milliseconds = 0)",
            "    $type = 'null'",
            "    if ($null -ne $Seconds) { $type = $Seconds.GetType().Name }",
            "    Add-Content -LiteralPath '%s' -Encoding utf8 "
            "-Value ('{0}|{1}' -f $type, $Seconds)" % waits,
            "}",
            READ_HOST_STUB,
            PROBE_STUB,
            "$AppRoot = '%s'" % directory,
            "$LogFile = '%s'" % log,
            "$Python = '%s'" % _write_fake_python(directory),
            "$pipIndexUrls = @(%s)" % urls,
            # The ranking itself is not under test here; the loop is.
            "$pipProbeEligible = $false",
            _install_block(),
        ]
    )


class FiveSourceRetryTests(unittest.TestCase):
    def test_five_sources_are_tried_once_each_with_a_non_empty_wait(self) -> None:
        china_chain = _china_chain()
        self.assertEqual(5, len(china_chain))

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            script = _install_harness(directory, china_chain)
            result, _elapsed = _run_harness(script)

            waits = _read_lines(directory / "waits.txt")
            log = _read_lines(directory / "launch_log.txt")

        self.assertEqual(1, result.returncode)
        for attempt in range(1, 6):
            self.assertIn(
                "[INFO] Dependency index attempt %d/5" % attempt, result.stdout
            )
        self.assertEqual(
            ["Int32|5", "Int32|30", "Int32|30", "Int32|30"],
            waits,
            "a wait was empty, non-integer or missing",
        )
        for url in china_chain:
            with self.subTest(url=url):
                self.assertEqual(
                    1,
                    sum(1 for line in log if line.endswith(": " + url)),
                    "each source must be used exactly once",
                )
        self.assertIn(
            "pip install failed across the configured package indexes", result.stdout
        )

    def test_a_single_source_is_retried_three_times(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            script = _install_harness(directory, ["https://pypi.org/simple/"])
            result, _elapsed = _run_harness(script)

            waits = _read_lines(directory / "waits.txt")
            log = _read_lines(directory / "launch_log.txt")

        self.assertEqual(1, result.returncode)
        self.assertIn("[INFO] Dependency index attempt 1/3", result.stdout)
        self.assertIn("[INFO] Dependency index attempt 3/3", result.stdout)
        self.assertNotIn("attempt 4/3", result.stdout)
        self.assertEqual(["Int32|5", "Int32|30"], waits)
        self.assertEqual(
            3,
            sum(1 for line in log if line.endswith(": https://pypi.org/simple/")),
        )


class CredentialMaskingTests(unittest.TestCase):
    SECRET_URL = "https://someuser:s3cret-token@127.0.0.1:9/simple/"

    def test_override_credentials_never_reach_the_console_or_the_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            log_path = directory / "launch_log.txt"
            script = "\n".join(
                [
                    "$ErrorActionPreference = 'Stop'",
                    _function_definitions(FUNCTIONS),
                    _variable_definitions(VARIABLES),
                    "function Start-Sleep { param([Parameter(Position = 0)]"
                    "$Seconds = 0, [int]$Milliseconds = 0) }",
                    READ_HOST_STUB,
                    PROBE_STUB,
                    "$AppRoot = '%s'" % directory,
                    "$LogFile = '%s'" % log_path,
                    "$Python = '%s'" % _write_fake_python(directory),
                    "$env:BASHI_PIP_INDEX_URL = '%s'" % self.SECRET_URL,
                    _override_block(),
                    _install_block(),
                ]
            )
            result, _elapsed = _run_harness(script)

            log_text = log_path.read_text(encoding="utf-8")

        self.assertEqual(1, result.returncode)
        self.assertIn("https://***@127.0.0.1:9/simple/", result.stdout)
        self.assertIn("https://***@127.0.0.1:9/simple/", log_text)
        for text in (result.stdout, result.stderr, log_text):
            self.assertNotIn("s3cret-token", text)
            self.assertNotIn("someuser", text)

    def test_display_url_keeps_host_port_and_path_but_drops_user_info(self) -> None:
        cases = (
            (
                "https://mirrors.aliyun.com/pypi/simple/",
                "https://mirrors.aliyun.com/pypi/simple/",
            ),
            (
                "https://user:pass@example.com:8443/pypi/simple/",
                "https://***@example.com:8443/pypi/simple/",
            ),
            ("http://user@example.com/simple/", "http://***@example.com/simple/"),
            ("not a url", "<unparsable index URL>"),
        )
        for raw, expected in cases:
            with self.subTest(raw=raw):
                result, _elapsed = _run_harness(
                    "\n".join(
                        [
                            "$ErrorActionPreference = 'Stop'",
                            _function_definitions(("Get-PipIndexDisplayUrl",)),
                            "Get-PipIndexDisplayUrl -IndexUrl '%s'" % raw,
                        ]
                    )
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(expected, result.stdout.strip())


class ProbeEligibilityTests(unittest.TestCase):
    def test_only_the_built_in_chinese_chain_is_probed(self) -> None:
        cases = (
            ("", "China Standard Time", "zh-CN", "True"),
            ("", "UTC", "zh-CN", "True"),
            ("", "China Standard Time", "en-US", "True"),
            ("", "UTC", "en-US", "False"),
            ("", "Pacific Standard Time", "en-GB", "False"),
            ("https://example.invalid/simple/", "China Standard Time", "zh-CN", "False"),
        )
        for override, time_zone, culture, expected in cases:
            with self.subTest(time_zone=time_zone, culture=culture, override=override):
                result, _elapsed = _run_harness(
                    "\n".join(
                        [
                            "$ErrorActionPreference = 'Stop'",
                            _function_definitions(("Test-PipProbeEligible",)),
                            "Test-PipProbeEligible -Override '%s' -TimeZoneId '%s' "
                            "-CultureName '%s'" % (override, time_zone, culture),
                        ]
                    )
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(expected, result.stdout.strip())


class ProbeRankingTests(unittest.TestCase):
    def _ranking_harness(
        self, directory: Path, probe_lines, exit_code: int = 0, eligible="True"
    ) -> str:
        app_root = directory / "app"
        app_root.mkdir(exist_ok=True)
        (app_root / "mirror_probe.py").write_text("", encoding="utf-8")
        lines = ", ".join("'%s'" % line for line in probe_lines)
        return "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                _function_definitions(FUNCTIONS),
                _variable_definitions(PROBE_VARIABLES),
                "function Invoke-PipMirrorProbeProcess {",
                "    param([Parameter(Mandatory = $true)][string]$ScriptPath,"
                " [int]$TimeoutSeconds = 15)",
                "    Add-Content -LiteralPath '%s' -Encoding utf8 -Value 'called'"
                % (directory / "probe_calls.txt"),
                "    return [pscustomobject]@{ TimedOut = $false; ExitCode = %d; "
                "Lines = @(%s) }" % (exit_code, lines),
                "}",
                "$AppRoot = '%s'" % app_root,
                "$LogFile = '%s'" % (directory / "launch_log.txt"),
                "$result = Get-PipRankedPipIndexUrls -FallbackUrls $chinaPipIndexUrls "
                "-ProbeEligible $%s" % eligible,
                "$result -join ';'",
            ]
        )

    def test_successful_ranking_reorders_the_chain_and_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            script = self._ranking_harness(
                directory,
                [
                    "[mirror-probe] pypi ok 0.42s",
                    "[mirror-probe] aliyun timeout",
                    "[mirror-probe] rank pypi,aliyun,tuna,tencent,huawei",
                ],
            )
            script += (
                "\n$second = Get-PipRankedPipIndexUrls -FallbackUrls $chinaPipIndexUrls "
                "-ProbeEligible $true\n$second -join ';'"
            )
            result, _elapsed = _run_harness(script)

            calls = _read_lines(directory / "probe_calls.txt")
            log_text = (directory / "launch_log.txt").read_text(encoding="utf-8")

        self.assertEqual(0, result.returncode, result.stderr)
        first, second = result.stdout.strip().splitlines()[-2:]
        self.assertTrue(first.startswith("https://pypi.org/simple/;"))
        self.assertIn("https://mirrors.aliyun.com/pypi/simple/", first)
        self.assertEqual(first, second, "the second call must reuse the ranking")
        self.assertEqual(1, len(calls), "the probe must run at most once per launch")
        self.assertIn("[mirror-probe] rank pypi,aliyun,tuna,tencent,huawei", log_text)
        self.assertIn("Testing the package mirrors before downloading", result.stdout)

    def test_output_without_a_ranking_line_falls_back_to_the_fixed_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            script = self._ranking_harness(directory, ["[mirror-probe] pypi ok 0.42s"])
            result, _elapsed = _run_harness(script)

            log_text = (directory / "launch_log.txt").read_text(encoding="utf-8")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(_china_chain(), _emitted_values(result))
        self.assertIn("had no ranking", log_text)

    def test_probe_that_finds_no_usable_mirror_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            script = self._ranking_harness(
                directory,
                [
                    "[mirror-probe] aliyun timeout",
                    "[mirror-probe] tuna timeout",
                    "[mirror-probe] rank aliyun,tuna,tencent,huawei,pypi",
                ],
                exit_code=1,
            )
            result, _elapsed = _run_harness(script)

            log_text = (directory / "launch_log.txt").read_text(encoding="utf-8")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(_china_chain(), _emitted_values(result))
        self.assertIn("found no usable mirror", log_text)

    def test_missing_probe_script_falls_back_without_running_anything(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            empty_root = directory / "empty"
            empty_root.mkdir()
            script = "\n".join(
                [
                    "$ErrorActionPreference = 'Stop'",
                    _function_definitions(FUNCTIONS),
                    _variable_definitions(PROBE_VARIABLES),
                    "$AppRoot = '%s'" % empty_root,
                    "$LogFile = '%s'" % (directory / "launch_log.txt"),
                    "$result = Get-PipRankedPipIndexUrls -FallbackUrls "
                    "$chinaPipIndexUrls -ProbeEligible $true",
                    "$result -join ';'",
                ]
            )
            result, _elapsed = _run_harness(script)

            log_text = (directory / "launch_log.txt").read_text(encoding="utf-8")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(_china_chain(), result.stdout.strip().split(";"))
        self.assertIn("mirror_probe.py is missing", log_text)

    def test_ineligible_run_never_starts_the_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            empty_root = directory / "empty"
            empty_root.mkdir()
            script = "\n".join(
                [
                    "$ErrorActionPreference = 'Stop'",
                    _function_definitions(FUNCTIONS),
                    _variable_definitions(PROBE_VARIABLES),
                    "$AppRoot = '%s'" % empty_root,
                    "$LogFile = '%s'" % (directory / "launch_log.txt"),
                    # A path that cannot be started: if the probe ran, the
                    # process start would throw and this script would fail.
                    "$Python = 'Z:\\does\\not\\exist\\python.exe'",
                    "$result = Get-PipRankedPipIndexUrls -FallbackUrls "
                    "$chinaPipIndexUrls -ProbeEligible $false",
                    "$result -join ';'",
                ]
            )
            result, _elapsed = _run_harness(script)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(_china_chain(), result.stdout.strip().split(";"))
        self.assertNotIn("Testing the package mirrors", result.stdout)


class ProbeHardLimitTests(unittest.TestCase):
    def test_a_probe_that_never_exits_is_killed_and_the_fixed_order_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            app_root = directory / "app"
            app_root.mkdir()
            (app_root / "mirror_probe.py").write_text(
                "import time\ntime.sleep(600)\n", encoding="utf-8"
            )
            script = "\n".join(
                [
                    "$ErrorActionPreference = 'Stop'",
                    _function_definitions(FUNCTIONS),
                    _variable_definitions(PROBE_VARIABLES),
                    "$AppRoot = '%s'" % app_root,
                    "$LogFile = '%s'" % (directory / "launch_log.txt"),
                    "$Python = '%s'" % sys.executable,
                    "$result = Get-PipRankedPipIndexUrls -FallbackUrls "
                    "$chinaPipIndexUrls -ProbeEligible $true",
                    "$result -join ';'",
                ]
            )
            result, elapsed = _run_harness(script)

            log_text = (directory / "launch_log.txt").read_text(encoding="utf-8")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(_china_chain(), _emitted_values(result))
        self.assertIn("mirror probe timed out", log_text)
        self.assertIn("did not finish in time", result.stdout)
        self.assertLess(elapsed, 25.0, "harness took %.1fs" % elapsed)
        self.assertGreaterEqual(elapsed, 14.0, "harness took %.1fs" % elapsed)


class ProbeWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = _launcher_source()

    def test_probe_is_called_at_both_install_entry_points_only(self) -> None:
        self.assertEqual(
            2,
            self.source.count("Get-PipRankedPipIndexUrls -FallbackUrls"),
            "expected exactly two call sites: the pip bootstrap and the install",
        )
        early_return = self.source.index(
            "$pipCheckExit = Invoke-NativeCommand { & $Python -m pip --version --isolated"
        )
        bootstrap_call = self.source.index(
            "$bootstrapPipIndexUrls = @(Get-PipRankedPipIndexUrls -FallbackUrls"
        )
        dependency_gate = self.source.index(
            "$dependencyCheck = Invoke-NativeCommandCapture"
        )
        install_call = self.source.index(
            "$installPipIndexUrls = @(Get-PipRankedPipIndexUrls -FallbackUrls"
        )

        self.assertLess(early_return, bootstrap_call)
        self.assertLess(bootstrap_call, self.source.index("\nEnsure-Pip\n"))
        self.assertLess(dependency_gate, install_call)

    def test_attempt_counts_are_derived_from_the_source_list(self) -> None:
        self.assertIn(
            "$pipBootstrapMaxAttempts = [Math]::Max(3, $bootstrapPipIndexUrls.Count)",
            self.source,
        )
        self.assertIn(
            "$pipMaxAttempts = [Math]::Max(3, $installPipIndexUrls.Count)",
            self.source,
        )
        self.assertIn(
            "$pipBackoffSeconds[[Math]::Min($attempt - 2, $pipBackoffSeconds.Count - 1)]",
            self.source,
        )
        self.assertIn(
            "$pipBootstrapBackoffSeconds[[Math]::Min($attempt - 2, "
            "$pipBootstrapBackoffSeconds.Count - 1)]",
            self.source,
        )

    def test_backoff_lists_cover_every_attempt(self) -> None:
        self.assertEqual([5, 30, 30, 30], _variable_json("$pipBackoffSeconds"))

        result, _elapsed = _run_harness(
            "\n".join(
                [
                    _function_definitions(("Ensure-Pip",)),
                    "$body = $fn.Extent.Text",
                    "($body -split \"`n\" | Where-Object { $_ -match "
                    "'pipBootstrapBackoffSeconds = @' }) -join ''",
                ]
            )
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("@(2, 5, 10, 10)", result.stdout)

    def test_catalog_and_probe_candidates_agree(self) -> None:
        catalog, chain = _chain_and_catalog()
        sys.path.insert(0, str(APP_ROOT))
        try:
            import mirror_probe
        finally:
            sys.path.pop(0)

        self.assertEqual(
            catalog,
            {
                candidate.name: candidate.index_url
                for candidate in mirror_probe.DEFAULT_CANDIDATES
            },
        )
        self.assertEqual(list(catalog.values()), chain)


if __name__ == "__main__":
    unittest.main()
