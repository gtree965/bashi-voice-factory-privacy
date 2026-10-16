"""Keep portable builds on the same compression implementation."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
PS = shutil.which("powershell.exe")


@unittest.skipUnless(PS, "Windows PowerShell is required")
class ArchiveModuleTests(unittest.TestCase):
    def invoke(self, setup="", verify_hash=False):
        source = str(ROOT / "scripts/build_portable_zip.ps1").replace("'", "''")
        command = ("$ErrorActionPreference='Stop'; $tokens=$null; $errors=$null; "
                   "$ast=[System.Management.Automation.Language.Parser]::ParseFile('" + source + "',[ref]$tokens,[ref]$errors); "
                   "$fn=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and "
                   "$n.Name -eq 'Import-PortableArchiveModule'},$true); Invoke-Expression $fn.Extent.Text; "
                   + setup + " Import-PortableArchiveModule; "
                   + ("(Get-FileHash -LiteralPath '" + source + "' -Algorithm SHA256).Hash.Length; " if verify_hash else "")
                   + "(Get-Command Compress-Archive).Module.Version.ToString()")
        return subprocess.run([PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command], capture_output=True, text=True)

    def test_uses_windows_archive_version(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Archive module: 1.0.1.0", result.stdout)
        self.assertTrue(result.stdout.strip().endswith("1.0.1.0"))

    def test_preloaded_other_module_does_not_change_build_selection(self):
        alternate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "PowerShell/7/Modules/Microsoft.PowerShell.Archive/Microsoft.PowerShell.Archive.psd1"
        if not alternate.exists():
            self.skipTest("alternate module is not installed")
        setup = "Import-Module '" + str(alternate).replace("'", "''") + "' -Force; "
        result = self.invoke(setup)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Archive module: 1.0.1.0", result.stdout)

    def test_hash_command_remains_available_to_the_build_caller(self):
        result = self.invoke(verify_hash=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("\n64\n", result.stdout.replace("\r\n", "\n"))
