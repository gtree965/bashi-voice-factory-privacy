param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 5050
)

$ErrorActionPreference = "Stop"

$AppRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $AppRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Missing unified app environment: $Python"
}

Set-Location $AppRoot

$ModelDownloadScript = Join-Path $AppRoot "download_gguf_model.py"
if (Test-Path $ModelDownloadScript) {
    & $Python $ModelDownloadScript --check-only *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARN] GGUF runtime model pack is missing or incomplete."
        Write-Host "       未检测到完整 GGUF 运行模型包。"
        Write-Host "       First download is about 2.2 GiB. After that, synthesis can run offline."
        Write-Host "       首次下载约 2.2 GiB；下载完成后，语音合成可本地离线运行。"
        $modelChoice = Read-Host "Download GGUF model from ModelScope now? / 现在从 ModelScope 下载 GGUF 模型？ [y/N]"
        if ($modelChoice -match "^[Yy]$") {
            & $Python $ModelDownloadScript
            if ($LASTEXITCODE -ne 0) {
                throw "GGUF model download did not complete. Retry later or use BASHI_GGUF_FILESFM_URL fallback."
            }
        }
        else {
            throw "GGUF model is required when launcher is pinned to GGUF."
        }
    }
}

$env:USE_GGUF_BACKEND = "1"
if (Test-Path Env:USE_PYTORCH_BACKEND) {
    Remove-Item Env:USE_PYTORCH_BACKEND
}

Write-Host "Launcher pinned backend: gguf"
Write-Host "Starting full app with $Python on http://$BindHost`:$Port"

& $Python ".\app.py" --host $BindHost --port $Port
