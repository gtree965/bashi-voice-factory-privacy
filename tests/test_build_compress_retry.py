"""Tests for the compress retry in scripts/build_portable_zip.ps1.

Three builds in a row died in ``Compress-Archive`` on the same staged file with
"being used by another process": the bundled Archive module opens every source
file exclusively, so even a shared reader makes the compression fail. The retry
in ``Compress-StagedPackage`` covers exactly that error, and this file proves it
does - including one case with a real competing reader.

The functions are pulled out of the build script with the PowerShell parser and
called under **Windows PowerShell 5.1**, because the module that fails is the
one that ships with 5.1; PowerShell 7 carries a different implementation.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = APP_ROOT / "scripts" / "build_portable_zip.ps1"

POWERSHELL = (
    Path(os.environ.get("SystemRoot", r"C:\WINDOWS"))
    / "System32"
    / "WindowsPowerShell"
    / "v1.0"
    / "powershell.exe"
)

# The version this machine was measured with; the real-contention case is only
# meaningful against it.
MEASURED_ARCHIVE_VERSION = "1.0.1.0"

FUNCTIONS = (
    "Assert-PathInside",
    "Test-PathInside",
    "Get-StagedPackageRelativePath",
    "Get-CompressAttemptPath",
    "Remove-CompressAttemptFile",
    "Test-IsStagedFileInUseError",
    "Assert-CompressedPackageReadable",
    "Compress-StagedPackage",
)

RETRY_LINE = re.compile(
    r"\[compress-retry\] attempt (\d+) of (\d+): a staged file is still in use "
    r"\((.+)\); waiting (\d+)s before retrying\."
)

HOLDER_SCRIPT = """import pathlib
import sys
import time

target = pathlib.Path(sys.argv[1])
marker = pathlib.Path(sys.argv[2])
hold_seconds = float(sys.argv[3])

with target.open("rb") as handle:
    handle.read(1)
    marker.write_text("locked", encoding="ascii")
    time.sleep(hold_seconds)
"""

HARNESS_BODY = r"""
$DistRoot = Join-Path $WorkRoot 'dist'
$StageRoot = Join-Path $DistRoot 'stage'
$ZipPath = Join-Path $DistRoot 'candidate-windows.zip'

function Initialize-StageTree {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [int]$Files = 3
    )
    if (Test-Path -LiteralPath $Root) {
        Remove-Item -LiteralPath $Root -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $Root 'nested') | Out-Null
    for ($i = 1; $i -le $Files; $i++) {
        Set-Content -LiteralPath (Join-Path $Root ("file{0}.txt" -f $i)) -Value ("staged {0}" -f $i) -Encoding UTF8
    }
    Set-Content -LiteralPath (Join-Path $Root 'nested\child.txt') -Value 'nested' -Encoding UTF8
}

function Get-AttemptFileCount {
    return @(Get-ChildItem -LiteralPath $DistRoot -Filter '*.attempt*.zip' -File -ErrorAction SilentlyContinue).Count
}

