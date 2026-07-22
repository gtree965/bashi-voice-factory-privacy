param(
    [string]$Version = "",
    [string]$PythonEmbedZip = "",
    [switch]$NoPythonOnly,
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppRoot = (Resolve-Path -LiteralPath (Join-Path $ScriptRoot "..")).Path
$WorkspaceRoot = (Resolve-Path -LiteralPath (Join-Path $AppRoot "..")).Path
$DistRoot = Join-Path $AppRoot "dist"
$EmbedZipName = "python-3.12.10-embed-amd64.zip"
$EmbedDirName = "python-3.12.10-embed-amd64"
$EmbedSha256 = "4ACBED6DD1C744B0376E3B1CF57CE906F9DC9E95E68824584C8099A63025A3C3"
$EmbedDownloadUrl = "https://www.python.org/ftp/python/3.12.10/$EmbedZipName"

if (-not $Version) {
    $Version = (Get-Content -LiteralPath (Join-Path $AppRoot "VERSION") -TotalCount 1).Trim()
}
if (-not $Version) {
    throw "VERSION file is empty."
}

$PackageName = "bashi-voice-factory-privacy-v$Version"

function Assert-PathInside {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Parent
    )
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullParent = [System.IO.Path]::GetFullPath($Parent).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    if (-not $fullPath.StartsWith($fullParent + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to operate outside ${fullParent}: ${fullPath}"
    }
}

function Test-Sha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Expected
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        return $false
    }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    return $actual.Equals($Expected, [System.StringComparison]::OrdinalIgnoreCase)
}

function Resolve-EmbedZip {
    if ($PythonEmbedZip) {
        $resolved = (Resolve-Path -LiteralPath $PythonEmbedZip).Path
        if (-not (Test-Sha256 -Path $resolved -Expected $EmbedSha256)) {
            throw "SHA256 mismatch for explicit Python embed zip: $resolved"
        }
        return $resolved
    }

    $cacheDir = Join-Path $WorkspaceRoot "release_artifacts\cached"
    $cachedZip = Join-Path $cacheDir $EmbedZipName
    $candidateZips = @(
        $cachedZip,
        (Join-Path $WorkspaceRoot $EmbedZipName),
        (Join-Path $AppRoot $EmbedZipName)
    )

    foreach ($candidate in $candidateZips) {
        if (Test-Sha256 -Path $candidate -Expected $EmbedSha256) {
            if ($candidate -ne $cachedZip) {
                New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
                Copy-Item -LiteralPath $candidate -Destination $cachedZip -Force
            }
            return (Resolve-Path -LiteralPath $cachedZip).Path
        }
    }

    New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
    Write-Host "Downloading official Python embed zip: $EmbedDownloadUrl"
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest -Uri $EmbedDownloadUrl -OutFile $cachedZip -UseBasicParsing -ErrorAction Stop
    if (-not (Test-Sha256 -Path $cachedZip -Expected $EmbedSha256)) {
        Remove-Item -LiteralPath $cachedZip -Force -ErrorAction SilentlyContinue
        throw "Downloaded Python embed zip failed SHA256 verification."
    }
    return (Resolve-Path -LiteralPath $cachedZip).Path
}

function New-CleanDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)
    New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
    Assert-PathInside -Path $Path -Parent $DistRoot
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Copy-RelativeFile {
    param(
        [Parameter(Mandatory = $true)][string]$SourceRoot,
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][string]$DestRoot
    )
    $source = Join-Path $SourceRoot $RelativePath
    if (-not (Test-Path -LiteralPath $source)) {
        throw "Missing required file: $source"
    }
    $dest = Join-Path $DestRoot $RelativePath
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
    Copy-Item -LiteralPath $source -Destination $dest -Force
}

function Copy-RelativeDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$SourceRoot,
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][string]$DestRoot
    )
    $source = Join-Path $SourceRoot $RelativePath
    if (-not (Test-Path -LiteralPath $source)) {
        throw "Missing required directory: $source"
    }
    $dest = Join-Path $DestRoot $RelativePath
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
    Copy-Item -LiteralPath $source -Destination $dest -Recurse -Force
}

