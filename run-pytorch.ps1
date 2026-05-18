param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 5050
)

$ErrorActionPreference = "Stop"

$AppRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $AppRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Missing PyTorch app environment: $Python"
}

Set-Location $AppRoot

$env:USE_PYTORCH_BACKEND = "1"
if (Test-Path Env:USE_GGUF_BACKEND) {
    Remove-Item Env:USE_GGUF_BACKEND
}

Write-Host "Launcher pinned backend: pytorch"
Write-Host "Starting full app with $Python on http://$BindHost`:$Port"

& $Python ".\app.py" --host $BindHost --port $Port