function Get-ZipEntryNames {
    param([Parameter(Mandatory = $true)][string]$ArchivePath)
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $names = New-Object System.Collections.Generic.List[string]
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        foreach ($entry in $archive.Entries) {
            $names.Add($entry.FullName.Replace('\', '/'))
        }
    }
    finally {
        $archive.Dispose()
    }
    return $names
}

function New-LeftoverAttemptZip {
    param([Parameter(Mandatory = $true)][string]$Path)
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::Open($Path, [System.IO.Compression.ZipArchiveMode]::Create)
    try {
        $entry = $archive.CreateEntry('leftover-marker.txt')
        $writer = New-Object System.IO.StreamWriter($entry.Open())
        try {
            $writer.Write('left behind by an earlier failure')
        }
        finally {
            $writer.Dispose()
        }
    }
    finally {
        $archive.Dispose()
    }
}

function Write-Outcome {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        $Caught
    )
    Write-Output ("CASE=" + $Name)
    if ($null -eq $Caught) {
        Write-Output 'THREW=0'
    }
    else {
        Write-Output 'THREW=1'
        Write-Output ("THREW_TYPE=" + $Caught.Exception.GetType().FullName)
        Write-Output ("THREW_FQID=" + $Caught.FullyQualifiedErrorId)
        $message = [string]$Caught.Exception.Message
        Write-Output ("THREW_MESSAGE=" + ($message -replace "`r?`n", ' '))
    }
    Write-Output ("ZIP_EXISTS=" + (Test-Path -LiteralPath $ZipPath))
    Write-Output ("ATTEMPT_FILES=" + (Get-AttemptFileCount))
    if ($null -ne $script:MockCalls) {
        Write-Output ("MOCK_CALLS=" + $script:MockCalls.Count)
        Write-Output ("MOCK_UNIQUE_CALLS=" + (@($script:MockCalls | Sort-Object -Unique).Count))
        Write-Output ("MOCK_NON_ATTEMPT=" + (@($script:MockCalls | Where-Object { -not ($_ -match '\.attempt\d+\.zip$') }).Count))
        Write-Output ("MOCK_PREEXISTING=" + ($script:MockPreExisting -join ','))
    }
    if (Test-Path -LiteralPath $ZipPath) {
        $names = Get-ZipEntryNames -ArchivePath $ZipPath
        Write-Output ("ENTRY_COUNT=" + (@($names | Where-Object { -not $_.EndsWith('/') }).Count))
        Write-Output ("ENTRY_HAS_ATTEMPT=" + (@($names | Where-Object { $_ -match '\.attempt\d+\.zip$' }).Count))
        Write-Output ("ENTRY_HAS_LEFTOVER=" + (@($names | Where-Object { $_ -like '*leftover-marker*' }).Count))
    }
}

function Set-MockCompress {
    param(
        [int]$ConflictAttempts = 0,
        [string]$Target,
        [string]$SourceDir,
        [string]$FailureMode = 'sharing',
        [string]$Mode = 'valid'
    )
    $script:MockCalls = New-Object System.Collections.Generic.List[string]
    $script:MockPreExisting = New-Object System.Collections.Generic.List[string]
    $script:MockConflictAttempts = $ConflictAttempts
    $script:MockTarget = $Target
    $script:MockSourceDir = $SourceDir
    $script:MockFailureMode = $FailureMode
    $script:MockMode = $Mode

    function global:Compress-Archive {
        param(
            [Parameter(Mandatory = $true)][string]$Path,
            [Parameter(Mandatory = $true)][string]$DestinationPath,
            [string]$CompressionLevel = 'Optimal'
        )
        $script:MockCalls.Add($DestinationPath)
        $script:MockPreExisting.Add($(if (Test-Path -LiteralPath $DestinationPath) { '1' } else { '0' }))

        if ($script:MockFailureMode -eq 'custom') {
            & $script:MockFailureScript
        }

        if ($script:MockConflictAttempts -gt 0) {
            $script:MockConflictAttempts--
            $target = $script:MockTarget
            # A real sharing violation, produced the same way the module runs
            # into one: this handle is open for shared read, and the module
            # asks for exclusive access.
            $shared = [System.IO.File]::Open($target, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
            try {
                [System.IO.File]::Open($target, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::None) | Out-Null
                throw 'the exclusive open unexpectedly succeeded'
            }
            catch [System.IO.IOException] {
                $exception = $_.Exception
            }
            finally {
                $shared.Dispose()
            }
            $record = New-Object System.Management.Automation.ErrorRecord($exception, 'CompressArchiveUnauthorizedAccessError,ZipArchiveHelper', [System.Management.Automation.ErrorCategory]::PermissionDenied, $target)
            throw $record
        }

        if ($script:MockMode -eq 'junk') {
            [System.IO.File]::WriteAllBytes($DestinationPath, [byte[]](1..64))
            return
        }

        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::CreateFromDirectory($script:MockSourceDir, $DestinationPath)
    }
}

function Invoke-Case {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [switch]$UseDefaults
    )
    $caught = $null
    try {
        if ($UseDefaults) {
            # No overrides: the real case has to exercise the shipped defaults.
            Compress-StagedPackage -StageRoot $StageRoot -ZipPath $ZipPath
        }
        else {
            Compress-StagedPackage -StageRoot $StageRoot -ZipPath $ZipPath -MaxAttempts $script:Attempts -RetryWaitSeconds $script:Waits
        }
    }
    catch {
        $caught = $_
    }
    Write-Outcome -Name $Name -Caught $caught
}

