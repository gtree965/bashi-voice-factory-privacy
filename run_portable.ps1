param(
    [string]$BindHost = $env:BASHI_HOST,
    [int]$Port = $(if ($env:BASHI_PORT) { [int]$env:BASHI_PORT } else { 5050 })
)

$ErrorActionPreference = "Stop"

$AppRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PackageRoot = (Resolve-Path -LiteralPath (Join-Path $AppRoot "..")).Path
$LogFile = Join-Path $AppRoot "launch_log.txt"
$EmbedDirName = "python-3.12.10-embed-amd64"
$EmbedDir = Join-Path $AppRoot $EmbedDirName
$Python = Join-Path $EmbedDir "python.exe"
$PthFile = Join-Path $EmbedDir "python312._pth"

Set-Location $AppRoot

('[' + (Get-Date) + '] Privacy launcher started') | Set-Content -Path $LogFile -Encoding utf8
"Working directory: $AppRoot" | Add-Content -Path $LogFile -Encoding utf8

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Command
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldPreference
    }
}

function Add-PthEntry {
    param(
        [Parameter(Mandatory = $true)][string]$Entry
    )
    $resolved = [System.IO.Path]::GetFullPath($Entry)
    $lines = @(Get-Content -LiteralPath $PthFile)
    if ($lines -contains $resolved) {
        return
    }

    $importIndex = [Array]::IndexOf($lines, "import site")
    if ($importIndex -lt 0) {
        $lines += $resolved
    }
    elseif ($importIndex -eq 0) {
        $lines = @($resolved) + $lines
    }
    else {
        $lines = @($lines[0..($importIndex - 1)] + $resolved + $lines[$importIndex..($lines.Count - 1)])
    }
    Set-Content -LiteralPath $PthFile -Encoding ascii -Value $lines
}

function Configure-EmbeddedPython {
    if (-not (Test-Path -LiteralPath $Python)) {
        Write-Host '[ERROR] Portable Python runtime is missing.'
        Write-Host "        便携版 Python 运行时缺失。"
        Write-Host "Expected: $Python"
        Write-Host "This package is incomplete. Please re-extract or download it again."
        Write-Host "当前发布包不完整，请重新解压或重新下载。"
        Read-Host "Press Enter to exit / 按回车退出"
        exit 1
    }
    if (-not (Test-Path -LiteralPath $PthFile)) {
        Write-Host ('[ERROR] Embedded Python path file is missing: {0}' -f $PthFile)
        Write-Host "        便携版 Python 路径配置文件缺失。"
        Read-Host "Press Enter to exit / 按回车退出"
        exit 1
    }

    (Get-Content -LiteralPath $PthFile) -replace '^#import site', 'import site' |
        Set-Content -LiteralPath $PthFile -Encoding ascii

    Add-PthEntry -Entry $AppRoot
    Add-PthEntry -Entry (Join-Path $PackageRoot "vulkan_backend_spike\Qwen3-TTS-GGUF")
}

function Ensure-Pip {
    $pipCheckExit = Invoke-NativeCommand { & $Python -m pip --version *> $null }
    if ($pipCheckExit -eq 0) {
        return
    }

    Write-Host ""
    Write-Host '[INFO] Initializing portable pip...'
    Write-Host '[INFO] 正在初始化便携版 pip...'
    '[STEP] Bootstrap pip' | Add-Content -Path $LogFile -Encoding utf8

    $tmpDir = Join-Path $AppRoot ".tmp"
    New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
    $getPip = Join-Path $tmpDir "get-pip.py"
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip -UseBasicParsing -ErrorAction Stop
    $pipBootstrapExit = Invoke-NativeCommand { & $Python $getPip --no-warn-script-location @pipArgs *>> $LogFile }
    if ($pipBootstrapExit -ne 0) {
        Write-Host '[ERROR] Failed to initialize pip.'
        Write-Host "        pip 初始化失败。"
        Write-Host "Check launch_log.txt for details."
        Write-Host "请查看 launch_log.txt 了解详情。"
        Read-Host "Press Enter to exit / 按回车退出"
        exit 1
    }
}

Write-Host "========================================================"
Write-Host " Bashi Voice Factory Privacy Edition"
Write-Host " 巴适声工厂隐私版"
Write-Host "========================================================"
Write-Host ""
Write-Host "First launch downloads ~700 MB dependencies + ~2.2 GB GGUF model."
Write-Host "首次启动需要下载约 700 MB 依赖 + 2.2 GB GGUF 模型。"
Write-Host "Typical first launch time: about 15-25 minutes, depending on network speed."
Write-Host "首次启动通常约 15-25 分钟，具体取决于网速。"
Write-Host "Press Ctrl+C to cancel; restart reuses completed files where possible."
Write-Host "可按 Ctrl+C 取消；重新启动会尽量复用已完成的文件。"
Write-Host ""

Configure-EmbeddedPython