function Remove-StagedDebris {
    param([Parameter(Mandatory = $true)][string]$Root)
    Get-ChildItem -LiteralPath $Root -Recurse -Force -Directory |
        Where-Object { $_.Name -in @("__pycache__", ".git", ".venv", ".tmp", "tests") -or $_.Name -like "tmp*" } |
        Sort-Object FullName -Descending |
        ForEach-Object {
            Assert-PathInside -Path $_.FullName -Parent $Root
            Remove-Item -LiteralPath $_.FullName -Recurse -Force
        }

    Get-ChildItem -LiteralPath $Root -Recurse -Force -File |
        Where-Object {
            $_.Name -eq ".gitignore" -or
            $_.Name -like "*.pyc" -or
            $_.Name -like "*.pyo" -or
            $_.Name -like "*.log" -or
            $_.Name -like "llama-*-bin-*.zip" -or
            $_.Name -like "*.odt" -or
            $_.Name -like ".~lock.*#"
        } |
        ForEach-Object {
            Assert-PathInside -Path $_.FullName -Parent $Root
            Remove-Item -LiteralPath $_.FullName -Force
        }
}

function Add-EmbedPython {
    param(
        [Parameter(Mandatory = $true)][string]$EmbedZip,
        [Parameter(Mandatory = $true)][string]$AppDest
    )
    $embedDest = Join-Path $AppDest $EmbedDirName
    New-Item -ItemType Directory -Force -Path $embedDest | Out-Null
    Expand-Archive -LiteralPath $EmbedZip -DestinationPath $embedDest -Force
    if (-not (Test-Path -LiteralPath (Join-Path $embedDest "python.exe"))) {
        throw "Expanded Python embed is missing python.exe: $embedDest"
    }
}

