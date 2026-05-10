param(
    [string]$Version = "",
    [string]$PythonEmbedDir = "",
    [switch]$NoPythonOnly,
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppRoot = (Resolve-Path -LiteralPath (Join-Path $ScriptRoot "..")).Path
$WorkspaceRoot = (Resolve-Path -LiteralPath (Join-Path $AppRoot "..")).Path
$DistRoot = Join-Path $AppRoot "dist"

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
            $_.Name -like "*.pyc" -or
            $_.Name -like "*.pyo" -or
            $_.Name -like "*.log" -or
            $_.Name -like "*.odt" -or
            $_.Name -like ".~lock.*#"
        } |
        ForEach-Object {
            Assert-PathInside -Path $_.FullName -Parent $Root
            Remove-Item -LiteralPath $_.FullName -Force
        }
}

function Stage-Package {
    param(
        [Parameter(Mandatory = $true)][string]$StageRoot,
        [string]$EmbedDir = ""
    )

    New-CleanDirectory -Path $StageRoot

    $appDest = Join-Path $StageRoot "bashi-privacy-app"
    $kernelDest = Join-Path $StageRoot "LocalBashiVoiceFactory"
    $ggufDest = Join-Path $StageRoot "vulkan_backend_spike\Qwen3-TTS-GGUF"

    New-Item -ItemType Directory -Force -Path $appDest, $kernelDest, $ggufDest | Out-Null

    $appFiles = @(
        ".gitignore",
        "app.py",
        "audio_encoding.py",
        "backend_probe.py",
        "download_gguf_model.py",
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
        "stt_engine.py",
        "stt_routes.py",
        "SYSTEM_OVERVIEW.md",
        "tts_routes.py",
        "utils.py",
        "VERSION"
    )
    foreach ($file in $appFiles) {
        Copy-RelativeFile -SourceRoot $AppRoot -RelativePath $file -DestRoot $appDest
    }

    foreach ($dir in @("engines", "scripts", "templates", "static\css", "static\images", "static\js", "static\audio\style_previews")) {
        Copy-RelativeDirectory -SourceRoot $AppRoot -RelativePath $dir -DestRoot $appDest
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $appDest "models"), (Join-Path $appDest "static\audio"), (Join-Path $appDest "static\uploads") | Out-Null

    foreach ($file in @("bashi_tts_core.py", "download_model.py", "README.md", "requirements.txt", "speakers.json", "zh_normalizer_lite.py")) {
        Copy-RelativeFile -SourceRoot (Join-Path $WorkspaceRoot "LocalBashiVoiceFactory") -RelativePath $file -DestRoot $kernelDest
    }

    $ggufSource = Join-Path $WorkspaceRoot "vulkan_backend_spike\Qwen3-TTS-GGUF"
    Copy-RelativeFile -SourceRoot $ggufSource -RelativePath "requirements.txt" -DestRoot $ggufDest
    Copy-RelativeFile -SourceRoot $ggufSource -RelativePath "readme.md" -DestRoot $ggufDest
    Copy-RelativeFile -SourceRoot $ggufSource -RelativePath "qwen3_tts_gguf\__init__.py" -DestRoot $ggufDest
    Copy-RelativeDirectory -SourceRoot $ggufSource -RelativePath "qwen3_tts_gguf\inference" -DestRoot $ggufDest
    New-Item -ItemType Directory -Force -Path (Join-Path $ggufDest "model-custom") | Out-Null

    if ($EmbedDir) {
        $resolvedEmbed = (Resolve-Path -LiteralPath $EmbedDir).Path
        Copy-Item -LiteralPath $resolvedEmbed -Destination (Join-Path $appDest (Split-Path -Leaf $resolvedEmbed)) -Recurse -Force
    }

    Remove-StagedDebris -Root $StageRoot
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

$candidateEmbedDirs = @()
if ($PythonEmbedDir) {
    $candidateEmbedDirs += $PythonEmbedDir
}
$candidateEmbedDirs += (Join-Path $AppRoot "python-3.12.10-embed-amd64")
$candidateEmbedDirs += (Join-Path $WorkspaceRoot "python-3.12.10-embed-amd64")
$resolvedEmbedDir = $candidateEmbedDirs | Where-Object { $_ -and (Test-Path -LiteralPath (Join-Path $_ "python.exe")) } | Select-Object -First 1

$noPythonStage = Join-Path $DistRoot $PackageName
$noPythonZip = Join-Path $DistRoot "$PackageName-windows-no-python.zip"
Stage-Package -StageRoot $noPythonStage
if (-not $SkipZip) {
    Compress-StagedPackage -StageRoot $noPythonStage -ZipPath $noPythonZip
}
Write-Host "Prepared no-python package: $noPythonStage"
if (-not $SkipZip) {
    Write-Host "Created: $noPythonZip"
}

if (-not $NoPythonOnly) {
    if ($resolvedEmbedDir) {
        $withPythonStage = Join-Path $DistRoot "$PackageName-python"
        $withPythonZip = Join-Path $DistRoot "$PackageName-windows.zip"
        Stage-Package -StageRoot $withPythonStage -EmbedDir $resolvedEmbedDir
        if (-not $SkipZip) {
            Compress-StagedPackage -StageRoot $withPythonStage -ZipPath $withPythonZip
        }
        Write-Host "Prepared with-python package: $withPythonStage"
        if (-not $SkipZip) {
            Write-Host "Created: $withPythonZip"
        }
    }
    else {
        Write-Host "Portable Python embed folder not found; skipped with-python package."
        Write-Host "Expected python.exe under python-3.12.10-embed-amd64."
    }
}