$pipArgs = @()
$timeZone = (Get-TimeZone).Id
$culture = [System.Globalization.CultureInfo]::CurrentCulture.Name
if ($timeZone -like "*China*" -or $culture -like "zh-*") {
    Write-Host '[INFO] 检测到中国时区/语言环境，将使用阿里云镜像加速 pip 下载。'
    Write-Host '[INFO] China timezone/locale detected. Using Aliyun pip mirror.'
    $pipArgs = @("-i", "https://mirrors.aliyun.com/pypi/simple/", "--trusted-host", "mirrors.aliyun.com")
}

Ensure-Pip

$dependencyCheckCode = 'import importlib.metadata as m; [m.version(p) for p in ("Flask","imageio-ffmpeg","sherpa-onnx","gguf","onnx","onnxruntime-directml","sentencepiece","sounddevice","torch","transformers","qwen-tts")]'
$dependencyCheckExit = Invoke-NativeCommand { & $Python -c $dependencyCheckCode *> $null }
if ($dependencyCheckExit -ne 0) {
    Write-Host ""
    Write-Host '[INFO] Installing or repairing dependencies. This usually takes 8-10 minutes on a good connection.'
    Write-Host '[INFO] 正在安装或修复依赖。网络顺畅时通常需要 8-10 分钟。'
    '[STEP] pip install -r requirements.txt' | Add-Content -Path $LogFile -Encoding utf8

    $pipInstallExit = Invoke-NativeCommand { & $Python -m pip install -r requirements.txt --prefer-binary --no-warn-script-location @pipArgs *>> $LogFile }
    if ($pipInstallExit -ne 0) {
        Write-Host '[WARN] First install attempt failed, retrying without cache...'
        Write-Host "       首次安装失败，正在清除缓存重试..."
        $pipRetryExit = Invoke-NativeCommand { & $Python -m pip install -r requirements.txt --prefer-binary --no-cache-dir --no-warn-script-location @pipArgs *>> $LogFile }
        if ($pipRetryExit -ne 0) {
            Write-Host '[ERROR] Failed to install dependencies from requirements.txt.'
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
    '[STEP] Checking GGUF runtime model pack' | Add-Content -Path $LogFile -Encoding utf8
    $modelCheckExit = Invoke-NativeCommand { & $Python $ModelDownloadScript --check-only *>> $LogFile }
    if ($modelCheckExit -ne 0) {
        Write-Host ""
        Write-Host '[WARN] GGUF runtime model pack is missing or incomplete.'
        Write-Host "       未检测到完整 GGUF 运行模型包。"
        Write-Host "       First model download is about 2.2 GiB and can take 5-15 minutes."
        Write-Host "       首次模型下载约 2.2 GiB，通常需要 5-15 分钟。"
        Write-Host "       After that, synthesis runs offline."
        Write-Host "       下载完成后，语音合成可本地离线运行。"
        Write-Host ""
        $modelChoice = Read-Host "Download GGUF model from ModelScope now? / 现在从 ModelScope 下载 GGUF 模型？ [y/N]"
        if ($modelChoice -match "^[Yy]$") {
            Write-Host ""
            Write-Host '[INFO] Downloading GGUF runtime model pack...'
            Write-Host '[INFO] 正在下载 GGUF 运行模型包...'
            '[STEP] download_gguf_model.py' | Add-Content -Path $LogFile -Encoding utf8
            $modelDownloadExit = Invoke-NativeCommand { & $Python $ModelDownloadScript *>> $LogFile }
            if ($modelDownloadExit -ne 0) {
                Write-Host '[WARN] GGUF model download did not complete.'
                Write-Host "       GGUF 模型下载未完成。"
                Write-Host "       The app will continue to start; you can retry later."
                Write-Host "       程序将继续启动；你可以稍后重试下载。"
                Write-Host "       See launch_log.txt for details."
                Write-Host "       详情请查看 launch_log.txt。"
            }
            else {
                Write-Host '[OK] GGUF runtime model pack is ready.'
                Write-Host '[OK] GGUF 运行模型包已就绪。'
            }
        }
        else {
            Write-Host '[INFO] Skipping GGUF model download for now.'
            Write-Host '[INFO] 暂时跳过 GGUF 模型下载。'
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
    Write-Host '[Y] Yes / 允许 (Host on 0.0.0.0)'
    Write-Host '[N] No / 拒绝 (Host on 127.0.0.1 - Default / 默认)'
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

('[STEP] Starting app.py with host={0} port={1}' -f $BindHost, $Port) | Add-Content -Path $LogFile -Encoding utf8
$pythonCommand = "`"$Python`" app.py --host `"$BindHost`" --port `"$Port`" 2>> `"$LogFile`""
$exitCode = Invoke-NativeCommand { & cmd.exe /d /c $pythonCommand }
('[DONE] app.py exited with code {0}' -f $exitCode) | Add-Content -Path $LogFile -Encoding utf8

Write-Host ""
Write-Host "App exited. (Exit code: $exitCode)"
Write-Host "程序已退出。（退出代码: $exitCode）"
Write-Host "If the app crashed, check launch_log.txt for details."
Write-Host "如果程序异常退出，请查看 launch_log.txt 了解详情。"
Read-Host "Press Enter to exit / 按回车退出"
exit $exitCode