function Assert-LauncherCompatibility {
    param([Parameter(Mandatory = $true)][string]$AppDest)

    $smartQuotePattern = "[" + [char]0x201C + [char]0x201D + [char]0x2018 + [char]0x2019 + "]"
    $windowsPowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

    $psFiles = Get-ChildItem -LiteralPath $AppDest -Recurse -File -Filter *.ps1
    if (-not $psFiles) {
        throw "No .ps1 files staged under $AppDest"
    }

    $mainLauncher = Join-Path $AppDest "run_portable.ps1"
    if (-not (Test-Path -LiteralPath $mainLauncher)) {
        throw "Missing staged launcher: $mainLauncher"
    }

    foreach ($file in $psFiles) {
        $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
        if ($bytes.Length -lt 3 -or $bytes[0] -ne 0xEF -or $bytes[1] -ne 0xBB -or $bytes[2] -ne 0xBF) {
            throw ("Missing UTF-8 BOM in {0}; Windows PowerShell 5.1 mis-decodes BOM-less .ps1 under CJK ANSI code pages." -f $file.FullName)
        }

        if (Select-String -LiteralPath $file.FullName -Pattern $smartQuotePattern -Quiet) {
            throw ("Smart quotes found in {0}; Windows PowerShell will not parse it reliably." -f $file.FullName)
        }

        if (Test-Path -LiteralPath $windowsPowerShell) {
            $escaped = $file.FullName.Replace("'", "''")
            $parseCommand = '$ErrorActionPreference = ''Stop''; $null = [scriptblock]::Create((Get-Content -LiteralPath ''' + $escaped + ''' -Raw))'
            & $windowsPowerShell -NoProfile -ExecutionPolicy Bypass -Command $parseCommand
            if ($LASTEXITCODE -ne 0) {
                throw ("{0} failed Windows PowerShell parser validation." -f $file.FullName)
            }
        }
    }
}

function Stage-Package {
    param(
        [Parameter(Mandatory = $true)][string]$StageRoot,
        [string]$EmbedZip = ""
    )

    New-CleanDirectory -Path $StageRoot

    $appDest = Join-Path $StageRoot "bashi-privacy-app"
    $ggufDest = Join-Path $StageRoot "vulkan_backend_spike\Qwen3-TTS-GGUF"

    New-Item -ItemType Directory -Force -Path $appDest, $ggufDest | Out-Null

    $appFiles = @(
        "app.py",
        "audio_encoding.py",
        "backend_probe.py",
        "download_cuda_runtime.py",
        "download_gguf_model.py",
        "download_utils.py",
        "LICENSE",
        "local_tts_engine.py",
        "local_tts_engine_gguf.py",
        "local_tts_engine_pytorch.py",
        "local_voice_catalog.py",
        "model_manager.py",
        "PRIVACY.md",
        "README.md",
        "requirements.txt",
        "run_portable.bat",
        "run_portable.ps1",
        "run-gguf.cmd",
        "run-gguf.ps1",
        "run-pytorch.cmd",
        "run-pytorch.ps1",
        "speaker_diarization.py",
        "stt_engine.py",
        "stt_routes.py",
        "SYSTEM_OVERVIEW.md",
        "tts_routes.py",
        "utils.py",
        "VERSION",
        "zh_confusion.py"
    )
    foreach ($file in $appFiles) {
        Copy-RelativeFile -SourceRoot $AppRoot -RelativePath $file -DestRoot $appDest
    }

    foreach ($dir in @("bashi_tts_kernel", "data", "engines", "templates", "static\css", "static\images", "static\js", "static\audio\style_previews")) {
        Copy-RelativeDirectory -SourceRoot $AppRoot -RelativePath $dir -DestRoot $appDest
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $appDest "models"), (Join-Path $appDest "static\audio"), (Join-Path $appDest "static\uploads") | Out-Null

    $ggufSource = Join-Path $WorkspaceRoot "vulkan_backend_spike\Qwen3-TTS-GGUF"
    Copy-RelativeFile -SourceRoot $ggufSource -RelativePath "requirements.txt" -DestRoot $ggufDest
    Copy-RelativeFile -SourceRoot $ggufSource -RelativePath "readme.md" -DestRoot $ggufDest
    Copy-RelativeFile -SourceRoot $ggufSource -RelativePath "qwen3_tts_gguf\__init__.py" -DestRoot $ggufDest
    Copy-RelativeDirectory -SourceRoot $ggufSource -RelativePath "qwen3_tts_gguf\inference" -DestRoot $ggufDest
    New-Item -ItemType Directory -Force -Path (Join-Path $ggufDest "model-custom") | Out-Null

    if ($EmbedZip) {
        Add-EmbedPython -EmbedZip $EmbedZip -AppDest $appDest
    }

    # Top-level launcher — delegates to the real launcher inside bashi-privacy-app
    # so non-tech users see one obvious entry point at the extracted root instead
    # of having to dig through 20+ files in bashi-privacy-app/.
    $topLauncherPath = Join-Path $StageRoot "Start_启动.bat"
    $launcherContent = @"
@echo off
cd /d "%~dp0bashi-privacy-app"
call run_portable.bat %*
exit /b %ERRORLEVEL%
"@
    # .bat files MUST be ASCII (no BOM) — cmd.exe parses EF BB BF as a stray command.
    Set-Content -LiteralPath $topLauncherPath -Value $launcherContent -Encoding ASCII

    # Optional CPU-only launcher — for users on weak iGPU (e.g., Intel N100/N305)
    # who want to A/B test whether pure CPU is faster than DirectML/Vulkan iGPU
    # without setting env vars by hand. Sets GGUF_LLM_USE_GPU=0 +
    # GGUF_ONNX_PROVIDER=CPU before delegating to the standard launcher.
    $cpuLauncherPath = Join-Path $StageRoot "Start_CPU_only_仅CPU启动.bat"
    $cpuLauncherContent = @"
@echo off
REM Force GGUF LLM to use CPU (skip Vulkan); force ONNX decoder to use CPU (skip DirectML).
REM Useful on entry-level iGPU where GPU overhead may outweigh benefit.
REM Edit/delete this file if not needed.
set "GGUF_LLM_USE_GPU=0"
set "GGUF_ONNX_PROVIDER=CPU"
cd /d "%~dp0bashi-privacy-app"
call run_portable.bat %*
exit /b %ERRORLEVEL%
"@
    Set-Content -LiteralPath $cpuLauncherPath -Value $cpuLauncherContent -Encoding ASCII

    # Top-level bilingual READMEs — source files live in bashi-privacy-app/release_docs/
    # and are copied verbatim. Cross-link line at top of each: README.md says
    # "**English** | [中文文档](README_CN.md)"; README_CN.md says
    # "[English](README.md) | **中文文档**".
    $releaseDocsDir = Join-Path $AppRoot "release_docs"
    foreach ($name in @("README.md", "README_CN.md")) {
        $src = Join-Path $releaseDocsDir $name
        if (-not (Test-Path -LiteralPath $src)) {
            throw "Missing top-level doc source: $src"
        }
        Copy-Item -LiteralPath $src -Destination (Join-Path $StageRoot $name) -Force
        Copy-Item -LiteralPath $src -Destination (Join-Path $appDest $name) -Force
    }
    foreach ($name in @("LICENSE", "VERSION")) {
        $src = Join-Path $AppRoot $name
        if (-not (Test-Path -LiteralPath $src)) {
            throw "Missing top-level metadata source: $src"
        }
        Copy-Item -LiteralPath $src -Destination (Join-Path $StageRoot $name) -Force
    }

    # Optional bilingual PDF help file. Alex generates this locally (Word
    # "Save as PDF", or Pandoc + Edge headless print-to-pdf) and drops it
    # at the path below. Build succeeds with a warning if absent so this
    # build script can iterate before the PDF is finalized.
    $pdfName = "巴适声工厂隐私版使用手册_Bashi_Voice_Factory_Privacy_Edition_User_Guide.pdf"
    $pdfSrc = Join-Path $releaseDocsDir $pdfName
    if (Test-Path -LiteralPath $pdfSrc) {
        Copy-Item -LiteralPath $pdfSrc -Destination (Join-Path $StageRoot $pdfName) -Force
    } else {
        Write-Warning ("PDF user guide not found at {0} — top-level PDF will be missing from zip." -f $pdfSrc)
    }

    Remove-StagedDebris -Root $StageRoot
    Assert-LauncherCompatibility -AppDest $appDest
}

function Compress-StagedPackage {
    param(
        [Parameter(Mandatory = $true)][string]$StageRoot,
        [Parameter(Mandatory = $true)][string]$ZipPath
    )
    Assert-PathInside -Path $ZipPath -Parent $DistRoot
    if (Test-Path -LiteralPath $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }
    Compress-Archive -Path (Join-Path $StageRoot "*") -DestinationPath $ZipPath -CompressionLevel Optimal
}

if ($NoPythonOnly) {
    $stage = Join-Path $DistRoot "$PackageName-no-python"
    $zip = Join-Path $DistRoot "$PackageName-windows-no-python.zip"
    Stage-Package -StageRoot $stage
    if (-not $SkipZip) {
        Compress-StagedPackage -StageRoot $stage -ZipPath $zip
    }
    Write-Host "Prepared no-python package: $stage"
    if (-not $SkipZip) {
        Write-Host "Created: $zip"
    }
    return
}

$resolvedEmbedZip = Resolve-EmbedZip
Write-Host "Using Python embed zip: $resolvedEmbedZip"
$stage = Join-Path $DistRoot $PackageName
$zip = Join-Path $DistRoot "$PackageName-windows.zip"
Stage-Package -StageRoot $stage -EmbedZip $resolvedEmbedZip
if (-not $SkipZip) {
    Compress-StagedPackage -StageRoot $stage -ZipPath $zip
}
Write-Host "Prepared portable package: $stage"
if (-not $SkipZip) {
    Write-Host "Created: $zip"
}
