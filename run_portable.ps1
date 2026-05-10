param(
    [string]$BindHost = $env:BASHI_HOST,
    [int]$Port = $(if ($env:BASHI_PORT) { [int]$env:BASHI_PORT } else { 5050 })
)

$ErrorActionPreference = "Stop"

$AppRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogFile = Join-Path $AppRoot "launch_log.txt"
$VenvDir = Join-Path $AppRoot ".venv"
$Python = Join-Path $VenvDir "Scripts\python.exe"

Set-Location $AppRoot

"[$(Get-Date)] Privacy launcher started" | Set-Content -Path $LogFile -Encoding utf8
"Working directory: $AppRoot" | Add-Content -Path $LogFile -Encoding utf8

Write-Host "========================================================"
Write-Host " Bashi Voice Factory Privacy Edition"
Write-Host " 巴适声工厂隐私版"
Write-Host "========================================================"
Write-Host ""

if (-not (Test-Path $Python)) {
    Write-Host "[INFO] Local .venv not found. Creating it now..."
    Write-Host "[INFO] 未找到本地 .venv，正在创建..."
    "[STEP] Creating .venv" | Add-Content -Path $LogFile -Encoding utf8

    $pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pythonLauncher) {
        & py -3.10 -m venv $VenvDir *>> $LogFile
    }
    else {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if (-not $pythonCommand) {
            Write-Host "[ERROR] Python 3.10+ was not found."
            Write-Host "        找不到 Python 3.10 或更高版本。"
            Write-Host "Please install Python first, then rerun this launcher."
            Write-Host "请先安装 Python，然后重新运行本启动器。"
            Read-Host "Press Enter to exit / 按回车退出"
            exit 1
        }
        & python -m venv $VenvDir *>> $LogFile
    }
}

if (-not (Test-Path $Python)) {
    Write-Host "[ERROR] Failed to create local .venv."
    Write-Host "        创建本地 .venv 失败。"
    Write-Host "Check launch_log.txt for details."
    Write-Host "请查看 launch_log.txt 了解详情。"
    Read-Host "Press Enter to exit / 按回车退出"
    exit 1
}

$pipArgs = @()
$timeZone = (Get-TimeZone).Id
$culture = [System.Globalization.CultureInfo]::CurrentCulture.Name
if ($timeZone -like "*China*" -or $culture -like "zh-*") {
    Write-Host "[INFO] 检测到中国时区/语言环境，将使用阿里云镜像加速 pip 下载。"
    Write-Host "[INFO] China timezone/locale detected. Using Aliyun pip mirror."
    $pipArgs = @("-i", "https://mirrors.aliyun.com/pypi/simple/", "--trusted-host", "mirrors.aliyun.com")
}

& $Python -c "import importlib.metadata as m; [m.version(p) for p in ['Flask','imageio-ffmpeg','sherpa-onnx','gguf','onnxruntime-directml','sentencepiece','torch','transformers','qwen-tts']]" *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[INFO] Installing or repairing dependencies. This can take a while."
    Write-Host "[INFO] 正在安装或修复依赖，首次运行可能需要较长时间。"
    "[STEP] pip install -r requirements.txt" | Add-Content -Path $LogFile -Encoding utf8

    & $Python -m ensurepip --upgrade *>> $LogFile
    & $Python -m pip install -r requirements.txt --prefer-binary --no-warn-script-location @pipArgs *>> $LogFile
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARN] First install attempt failed, retrying without cache..."
        Write-Host "       首次安装失败，正在清除缓存重试..."
        & $Python -m pip install -r requirements.txt --prefer-binary --no-cache-dir --no-warn-script-location @pipArgs *>> $LogFile
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Failed to install dependencies from requirements.txt."
            Write-Host "        依赖组件安装失败。"
            Write-Host "Check launch_log.txt for details."
            Write-Host "请查看 launch_log.txt 了解详情。"
            Read-Host "Press Enter to exit / 按回车退出"
            exit 1
        }
    }
}

