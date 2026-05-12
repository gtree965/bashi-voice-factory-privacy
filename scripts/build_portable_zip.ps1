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

    foreach ($dir in @("bashi_tts_kernel", "engines", "templates", "static\css", "static\images", "static\js", "static\audio\style_previews")) {
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
