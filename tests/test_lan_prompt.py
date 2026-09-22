import subprocess
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = APP_ROOT / "run_portable.ps1"


def _invoke(functions, expression: str) -> str:
    """Define the named launcher functions in a bare pwsh and run *expression*."""
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
        ["pwsh", "-NoProfile", "-Command", command],
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
            "-KeyAvailable { $false } -Wait { param($ms) }"
        )

        self.assertEqual("127.0.0.1", output)

    def test_y_key_enables_lan_access(self) -> None:
        for key in ("Y", "y"):
            with self.subTest(key=key):
                output = _invoke_lan_prompt(
                    "Read-LanBindHost -TimeoutSeconds 10 "
                    "-KeyAvailable { $true } "
                    f"-ReadKey {{ '{key}' }} -Wait {{ param($ms) }}"
                )
                self.assertEqual("0.0.0.0", output)

    def test_console_error_defaults_to_localhost(self) -> None:
        output = _invoke_lan_prompt(
            "Read-LanBindHost -TimeoutSeconds 10 "
            "-KeyAvailable { throw 'no console' } -Wait { param($ms) }"
        )

        self.assertEqual("127.0.0.1", output)

    def test_launcher_uses_ten_second_prompt_without_read_host(self) -> None:
        source = LAUNCHER.read_text(encoding="utf-8")

        self.assertIn("[int]$TimeoutSeconds = 10", source)
        self.assertIn("$BindHost = Read-LanBindHost", source)
        self.assertNotIn('Read-Host "Select / 请选择 [y/N]"', source)


class LanPromptWarningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = LAUNCHER.read_text(encoding="utf-8")

    def test_bilingual_warning_is_printed_before_the_choice(self) -> None:
        warning_index = self.source.index("[!] WARNING / 警告")
        prompt_index = self.source.index("$BindHost = Read-LanBindHost")

        self.assertLess(warning_index, prompt_index)

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
