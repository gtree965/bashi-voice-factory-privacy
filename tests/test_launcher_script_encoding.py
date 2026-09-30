"""Guard the launcher's byte-order mark and its parameter block.

Windows PowerShell 5.1 strips exactly one byte-order mark while reading a
script. A second mark sitting in front of ``param(`` hides the parameter block
from the parser, and the ``$(...)`` expression inside the parameter list is
then evaluated on its own, so the launcher starts with substituted defaults
instead of the host and port it was called with.

The mark itself has to stay: without it that interpreter reads the Chinese
text in the script through the local code page and prints mojibake.
"""

import shutil
import subprocess
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = APP_ROOT / "run_portable.ps1"
BOM = b"\xef\xbb\xbf"
DOUBLE_BOM = BOM + BOM
POWERSHELL = "powershell.exe"


def _tracked_scripts() -> "list[Path]":
    """Tracked ``*.ps1`` files as absolute paths."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.ps1"],
        cwd=APP_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise unittest.SkipTest("git is not available for the listing")
    return [APP_ROOT / name for name in result.stdout.split("\0") if name]


class LauncherScriptEncodingTests(unittest.TestCase):
    def test_no_tracked_script_starts_with_two_byte_order_marks(self) -> None:
        scripts = _tracked_scripts()
        self.assertTrue(scripts, "no tracked script was listed")

        for script in scripts:
            with self.subTest(script=script.relative_to(APP_ROOT).as_posix()):
                self.assertFalse(
                    script.read_bytes().startswith(DOUBLE_BOM),
                    "a second byte-order mark hides the parameter block",
                )

    def test_launcher_keeps_one_mark_and_the_parameter_keyword(self) -> None:
        data = LAUNCHER.read_bytes()

        self.assertTrue(data.startswith(BOM + b"param("), data[:16])
        self.assertFalse(data.startswith(DOUBLE_BOM))

    def test_powershell_51_sees_the_parameter_block(self) -> None:
        if shutil.which(POWERSHELL) is None:
            self.skipTest(f"{POWERSHELL} is not available")

        escaped_path = str(LAUNCHER).replace("'", "''")
        command = (
            "$tokens=$null; $errors=$null; "
            f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{escaped_path}', "
            "[ref]$tokens, [ref]$errors); "
            "if ($ast.ParamBlock) { "
            "'BLOCK:' + (@($ast.ParamBlock.Parameters | "
            "ForEach-Object { $_.Name.VariablePath.UserPath }) -join ',') "
            "} else { 'NOBLOCK' }"
        )
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            "BLOCK:BindHost,Port",
            result.stdout.strip(),
            f"stderr: {result.stderr.strip()}",
        )


if __name__ == "__main__":
    unittest.main()
