param(
    [string]$SourceEmbedDir = "",
    [string]$SourceEmbedZip = "",
    [string]$WorkDir = (Join-Path $env:TEMP "bashi-privacy-py312-embed-precheck"),
    [ValidateSet("pypi", "aliyun")]
    [string]$Index = "pypi",
    [switch]$KeepExisting,
    [switch]$RunSynthesisSmoke
)

$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppRoot = (Resolve-Path -LiteralPath (Join-Path $ScriptRoot "..")).Path
$WorkspaceRoot = (Resolve-Path -LiteralPath (Join-Path $AppRoot "..")).Path

if (-not $SourceEmbedDir -and -not $SourceEmbedZip) {
    $SourceEmbedZip = Join-Path $WorkspaceRoot "python-3.12.10-embed-amd64.zip"
}

if ($SourceEmbedDir -and -not (Test-Path -LiteralPath (Join-Path $SourceEmbedDir "python.exe"))) {
    throw "Missing source embed python.exe: $SourceEmbedDir"
}
if ($SourceEmbedZip -and -not (Test-Path -LiteralPath $SourceEmbedZip)) {
    throw "Missing source embed zip: $SourceEmbedZip"
}
if (-not $SourceEmbedDir -and -not $SourceEmbedZip) {
    throw "Provide SourceEmbedZip or SourceEmbedDir."
}

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

function Invoke-Logged {
    param(
        [Parameter(Mandatory = $true)][string]$Step,
        [Parameter(Mandatory = $true)][string]$LogPath,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )
    Write-Host ""
    Write-Host "== $Step =="
    $started = Get-Date
    & $Command *> $LogPath
    $code = $LASTEXITCODE
    $elapsed = (Get-Date) - $started
    if ($code -ne 0) {
        Write-Host "FAILED: $Step ($([math]::Round($elapsed.TotalSeconds, 1))s)"
        Write-Host "Log tail: $LogPath"
        Get-Content -LiteralPath $LogPath -Tail 120
        exit $code
    }
    Write-Host "OK: $Step ($([math]::Round($elapsed.TotalSeconds, 1))s)"
    Get-Content -LiteralPath $LogPath -Tail 20
}

function Add-PthEntry {
    param(
        [Parameter(Mandatory = $true)][string]$PthFile,
        [Parameter(Mandatory = $true)][string]$Entry
    )
    $resolved = (Resolve-Path -LiteralPath $Entry).Path
    $lines = @(Get-Content -LiteralPath $PthFile)
    if ($lines -notcontains $resolved) {
        $insertAt = [Math]::Max(0, $lines.IndexOf("import site"))
        if ($insertAt -eq 0 -and $lines[0] -ne "import site") {
            $lines += $resolved
        }
        else {
            $lines = @($lines[0..($insertAt - 1)] + $resolved + $lines[$insertAt..($lines.Count - 1)])
        }
        Set-Content -LiteralPath $PthFile -Encoding ascii -Value $lines
    }
}

$indexArgs = @()
if ($Index -eq "aliyun") {
    $indexArgs = @("-i", "https://mirrors.aliyun.com/pypi/simple/", "--trusted-host", "mirrors.aliyun.com")
}
else {
    $indexArgs = @("-i", "https://pypi.org/simple")
}

$workParent = Split-Path -Parent $WorkDir
if (-not (Test-Path -LiteralPath $workParent)) {
    New-Item -ItemType Directory -Force -Path $workParent | Out-Null
}

