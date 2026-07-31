import subprocess
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = APP_ROOT / "run_portable.ps1"


def _invoke_lan_prompt(expression: str) -> str:
    escaped_path = str(LAUNCHER).replace("'", "''")
    command = (
        "$tokens=$null; $errors=$null; "
        f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{escaped_path}', "
        "[ref]$tokens, [ref]$errors); "
        "$fn=$ast.Find({param($node) $node -is "
        "[System.Management.Automation.Language.FunctionDefinitionAst] -and "
        "$node.Name -eq 'Read-LanBindHost'}, $true); "
        "Invoke-Expression $fn.Extent.Text; "
        f"{expression}"
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


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


if __name__ == "__main__":
    unittest.main()
