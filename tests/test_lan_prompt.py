import subprocess
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = APP_ROOT / "run_portable.ps1"
# The launcher ships for Windows PowerShell 5.1 (run_portable.bat starts it by
# name), so the extracted functions are exercised under that interpreter.
POWERSHELL = "powershell.exe"

# Silent console callbacks: the tests that only care about the returned host
# must not have the countdown and echo lines mixed into their captured output.
# The default callbacks are covered by their own test and by source assertions.
_SILENT_REMAINING = "-ReportRemaining { param([int]$Seconds) } "
_SILENT_CHOICE = "-ReportChoice { param([string]$Message) }"
_SILENT_CONSOLE = _SILENT_REMAINING + _SILENT_CHOICE


def _invoke(functions, expression: str) -> str:
    """Define the named launcher functions in Windows PowerShell 5.1 and run *expression*."""
    escaped_path = str(LAUNCHER).replace("'", "''")
    command = (
        "$tokens=$null; $errors=$null; "
        f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{escaped_path}', "
        "[ref]$tokens, [ref]$errors); "
    )
    for name in functions:
        command += (
            "$fn=$ast.Find({param($node) $node -is "
            "[System.Management.Automation.Language.FunctionDefinitionAst] -and "
            f"$node.Name -eq '{name}'}}, $true); "
            "Invoke-Expression $fn.Extent.Text; "
        )
    command += expression
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _invoke_lan_prompt(expression: str) -> str:
    return _invoke(("Read-LanBindHost",), expression)


class LanPromptTests(unittest.TestCase):
    def test_timeout_defaults_to_localhost(self) -> None:
        output = _invoke_lan_prompt(
            "Read-LanBindHost -TimeoutSeconds 0 "
            "-KeyAvailable { $false } -Wait { param($ms) } " + _SILENT_CONSOLE
        )

        self.assertEqual("127.0.0.1", output)

    def test_y_key_enables_lan_access(self) -> None:
        for key in ("Y", "y"):
            with self.subTest(key=key):
                output = _invoke_lan_prompt(
                    "Read-LanBindHost -TimeoutSeconds 20 "
                    "-KeyAvailable { $true } "
                    f"-ReadKey {{ '{key}' }} -Wait {{ param($ms) }} " + _SILENT_CONSOLE
                )
                self.assertEqual("0.0.0.0", output)

    def test_any_other_key_selects_localhost_immediately(self) -> None:
        for key in ("n", "N", "x", " "):
            with self.subTest(key=key):
                expression = (
                    "$script:choices=@(); "
                    "Read-LanBindHost -TimeoutSeconds 20 "
                    "-KeyAvailable { $true } "
                    f"-ReadKey {{ '{key}' }} -Wait {{ param($ms) }} "
                    + _SILENT_REMAINING
                    + "-ReportChoice { param([string]$Message) $script:choices += $Message } "
                    "| Out-Null; $script:choices -join '|'"
                )
                output = _invoke_lan_prompt(expression)

                self.assertEqual("已选择：仅本机（按键）", output)

    def test_console_error_defaults_to_localhost(self) -> None:
        output = _invoke_lan_prompt(
            "Read-LanBindHost -TimeoutSeconds 20 "
            "-KeyAvailable { throw 'no console' } -Wait { param($ms) } " + _SILENT_CONSOLE
        )

        self.assertEqual("127.0.0.1", output)

    def test_default_callbacks_draw_the_countdown_and_the_echo(self) -> None:
        output = _invoke_lan_prompt(
            "Read-LanBindHost -TimeoutSeconds 0 "
            "-KeyAvailable { $false } -Wait { param($ms) }"
        )

        self.assertIn(
            "按 Y 允许局域网访问；按其他任意键立即选择仅本机（剩余 0 秒）", output
        )
        self.assertIn("已选择：仅本机（超时默认）", output)
        self.assertEqual("127.0.0.1", output.splitlines()[-1])

    def test_timeout_echo_says_the_default_was_used(self) -> None:
        expression = (
            "$script:choices=@(); "
            "Read-LanBindHost -TimeoutSeconds 0 "
            "-KeyAvailable { $false } -Wait { param($ms) } "
            + _SILENT_REMAINING
            + "-ReportChoice { param([string]$Message) $script:choices += $Message } "
            "| Out-Null; $script:choices -join '|'"
        )

        self.assertEqual("已选择：仅本机（超时默认）", _invoke_lan_prompt(expression))

    def test_y_echo_says_lan_access_was_chosen(self) -> None:
        expression = (
            "$script:choices=@(); "
            "Read-LanBindHost -TimeoutSeconds 20 "
            "-KeyAvailable { $true } -ReadKey { 'Y' } -Wait { param($ms) } "
            + _SILENT_REMAINING
            + "-ReportChoice { param([string]$Message) $script:choices += $Message } "
            "| Out-Null; $script:choices -join '|'"
        )

        self.assertEqual("已选择：允许局域网访问", _invoke_lan_prompt(expression))

    def test_countdown_reports_every_second_from_the_full_timeout(self) -> None:
        expression = (
            "$script:clock=[datetime]'2026-01-01T00:00:00'; $script:seen=@(); "
            "Read-LanBindHost -TimeoutSeconds 20 "
            "-KeyAvailable { $false } "
            "-Wait { param([int]$Milliseconds) $script:clock = $script:clock.AddMilliseconds($Milliseconds) } "
            "-Now { $script:clock } "
            "-ReportRemaining { param([int]$Seconds) $script:seen += $Seconds } "
            + _SILENT_CHOICE
            + " "
            "| Out-Null; $script:seen -join ','"
        )
        seen = [int(value) for value in _invoke_lan_prompt(expression).split(",")]

        self.assertEqual(20, seen[0])
        self.assertEqual(sorted(seen, reverse=True), seen)
        # One line per second, starting at the full timeout.
        self.assertEqual(list(range(20, -1, -1)), seen)

    def test_launcher_asks_with_the_twenty_second_countdown_prompt(self) -> None:
        source = LAUNCHER.read_text(encoding="utf-8")

        self.assertIn("[int]$TimeoutSeconds = 20", source)
        self.assertNotIn("[int]$TimeoutSeconds = 10", source)
        self.assertIn("$BindHost = Read-LanBindHost", source)
        self.assertNotIn('Read-Host "Select / 请选择 [y/N]"', source)
        self.assertIn("按 Y 允许局域网访问；按其他任意键立即选择仅本机（剩余 {0} 秒）", source)


class LanPromptWarningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = LAUNCHER.read_text(encoding="utf-8")

    def test_bilingual_warning_is_printed_before_the_choice(self) -> None:
        warning_index = self.source.index("[!] WARNING / 警告")
        prompt_index = self.source.index("$BindHost = Read-LanBindHost")

        self.assertLess(warning_index, prompt_index)

    def test_question_is_last_and_sits_next_to_the_input(self) -> None:
        warning_index = self.source.index("[!] WARNING / 警告")
        question_index = self.source.index(
            "DO YOU WANT TO ALLOW OTHER DEVICES ON YOUR NETWORK TO ACCESS THIS SERVER?"
        )
        prompt_index = self.source.index("$BindHost = Read-LanBindHost")

        self.assertLess(warning_index, question_index)
        self.assertLess(question_index, prompt_index)

        between = self.source[question_index:prompt_index]
        self.assertIn("[Y] Yes", between)
        self.assertIn("[N] No", between)
        self.assertIn("any other key selects it immediately", between)
        self.assertNotIn("WARNING", between)

    def test_warning_covers_reach_and_pin_and_trust(self) -> None:
        for fragment in (
            "Anyone who can reach this port on your network can open this app.",
            "任何能访问该端口的设备都可以打开本程序。",
            "A one-time PIN will be shown in the console",
            "控制台会显示一次性 PIN",
            "Only enable this on a network you trust.",
            "请仅在信任的网络上开启。",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.source)


class LanBindModeTests(unittest.TestCase):
    def test_mode_classification(self) -> None:
        cases = (
            ("127.0.0.1", "Local"),
            ("127.0.0.2", "Local"),
            ("::1", "Local"),
            ("localhost", "Local"),
            ("0.0.0.0", "Network"),
            ("192.168.1.23", "Specific"),
            ("::", "Unsupported"),
            ("fe80::1", "Unsupported"),
            ("2001:db8::1", "Unsupported"),
            ("mypc.local", "Unsupported"),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                output = _invoke(
                    ("Get-BindHostMode",), f"Get-BindHostMode -BindHost '{value}'"
                )
                self.assertEqual(expected, output)

    def test_display_host_three_branches(self) -> None:
        cases = (
            ("127.0.0.1", "", "127.0.0.1"),
            ("0.0.0.0", "10.0.0.5", "10.0.0.5"),
            ("0.0.0.0", "", "YOUR_LOCAL_IP"),
            ("192.168.1.23", "10.0.0.5", "192.168.1.23"),
        )
        for bind_host, detected, expected in cases:
            with self.subTest(bind_host=bind_host, detected=detected):
                output = _invoke(
                    ("Get-BindHostMode", "Get-BindHostDisplayHost"),
                    "Get-BindHostDisplayHost -BindHost '{0}' -DetectedLanIp '{1}'"
                    .format(bind_host, detected),
                )
                self.assertEqual(expected, output)

    def test_launcher_displays_the_resolved_host_not_a_hardcoded_loopback(self) -> None:
        source = LAUNCHER.read_text(encoding="utf-8")

        self.assertIn("$bindMode = Get-BindHostMode -BindHost $BindHost", source)
        self.assertIn(
            "$displayHost = Get-BindHostDisplayHost -BindHost $BindHost "
            "-DetectedLanIp $detectedLanIp",
            source,
        )
        self.assertIn('Write-Host "http://${displayHost}:$Port"', source)

        network_branch = source.index("if ($bindMode -eq 'Local') {")
        self.assertIn('Write-Host "http://127.0.0.1:$Port"', source[network_branch:])


if __name__ == "__main__":
    unittest.main()