Assert-PathInside -Path $WorkDir -Parent $workParent
if ((Test-Path -LiteralPath $WorkDir) -and -not $KeepExisting) {
    Remove-Item -LiteralPath $WorkDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

if ($SourceEmbedZip) {
    Write-Host "Source zip:   $SourceEmbedZip"
}
if ($SourceEmbedDir) {
    Write-Host "Source embed: $SourceEmbedDir"
}
Write-Host "Work dir:     $WorkDir"
Write-Host "Index:        $Index"

if (-not $KeepExisting) {
    if ($SourceEmbedZip) {
        Expand-Archive -LiteralPath $SourceEmbedZip -DestinationPath $WorkDir -Force
    }
    else {
        Get-ChildItem -LiteralPath $SourceEmbedDir -File -Force |
            Copy-Item -Destination $WorkDir -Force
    }
}

$pthFile = Join-Path $WorkDir "python312._pth"
if (-not (Test-Path -LiteralPath $pthFile)) {
    throw "Missing python312._pth in work dir."
}
(Get-Content -LiteralPath $pthFile) -replace '^#import site', 'import site' |
    Set-Content -LiteralPath $pthFile -Encoding ascii
Add-PthEntry -PthFile $pthFile -Entry $AppRoot
Add-PthEntry -PthFile $pthFile -Entry (Join-Path $WorkspaceRoot "vulkan_backend_spike\Qwen3-TTS-GGUF")

$python = Join-Path $WorkDir "python.exe"
& $python --version

$getPip = Join-Path $WorkDir "get-pip.py"
if (-not (Test-Path -LiteralPath (Join-Path $WorkDir "Lib\site-packages\pip"))) {
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip -UseBasicParsing -ErrorAction Stop
    Invoke-Logged -Step "bootstrap pip" -LogPath (Join-Path $WorkDir "01-get-pip.log") -Command {
        & $python $getPip --no-warn-script-location @indexArgs
    }
}
else {
    Write-Host "pip already present; skipping bootstrap."
}

Invoke-Logged -Step "install build tooling" -LogPath (Join-Path $WorkDir "01b-build-tooling.log") -Command {
    & $python -m pip install setuptools==79.0.1 wheel==0.45.1 --prefer-binary --no-warn-script-location --progress-bar off --timeout 120 --retries 3 @indexArgs
}

Invoke-Logged -Step "install requirements" -LogPath (Join-Path $WorkDir "02-pip-install.log") -Command {
    & $python -m pip install -r (Join-Path $AppRoot "requirements.txt") --no-build-isolation --prefer-binary --no-warn-script-location --progress-bar off --timeout 120 --retries 3 @indexArgs
}

Invoke-Logged -Step "install qwen-tts without dependencies" -LogPath (Join-Path $WorkDir "02b-qwen-tts-no-deps.log") -Command {
    & $python -m pip install qwen-tts==0.1.1 --no-deps --prefer-binary --no-warn-script-location --progress-bar off --timeout 120 --retries 3 @indexArgs
}

Invoke-Logged -Step "restore DirectML package files last" -LogPath (Join-Path $WorkDir "02c-directml-force-reinstall.log") -Command {
    & $python -m pip install --force-reinstall --no-deps onnxruntime-directml==1.23.0 --prefer-binary --no-warn-script-location --progress-bar off --timeout 120 --retries 3 @indexArgs
}

Invoke-Logged -Step "pip check" -LogPath (Join-Path $WorkDir "03-pip-check.log") -Command {
    $pipCheckOutput = @(& $python -m pip check 2>&1)
    $pipCheckOutput | Write-Output
    $unexpected = @($pipCheckOutput | Where-Object {
        $_ -and $_ -notmatch '(?i)^qwen-tts .*requires (gradio|onnxruntime), which is not installed'
    })
    if ($unexpected.Count -gt 0) {
        & $python -c "raise SystemExit(1)"
    }
    else {
        Write-Output "Accepted: DirectML supplies onnxruntime; gradio is only used by the unbundled qwen_tts CLI demo."
        & $python -c "raise SystemExit(0)"
    }
}

Invoke-Logged -Step "import smoke" -LogPath (Join-Path $WorkDir "04-import-smoke.log") -Command {
    & $python -c "import flask, gguf, onnx, onnxruntime, sentencepiece, sounddevice, torch, transformers, qwen_tts; print('imports ok')"
}

Invoke-Logged -Step "DML provider check" -LogPath (Join-Path $WorkDir "04b-dml-provider-check.log") -Command {
    & $python -c "import onnxruntime as ort; ps=ort.get_available_providers(); assert 'DmlExecutionProvider' in ps, f'Missing DML: {ps}'; print(ps)"
}

Invoke-Logged -Step "ETA unit test" -LogPath (Join-Path $WorkDir "05-eta-unittest.log") -Command {
    & $python -m unittest discover -s (Join-Path $AppRoot "tests") -p "test_phase5_eta_routes.py"
}

if ($RunSynthesisSmoke) {
    Invoke-Logged -Step "GGUF synthesis smoke" -LogPath (Join-Path $WorkDir "06-synthesis-smoke.log") -Command {
        $env:USE_GGUF_BACKEND = "1"
        $env:GGUF_TTS_MODEL_DIR = "$WorkspaceRoot\vulkan_backend_spike\Qwen3-TTS-GGUF\model-custom"
        & $python -c "from local_tts_engine_gguf import LocalTTSService; e=LocalTTSService(); p=e.synthesize_text('今天的工作流程比预期顺利。', voice_id='uncle_fu'); print(p); e.shutdown()"
    }
}

Write-Host ""
Write-Host "Python 3.12 embed precheck passed."
Write-Host "Logs: $WorkDir"