$ModelDownloadScript = Join-Path $AppRoot "download_gguf_model.py"
if (Test-Path $ModelDownloadScript) {
    "[STEP] Checking GGUF runtime model pack" | Add-Content -Path $LogFile -Encoding utf8
    & $Python $ModelDownloadScript --check-only *>> $LogFile
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "[WARN] GGUF runtime model pack is missing or incomplete."
        Write-Host "       未检测到完整 GGUF 运行模型包。"
        Write-Host "       First download is about 2.2 GiB. After that, synthesis can run offline."
        Write-Host "       首次下载约 2.2 GiB；下载完成后，语音合成可本地离线运行。"
        Write-Host ""
        $modelChoice = Read-Host "Download GGUF model from ModelScope now? / 现在从 ModelScope 下载 GGUF 模型？ [y/N]"
        if ($modelChoice -match "^[Yy]$") {
            Write-Host ""
            Write-Host "[INFO] Downloading GGUF runtime model pack..."
            Write-Host "[INFO] 正在下载 GGUF 运行模型包..."
            "[STEP] download_gguf_model.py" | Add-Content -Path $LogFile -Encoding utf8
            & $Python $ModelDownloadScript *>> $LogFile
            if ($LASTEXITCODE -ne 0) {
                Write-Host "[WARN] GGUF model download did not complete."
                Write-Host "       GGUF 模型下载未完成。"
                Write-Host "       The app will continue to start; you can retry later."
                Write-Host "       程序将继续启动；你可以稍后重试下载。"
                Write-Host "       See launch_log.txt for details."
                Write-Host "       详情请查看 launch_log.txt。"
            }
            else {
                Write-Host "[OK] GGUF runtime model pack is ready."
                Write-Host "[OK] GGUF 运行模型包已就绪。"
            }
        }
        else {
            Write-Host "[INFO] Skipping GGUF model download for now."
            Write-Host "[INFO] 暂时跳过 GGUF 模型下载。"
        }
    }
}

Remove-Item Env:USE_GGUF_BACKEND -ErrorAction SilentlyContinue
Remove-Item Env:USE_PYTORCH_BACKEND -ErrorAction SilentlyContinue

if (-not $BindHost) {
    Write-Host ""
    Write-Host "========================================================"
    Write-Host "DO YOU WANT TO ALLOW OTHER DEVICES ON YOUR NETWORK TO ACCESS THIS SERVER?"
    Write-Host "是否允许局域网内其他设备（如手机、平板）访问本服务器？"
    Write-Host "[Y] Yes / 允许 (Host on 0.0.0.0)"
    Write-Host "[N] No / 拒绝 (Host on 127.0.0.1 - Default / 默认)"
    Write-Host "========================================================"
    $choice = Read-Host "Select / 请选择 [y/N]"
    $BindHost = if ($choice -match "^[Yy]$") { "0.0.0.0" } else { "127.0.0.1" }
}

Write-Host ""
Write-Host "Starting Bashi Voice Factory Privacy Edition..."
Write-Host "正在启动巴适声工厂隐私版..."
Write-Host "Backend: automatic selector / 后端：自动选择"
Write-Host ""

if ($BindHost -eq "0.0.0.0") {
    $localIp = (
        Get-NetIPConfiguration -ErrorAction SilentlyContinue |
            Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
            Select-Object -ExpandProperty IPv4Address -First 1
    ).IPAddress
    if (-not $localIp) {
        $localIp = "YOUR_LOCAL_IP"
    }
    Write-Host "--------------------------------------------------------"
    Write-Host "Server is accessible from other devices at:"
    Write-Host "可以从局域网其他设备访问此地址:"
    Write-Host "http://${localIp}:$Port"
    Write-Host "--------------------------------------------------------"
}
else {
    Write-Host "--------------------------------------------------------"
    Write-Host "Server is running locally. Access it at:"
    Write-Host "服务器运行在本地模式。请访问:"
    Write-Host "http://127.0.0.1:$Port"
    Write-Host "--------------------------------------------------------"
}

Write-Host ""
Write-Host "Press Ctrl+C to stop the server."
Write-Host "按 Ctrl+C 可停止服务器。"
Write-Host ""

"[STEP] Starting app.py with host=$BindHost port=$Port" | Add-Content -Path $LogFile -Encoding utf8
$pythonCommand = "`"$Python`" app.py --host `"$BindHost`" --port `"$Port`" 2>> `"$LogFile`""
& cmd.exe /d /c $pythonCommand
$exitCode = $LASTEXITCODE
"[DONE] app.py exited with code $exitCode" | Add-Content -Path $LogFile -Encoding utf8

Write-Host ""
Write-Host "App exited. (Exit code: $exitCode)"
Write-Host "程序已退出。（退出代码: $exitCode）"
Write-Host "If the app crashed, check launch_log.txt for details."
Write-Host "如果程序异常退出，请查看 launch_log.txt 了解详情。"
Read-Host "Press Enter to exit / 按回车退出"
exit $exitCode