$script:Attempts = 5
$script:Waits = @(0, 0, 0, 0)

switch ($Case) {
    'real-contention' {
        New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
        Initialize-StageTree -Root $StageRoot -Files 3
        $locked = Join-Path $StageRoot 'nested\child.txt'
        $marker = Join-Path $WorkRoot 'locked.marker'
        $holder = Start-Process -FilePath $env:BASHI_TEST_PYTHON -ArgumentList @($env:BASHI_TEST_HOLDER, $locked, $marker, '5.5') -PassThru
        $deadline = (Get-Date).AddSeconds(20)
        while (-not (Test-Path -LiteralPath $marker)) {
            if ((Get-Date) -gt $deadline) {
                throw 'the holder process never took its shared read'
            }
            Start-Sleep -Milliseconds 50
        }

        $probe = Join-Path $DistRoot 'probe.zip'
        $probeRecord = $null
        try {
            Compress-Archive -Path (Join-Path $StageRoot '*') -DestinationPath $probe -CompressionLevel Optimal -ErrorAction Stop
        }
        catch {
            $probeRecord = $_
        }
        Write-Output ("PROBE_THREW=" + ($null -ne $probeRecord))
        if ($null -ne $probeRecord) {
            Write-Output ("PROBE_EXCEPTION=" + $probeRecord.Exception.GetType().FullName)
            Write-Output ("PROBE_EXCEPTION_HRESULT=0x{0:X8}" -f $probeRecord.Exception.HResult)
            $inner = $probeRecord.Exception.InnerException
            $innerIndex = 0
            while ($null -ne $inner) {
                $innerIndex++
                Write-Output ("PROBE_INNER{0}={1} HRESULT=0x{2:X8}" -f $innerIndex, $inner.GetType().FullName, $inner.HResult)
                $inner = $inner.InnerException
            }
            Write-Output ("PROBE_FQID=" + $probeRecord.FullyQualifiedErrorId)
            Write-Output ("PROBE_CATEGORY=" + $probeRecord.CategoryInfo.Category)
            Write-Output ("PROBE_TARGET_TYPE=" + $probeRecord.TargetObject.GetType().FullName)
            Write-Output ("PROBE_TARGET_INSIDE=" + (Test-PathInside -Path ([string]$probeRecord.TargetObject).Trim() -Parent $StageRoot))
            Write-Output ("PROBE_CLASSIFIED=" + (Test-IsStagedFileInUseError -ErrorRecord $probeRecord -StageRoot $StageRoot))
        }
        if (Test-Path -LiteralPath $probe) {
            Remove-Item -LiteralPath $probe -Force
        }

        Invoke-Case -Name $Case -UseDefaults
        $holder | Wait-Process -Timeout 30 -ErrorAction SilentlyContinue
    }

    'mock-two-then-success' {
        New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
        Initialize-StageTree -Root $StageRoot -Files 3
        Set-MockCompress -ConflictAttempts 2 -Target (Join-Path $StageRoot 'nested\child.txt') -SourceDir $StageRoot
        $script:Waits = @(0, 1, 2, 3)
        Invoke-Case -Name $Case
    }

    'mock-exhausted' {
        New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
        Initialize-StageTree -Root $StageRoot -Files 3
        Set-MockCompress -ConflictAttempts 99 -Target (Join-Path $StageRoot 'nested\child.txt') -SourceDir $StageRoot
        Invoke-Case -Name $Case
    }

    'mock-leftover-attempt-file' {
        New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
        Initialize-StageTree -Root $StageRoot -Files 3
        New-LeftoverAttemptZip -Path (Join-Path $DistRoot 'candidate-windows.attempt1.zip')
        Set-MockCompress -ConflictAttempts 2 -Target (Join-Path $StageRoot 'nested\child.txt') -SourceDir $StageRoot
        Invoke-Case -Name $Case
    }

    'mock-fewer-files' {
        New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
        Initialize-StageTree -Root $StageRoot -Files 3
        $shortRoot = Join-Path $WorkRoot 'short'
        if (Test-Path -LiteralPath $shortRoot) { Remove-Item -LiteralPath $shortRoot -Recurse -Force }
        New-Item -ItemType Directory -Force -Path $shortRoot | Out-Null
        Set-Content -LiteralPath (Join-Path $shortRoot 'only.txt') -Value 'one' -Encoding UTF8
        Set-MockCompress -ConflictAttempts 0 -Target (Join-Path $StageRoot 'nested\child.txt') -SourceDir $shortRoot
        Invoke-Case -Name $Case
    }

    'mock-renamed-paths' {
        New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
        Initialize-StageTree -Root $StageRoot -Files 3
        $renamedRoot = Join-Path $WorkRoot 'renamed'
        if (Test-Path -LiteralPath $renamedRoot) { Remove-Item -LiteralPath $renamedRoot -Recurse -Force }
        New-Item -ItemType Directory -Force -Path (Join-Path $renamedRoot 'nested') | Out-Null
        foreach ($name in @('other1.txt', 'other2.txt', 'other3.txt')) {
            Set-Content -LiteralPath (Join-Path $renamedRoot $name) -Value 'x' -Encoding UTF8
        }
        Set-Content -LiteralPath (Join-Path $renamedRoot 'nested\other.txt') -Value 'x' -Encoding UTF8
        Set-MockCompress -ConflictAttempts 0 -Target (Join-Path $StageRoot 'nested\child.txt') -SourceDir $renamedRoot
        Invoke-Case -Name $Case
    }

    'mock-unreadable-archive' {
        New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
        Initialize-StageTree -Root $StageRoot -Files 3
        Set-MockCompress -ConflictAttempts 0 -Target (Join-Path $StageRoot 'nested\child.txt') -SourceDir $StageRoot -Mode 'junk'
        Invoke-Case -Name $Case
    }

    'mock-access-denied' {
        New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
        Initialize-StageTree -Root $StageRoot -Files 3
        Set-MockCompress -ConflictAttempts 0 -Target (Join-Path $StageRoot 'nested\child.txt') -SourceDir $StageRoot -FailureMode 'custom'
        $script:MockFailureScript = {
            $exception = New-Object System.UnauthorizedAccessException('Access to the path is denied.')
            $record = New-Object System.Management.Automation.ErrorRecord($exception, 'CompressArchiveUnauthorizedAccessError,ZipArchiveHelper', [System.Management.Automation.ErrorCategory]::PermissionDenied, $script:StageRoot)
            throw $record
        }
        Invoke-Case -Name $Case
    }

    'mock-missing-source' {
        New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
        Initialize-StageTree -Root $StageRoot -Files 3
        Set-MockCompress -ConflictAttempts 0 -Target (Join-Path $StageRoot 'nested\child.txt') -SourceDir $StageRoot -FailureMode 'custom'
        $script:MockFailureScript = {
            $exception = New-Object System.IO.FileNotFoundException("Could not find file 'missing.bin'.")
            $record = New-Object System.Management.Automation.ErrorRecord($exception, 'CompressArchiveUnauthorizedAccessError,ZipArchiveHelper', [System.Management.Automation.ErrorCategory]::PermissionDenied, (Join-Path $script:StageRoot 'missing.bin'))
            throw $record
        }
        Invoke-Case -Name $Case
    }

    'mock-other-io' {
        New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
        Initialize-StageTree -Root $StageRoot -Files 3
        Set-MockCompress -ConflictAttempts 0 -Target (Join-Path $StageRoot 'nested\child.txt') -SourceDir $StageRoot -FailureMode 'custom'
        $script:MockFailureScript = {
            $exception = New-Object System.IO.IOException('The process cannot read from the stream.')
            $record = New-Object System.Management.Automation.ErrorRecord($exception, 'CompressArchiveUnauthorizedAccessError,ZipArchiveHelper', [System.Management.Automation.ErrorCategory]::PermissionDenied, (Join-Path $script:StageRoot 'nested\child.txt'))
            throw $record
        }
        Invoke-Case -Name $Case
    }

    'mock-conflict-outside-stage' {
        $outsideDir = Join-Path $WorkRoot 'outside'
        New-Item -ItemType Directory -Force -Path $DistRoot, $outsideDir | Out-Null
        Initialize-StageTree -Root $StageRoot -Files 3
        $outsideFile = Join-Path $outsideDir 'not-staged.txt'
        Set-Content -LiteralPath $outsideFile -Value 'outside' -Encoding UTF8
        Set-MockCompress -ConflictAttempts 99 -Target $outsideFile -SourceDir $StageRoot
        Invoke-Case -Name $Case
    }
}
"""

EXTRACTOR = """
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{script}', [ref]$tokens, [ref]$errors)
{lookups}
"""

_EXTRACTED_CACHE = {}


def _find_powershell():
    if POWERSHELL.exists():
        return str(POWERSHELL)
    return shutil.which("powershell.exe")


def _run_powershell(arguments, script_text=None):
    powershell = _find_powershell()
    if powershell is None:
        return None
    if script_text is None:
        return subprocess.run(
            [powershell] + list(arguments), capture_output=True, text=True, timeout=300
        )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "runner.ps1"
        path.write_text(script_text, encoding="utf-8-sig")
        return subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path)],
            capture_output=True,
            text=True,
            timeout=600,
        )


def _extract_functions() -> str:
    """Pull the functions out of the build script with the PowerShell parser."""
    if "source" in _EXTRACTED_CACHE:
        return _EXTRACTED_CACHE["source"]

    lookups = []
    for name in FUNCTIONS:
        lookups.append(
            "$fn=$ast.Find({param($node) $node -is "
            "[System.Management.Automation.Language.FunctionDefinitionAst] -and "
            f"$node.Name -eq '{name}'}}, $true); "
            f"Write-Output '###FUNC###{name}'; "
            "Write-Output $fn.Extent.Text; "
            "Write-Output '###END###'"
        )
    script = EXTRACTOR.replace("{script}", str(BUILD_SCRIPT).replace("'", "''")).replace(
        "{lookups}", "\n".join(lookups)
    )
    result = _run_powershell([], script_text=script)
    if result is None or result.returncode != 0:
        raise AssertionError(
            "could not read %s with the PowerShell parser: %s"
            % (BUILD_SCRIPT, getattr(result, "stderr", ""))
        )

    extracted = []
    current = None
    for line in result.stdout.replace("\r\n", "\n").split("\n"):
        if line.startswith("###FUNC###"):
            current = [line[len("###FUNC###"):], []]
            extracted.append(current)
        elif line == "###END###":
            current = None
        elif current is not None:
            current[1].append(line)

    found = {name: "\n".join(lines) for name, lines in extracted}
    missing = [name for name in FUNCTIONS if not found.get(name)]
    if missing:
        raise AssertionError("could not extract %s from %s" % (missing, BUILD_SCRIPT))

    source = "\n\n".join(found[name] for name in FUNCTIONS)
    _EXTRACTED_CACHE["source"] = source
    return source


def _parse_output(stdout: str):
    values = {}
    for line in stdout.replace("\r\n", "\n").split("\n"):
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


class BuildCompressRetryTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        if _find_powershell() is None:
            self.skipTest("powershell.exe is not available, so the retry cannot run")
        self.assertTrue(
            BUILD_SCRIPT.exists(), "the build script is missing: %s" % BUILD_SCRIPT
        )

    def _run_case(self, case, work_root, holder_path=None):
        functions = _extract_functions()
        header = (
            "param(\n"
            "    [Parameter(Mandatory = $true)][string]$Case,\n"
            "    [Parameter(Mandatory = $true)][string]$WorkRoot\n"
            ")\n"
            "$ErrorActionPreference = 'Stop'\n"
            # A machine with PowerShell 7 installed can expose a newer Archive
            # module than the one that ships with 5.1, and that newer module
            # opens sources with a shared mode, so a competing reader no longer
            # breaks it. The builds that failed used the in-box 1.0.1.0, so the
            # harness pins the module path to it and reports what it got.
            "$env:PSModulePath = Join-Path $PSHOME 'Modules'\n"
            "$archiveCommand = Get-Command Compress-Archive\n"
            "Write-Output ('PS_MAJOR=' + $PSVersionTable.PSVersion.Major)\n"
            "Write-Output ('PS_VERSION=' + $PSVersionTable.PSVersion.ToString())\n"
            "Write-Output ('ARCHIVE_VERSION=' + $archiveCommand.Module.Version.ToString())\n"
            "Write-Output ('ARCHIVE_SOURCE=' + $archiveCommand.Source)\n"
            "Write-Output ('ARCHIVE_LIST=' + ((Get-Module -ListAvailable "
            "Microsoft.PowerShell.Archive | ForEach-Object { $_.Version.ToString() }) -join ','))\n"
        )
        script = header + "\n" + functions + "\n" + HARNESS_BODY
        harness_path = Path(work_root) / "harness.ps1"
        harness_path.write_text(script, encoding="utf-8-sig")

        environment = dict(os.environ)
        environment["BASHI_TEST_PYTHON"] = sys.executable
        environment["BASHI_TEST_HOLDER"] = str(holder_path or "")

        return subprocess.run(
            [
                _find_powershell(),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(harness_path),
                "-Case",
                case,
                "-WorkRoot",
                str(work_root),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            env=environment,
        )

    def _assert_case(self, case, with_holder=False):
        with tempfile.TemporaryDirectory() as tmp:
            work_root = Path(tmp)
            holder_path = None
            if with_holder:
                holder_path = work_root / "holder.py"
                holder_path.write_text(HOLDER_SCRIPT, encoding="utf-8")
            result = self._run_case(case, work_root, holder_path=holder_path)

        self.assertEqual(0, result.returncode, result.stderr)
        values = _parse_output(result.stdout)
        retries = RETRY_LINE.findall(result.stdout)
        # Every case asserts the runtime first: the module that fails is the one
        # that ships with Windows PowerShell 5.1.
        self.assertEqual("5", values.get("PS_MAJOR"), result.stdout)
        self.assertEqual(case, values.get("CASE"), result.stdout)
        return values, retries, result

    def test_real_contention_is_retried_and_recovers(self):
        values, retries, result = self._assert_case("real-contention", with_holder=True)
        archive_version = values.get("ARCHIVE_VERSION")
        if archive_version != MEASURED_ARCHIVE_VERSION:
            self.skipTest(
                "the Archive module here is %s, not the measured %s, so a real "
                "sharing violation cannot be assumed" % (archive_version, MEASURED_ARCHIVE_VERSION)
            )

        # The mechanism behind the build failures, reproduced: a shared reader
        # is enough to make the module's exclusive open fail, and the record
        # carries the sharing violation inside the staging tree.
        self.assertEqual("True", values.get("PROBE_THREW"), result.stdout)
        self.assertEqual("True", values.get("PROBE_TARGET_INSIDE"), result.stdout)
        self.assertEqual("True", values.get("PROBE_CLASSIFIED"), result.stdout)
        self.assertIn("IOException", values.get("PROBE_EXCEPTION", ""))
        self.assertEqual("PermissionDenied", values.get("PROBE_CATEGORY"))
        self.assertIn("CompressArchiveUnauthorizedAccessError", values.get("PROBE_FQID", ""))

        self.assertEqual("0", values.get("THREW"), values.get("THREW_TYPE"))
        self.assertEqual("True", values.get("ZIP_EXISTS"))
        self.assertEqual("0", values.get("ATTEMPT_FILES"))
        self.assertEqual("4", values.get("ENTRY_COUNT"))
        self.assertGreaterEqual(len(retries), 1)
        # The shipped defaults, in order, are what the real case exercises.
        expected_waits = [("1", "2"), ("2", "4"), ("3", "8"), ("4", "16")]
        self.assertEqual(expected_waits[: len(retries)], [(r[0], r[3]) for r in retries])
        for _attempt, total, relative, _wait in retries:
            self.assertEqual("5", total)
            self.assertTrue(relative.endswith("nested/child.txt"), relative)
            self.assertNotIn("\\", relative)
            self.assertNotIn(":", relative)

    def test_two_conflicts_then_success(self):
        values, retries, _result = self._assert_case("mock-two-then-success")

        self.assertEqual("0", values.get("THREW"))
        self.assertEqual("True", values.get("ZIP_EXISTS"))
        self.assertEqual("0", values.get("ATTEMPT_FILES"))
        self.assertEqual("4", values.get("ENTRY_COUNT"))
        self.assertEqual("0", values.get("ENTRY_HAS_ATTEMPT"))
        self.assertEqual(2, len(retries))
        self.assertEqual([("1", "0"), ("2", "1")], [(r[0], r[3]) for r in retries])
        # A fresh destination for every attempt, and never the candidate name.
        self.assertEqual(values.get("MOCK_CALLS"), values.get("MOCK_UNIQUE_CALLS"))
        self.assertEqual("0", values.get("MOCK_NON_ATTEMPT"))

    def test_conflicts_until_the_attempts_run_out(self):
        values, retries, _result = self._assert_case("mock-exhausted")

        self.assertEqual("1", values.get("THREW"))
        self.assertIn("IOException", values.get("THREW_TYPE", ""))
        self.assertEqual("False", values.get("ZIP_EXISTS"))
        self.assertEqual("0", values.get("ATTEMPT_FILES"))
        self.assertEqual("5", values.get("MOCK_CALLS"))
        self.assertEqual(values.get("MOCK_CALLS"), values.get("MOCK_UNIQUE_CALLS"))
        self.assertEqual("0", values.get("MOCK_NON_ATTEMPT"))
        self.assertEqual(4, len(retries))
        self.assertEqual(["1", "2", "3", "4"], [r[0] for r in retries])

    def test_a_leftover_or_failed_attempt_file_never_reaches_the_next_one(self):
        values, retries, _result = self._assert_case("mock-leftover-attempt-file")

        # Attempt 1 found a leftover from an earlier failure and every later
        # attempt found nothing: the failed attempt's file is gone before the
        # next one starts.
        self.assertEqual("1,0,0", values.get("MOCK_PREEXISTING"))
        self.assertEqual(2, len(retries))
        self.assertEqual("0", values.get("THREW"))
        self.assertEqual("True", values.get("ZIP_EXISTS"))
        self.assertEqual("0", values.get("ATTEMPT_FILES"))
        self.assertEqual("0", values.get("ENTRY_HAS_ATTEMPT"))
        self.assertEqual("0", values.get("ENTRY_HAS_LEFTOVER"))

    def test_a_package_that_does_not_match_the_staging_tree_is_rejected(self):
        for case, expectation in (
            ("mock-fewer-files", "file entries"),
            ("mock-renamed-paths", "entry paths do not match"),
        ):
            with self.subTest(case=case):
                values, retries, _result = self._assert_case(case)
                self.assertEqual("1", values.get("THREW"))
                self.assertEqual("False", values.get("ZIP_EXISTS"))
                self.assertEqual("0", values.get("ATTEMPT_FILES"))
                self.assertEqual([], retries)
                self.assertIn(expectation, values.get("THREW_MESSAGE", ""))

    def test_an_unreadable_package_is_rejected(self):
        values, retries, _result = self._assert_case("mock-unreadable-archive")

        self.assertEqual("1", values.get("THREW"))
        self.assertEqual("False", values.get("ZIP_EXISTS"))
        self.assertEqual("0", values.get("ATTEMPT_FILES"))
        self.assertEqual([], retries)

    def test_other_failures_are_not_retried(self):
        for case in (
            "mock-access-denied",
            "mock-missing-source",
            "mock-other-io",
            "mock-conflict-outside-stage",
        ):
            with self.subTest(case=case):
                values, retries, _result = self._assert_case(case)
                self.assertEqual("1", values.get("THREW"))
                self.assertEqual("False", values.get("ZIP_EXISTS"))
                self.assertEqual("0", values.get("ATTEMPT_FILES"))
                self.assertEqual("1", values.get("MOCK_CALLS"))
                self.assertEqual([], retries)


if __name__ == "__main__":
    unittest.main()
