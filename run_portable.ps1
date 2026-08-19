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
$pipBackoffSeconds = @(5, 30, 120)
$chinaPipIndexUrls = @(
    "https://mirrors.aliyun.com/pypi/simple/",
    "https://pypi.tuna.tsinghua.edu.cn/simple/",
    "https://pypi.org/simple/"
)
$officialPipIndexUrl = "https://pypi.org/simple/"

function Test-LocalPortListening {
    param([Parameter(Mandatory = $true)][int]$TargetPort)

    $client = New-Object System.Net.Sockets.TcpClient
    $connection = $null
    try {
        $connection = $client.BeginConnect("127.0.0.1", $TargetPort, $null, $null)
        if (-not $connection.AsyncWaitHandle.WaitOne(500)) {
            return $false
        }
        $client.EndConnect($connection)
        return $client.Connected
    }
    catch {
        return $false
    }
    finally {
        if ($null -ne $connection) {
            $connection.AsyncWaitHandle.Close()
        }
        $client.Close()
    }
}

Set-Location $AppRoot

$existingAppUrl = "http://127.0.0.1:$Port"
if (Test-LocalPortListening -TargetPort $Port) {
    $earlyExitTimestamp = (Get-Date).ToString(
        "yyyy-MM-dd HH:mm:ss",
        [Globalization.CultureInfo]::InvariantCulture
    )
    $earlyExitLogLine = '[{0}] [INFO] Port {1} already in use; existing instance detected, launcher exited early.' -f $earlyExitTimestamp, $Port
    try {
        $earlyExitLogLine | Add-Content -Path $LogFile -Encoding utf8 -ErrorAction Stop
    }
    catch {
        Write-Host "[WARN] Could not append the early-exit event to launch_log.txt because the file is busy."
        Write-Host "[WARN] launch_log.txt 正在使用中，无法追加本次提前退出记录。"
    }
    Write-Host "[INFO] Port $Port is already in use. Another copy of this app is very likely running."
    Write-Host "[INFO] 端口 $Port 已被占用，很可能已有本应用的另一个副本正在运行。"
    Write-Host "[INFO] Existing address: $existingAppUrl"
    Write-Host "[INFO] 已有实例地址：$existingAppUrl"
    Read-Host "Press Enter to exit / 按回车退出"
    exit 0
}

$env:BASHI_LAUNCH_EPOCH = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
('[' + (Get-Date) + '] Privacy launcher started') | Set-Content -Path $LogFile -Encoding utf8
"Working directory: $AppRoot" | Add-Content -Path $LogFile -Encoding utf8

$userPipConfig = if ($env:APPDATA) { Join-Path $env:APPDATA "pip\pip.ini" } else { $null }
if ($userPipConfig -and (Test-Path -LiteralPath $userPipConfig)) {
    $userPipConfigText = Get-Content -LiteralPath $userPipConfig -Raw -ErrorAction SilentlyContinue
    if ($userPipConfigText -match '(?im)^\s*index-url\s*=') {
        '[INFO] Detected user-level pip configuration; ignored for this install (--isolated).' | Add-Content -Path $LogFile -Encoding utf8
        Write-Host '[INFO] Detected user-level pip configuration; ignored for this install (--isolated).'
        Write-Host '[INFO] 检测到用户级 pip 配置，已在本次安装中忽略（--isolated）。'
    }
}

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

function ConvertTo-NativeOutputLine {
    param(
        [AllowNull()][object]$InputObject
    )
    if ($InputObject -is [System.Management.Automation.ErrorRecord]) {
        return $InputObject.Exception.Message
    }
    if ($null -eq $InputObject) {
        return ""
    }
    return $InputObject.ToString()
}

function Invoke-NativeCommandCapture {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Command,
        [switch]$WriteToHost,
        [switch]$WriteToLog
    )
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $lines = [System.Collections.Generic.List[string]]::new()
    try {
        & $Command 2>&1 | ForEach-Object {
            $line = ConvertTo-NativeOutputLine -InputObject $_
            [void]$lines.Add($line)
            if ($WriteToHost) {
                Write-Host $line
            }
            if ($WriteToLog) {
                Add-Content -Path $LogFile -Encoding utf8 -Value $line
            }
        }
        $exitCode = $LASTEXITCODE
        return [pscustomobject]@{
            ExitCode = $exitCode
            Lines = @($lines)
        }
    }
    finally {
        $ErrorActionPreference = $oldPreference
    }
}

function Invoke-NativeCommandWithUtf8Log {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )
    $result = Invoke-NativeCommandCapture -Command $Command -WriteToHost -WriteToLog
    return $result.ExitCode
}

function Get-PipIndexArguments {
    param([Parameter(Mandatory = $true)][string]$IndexUrl)

    $uri = [System.Uri]$IndexUrl
    if (-not $uri.IsAbsoluteUri -or $uri.Scheme -notin @("http", "https") -or -not $uri.Host) {
        throw "Invalid pip index URL: $IndexUrl"
    }
    return @("-i", $uri.AbsoluteUri, "--trusted-host", $uri.Host)
}

function Read-LanBindHost {
    param(
        [int]$TimeoutSeconds = 10,
        [scriptblock]$KeyAvailable = { [Console]::KeyAvailable },
        [scriptblock]$ReadKey = { [Console]::ReadKey($true).KeyChar },
        [scriptblock]$Wait = { param([int]$Milliseconds) Start-Sleep -Milliseconds $Milliseconds }
    )

    $selectedHost = "127.0.0.1"
    try {
        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        while ((Get-Date) -lt $deadline) {
            if (& $KeyAvailable) {
                $key = & $ReadKey
                if ($key -match '^[Yy]$') {
                    $selectedHost = "0.0.0.0"
                }
                break
            }
            & $Wait 200
        }
    }
    catch {
        # Redirected stdin and hosts without a console safely keep the default.
    }
    return $selectedHost
}

function Set-PortablePthEntries {
    $portableAppEntry = ".."
    $portableGgufEntry = "..\..\vulkan_backend_spike\Qwen3-TTS-GGUF"
    $sourceLines = @(
        (Get-Content -LiteralPath $PthFile) -replace '^#import site$', 'import site'
    )
    $cleanLines = New-Object System.Collections.Generic.List[string]

    foreach ($line in $sourceLines) {
        $trimmed = $line.Trim()
        $isComment = $trimmed.StartsWith("#")
        $isManagedEntry = (
            $trimmed -eq $portableAppEntry -or
            $trimmed -eq $portableGgufEntry -or
            $trimmed -match '^[A-Za-z]:\\' -or
            $trimmed -match '^\\\\' -or
            $trimmed -match '(?i)bashi-privacy-app|Qwen3-TTS-GGUF'
        )
        if (-not $isComment -and $isManagedEntry) {
            continue
        }
        [void]$cleanLines.Add($line)
    }

    $importIndex = $cleanLines.IndexOf("import site")
    if ($importIndex -lt 0) {
        [void]$cleanLines.Add($portableAppEntry)
        [void]$cleanLines.Add($portableGgufEntry)
    }
    else {
        $cleanLines.Insert($importIndex, $portableAppEntry)
        $cleanLines.Insert($importIndex + 1, $portableGgufEntry)
    }

    Set-Content -LiteralPath $PthFile -Encoding ascii -Value @($cleanLines)
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

    Set-PortablePthEntries
}

function Assert-WindowsLongPathSupport {
    $lpKey = "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem"
    $lpVal = (Get-ItemProperty -Path $lpKey -Name "LongPathsEnabled" -ErrorAction SilentlyContinue).LongPathsEnabled
    if ($lpVal -eq 1) {
        return
    }

    '[ERROR] Windows long-path support is disabled.' | Add-Content -Path $LogFile -Encoding utf8
    Write-Host ""
    Write-Host "[ERROR] Windows long-path support is disabled. pip install will fail on packages with deep paths."
    Write-Host "[ERROR] Windows 长路径支持未开启，pip 安装会失败。"
    Write-Host ""
    Write-Host "Fix (run once in an Administrator PowerShell, then re-launch):"
    Write-Host "修复方法（在管理员 PowerShell 里运行一次，然后重新启动启动器）："
    Write-Host ""
    Write-Host '  New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force'
    Write-Host ""
    Write-Host "Microsoft docs: https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation"
    Read-Host "Press Enter to exit / 按回车退出"
    exit 1
}

function Ensure-Pip {
    $pipCheckExit = Invoke-NativeCommand { & $Python -m pip --version --isolated *> $null }
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
    try {
        Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip -UseBasicParsing -ErrorAction Stop
    }
    catch {
        '[ERROR] Failed to download the pip bootstrap script from bootstrap.pypa.io.' | Add-Content -Path $LogFile -Encoding utf8
        Write-Host '[ERROR] Unable to download the pip bootstrap script. Check network or proxy settings.'
        Write-Host '[ERROR] 无法下载 pip 引导脚本，请检查网络或代理设置。'
        Write-Host "Check launch_log.txt for details."
        Write-Host "请查看 launch_log.txt 了解详情。"
        Read-Host "Press Enter to exit / 按回车退出"
        exit 1
    }

    $pipBootstrapMaxAttempts = 3
    $pipBootstrapBackoffSeconds = @(2, 5)
    $pipBootstrapExit = -1
    $lastPipBootstrapFailureText = ""
    for ($attempt = 1; $attempt -le $pipBootstrapMaxAttempts; $attempt++) {
        $pipIndexPosition = [Math]::Min($attempt - 1, $pipIndexUrls.Count - 1)
        $currentPipIndexUrl = $pipIndexUrls[$pipIndexPosition]
        $bootstrapPipIndexArgs = @(Get-PipIndexArguments -IndexUrl $currentPipIndexUrl)
        if ($attempt -gt 1) {
            $wait = $pipBootstrapBackoffSeconds[$attempt - 2]
            $previousPipIndexPosition = [Math]::Min($attempt - 2, $pipIndexUrls.Count - 1)
            $previousPipIndexUrl = $pipIndexUrls[$previousPipIndexPosition]
            Write-Host ""
            if ($lastPipBootstrapFailureText -match '(?i)403|Forbidden|denied by IP ACL') {
                if ($currentPipIndexUrl -ne $previousPipIndexUrl) {
                    Write-Host ('[INFO] The mirror refused this IP; switching to {0} in {1}s (pip bootstrap attempt {2}/{3})...' -f $currentPipIndexUrl, $wait, $attempt, $pipBootstrapMaxAttempts)
                    Write-Host ('[INFO] 镜像拒绝了本机 IP；{0} 秒后切换到 {1}（pip 引导第 {2}/{3} 次）...' -f $wait, $currentPipIndexUrl, $attempt, $pipBootstrapMaxAttempts)
                }
                else {
                    Write-Host ('[INFO] The package index refused this IP; retrying {0} in {1}s (pip bootstrap attempt {2}/{3})...' -f $currentPipIndexUrl, $wait, $attempt, $pipBootstrapMaxAttempts)
                    Write-Host ('[INFO] 依赖源拒绝了本机 IP；{0} 秒后重试 {1}（pip 引导第 {2}/{3} 次）...' -f $wait, $currentPipIndexUrl, $attempt, $pipBootstrapMaxAttempts)
                }
            }
            elseif ($currentPipIndexUrl -ne $previousPipIndexUrl) {
                Write-Host ('[INFO] pip bootstrap index failed; switching to {0} in {1}s (attempt {2}/{3})...' -f $currentPipIndexUrl, $wait, $attempt, $pipBootstrapMaxAttempts)
                Write-Host ('[INFO] pip 引导依赖源失败；{0} 秒后切换到 {1}（第 {2}/{3} 次）...' -f $wait, $currentPipIndexUrl, $attempt, $pipBootstrapMaxAttempts)
            }
            else {
                Write-Host ('[INFO] pip bootstrap index failed; retrying {0} in {1}s (attempt {2}/{3})...' -f $currentPipIndexUrl, $wait, $attempt, $pipBootstrapMaxAttempts)
                Write-Host ('[INFO] pip 引导依赖源失败；{0} 秒后重试 {1}（第 {2}/{3} 次）...' -f $wait, $currentPipIndexUrl, $attempt, $pipBootstrapMaxAttempts)
            }
            Start-Sleep -Seconds $wait
        }

        ('[STEP] pip bootstrap index attempt {0}/{1}: {2}' -f $attempt, $pipBootstrapMaxAttempts, $currentPipIndexUrl) |
            Add-Content -Path $LogFile -Encoding utf8
        $pipBootstrapResult = Invoke-NativeCommandCapture -Command {
            & $Python $getPip --isolated --timeout 60 --no-warn-script-location @bootstrapPipIndexArgs
        } -WriteToHost -WriteToLog
        $pipBootstrapExit = $pipBootstrapResult.ExitCode
        if ($pipBootstrapExit -eq 0) {
            return
        }
        $lastPipBootstrapFailureText = $pipBootstrapResult.Lines -join [Environment]::NewLine
    }

    '[ERROR] pip bootstrap failed across configured package indexes.' | Add-Content -Path $LogFile -Encoding utf8
    Write-Host '[ERROR] Configured package indexes were unreachable or returned no pip versions. Please retry later or set BASHI_PIP_INDEX_URL.'
    Write-Host '[ERROR] 配置的依赖源不可达或未返回 pip 版本。请稍后重试，或设置 BASHI_PIP_INDEX_URL。'
    Write-Host "Check launch_log.txt for details."
    Write-Host "请查看 launch_log.txt 了解详情。"
    Read-Host "Press Enter to exit / 按回车退出"
    exit 1
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

# Prevent OpenMP Error #15 if torch and the GGUF CPU path load different OpenMP
# runtimes. Set before the dependency gate: that gate imports onnxruntime and then
# qwen_tts (which pulls in torch), i.e. the same double-OpenMP sequence as the app.
$env:KMP_DUPLICATE_LIB_OK = "TRUE"

Assert-WindowsLongPathSupport

$timeZone = (Get-TimeZone).Id
$culture = [System.Globalization.CultureInfo]::CurrentCulture.Name
$pipIndexOverride = $env:BASHI_PIP_INDEX_URL
if (-not [string]::IsNullOrWhiteSpace($pipIndexOverride)) {
    $pipIndexUrls = @($pipIndexOverride.Trim())
    Write-Host ("[INFO] BASHI_PIP_INDEX_URL override active: {0}" -f $pipIndexUrls[0])
    Write-Host ("[INFO] 已使用 BASHI_PIP_INDEX_URL 指定依赖源：{0}" -f $pipIndexUrls[0])
}
elseif ($timeZone -like "*China*" -or $culture -like "zh-*") {
    $pipIndexUrls = @($chinaPipIndexUrls)
    Write-Host '[INFO] China timezone/locale detected. Using Aliyun -> Tsinghua -> PyPI fallback chain.'
    Write-Host '[INFO] 检测到中国时区/语言环境，将按阿里云 → 清华 → PyPI 顺序安装依赖。'
}
else {
    # Overseas users stay on a single explicit PyPI index; retries reuse it to
    # absorb transient failures without routing them through China mirrors.
    $pipIndexUrls = @($officialPipIndexUrl)
    Write-Host '[INFO] Using the official PyPI index with retries.'
    Write-Host '[INFO] 使用官方 PyPI 依赖源并在瞬时失败时重试。'
}
$pipIndexArgs = @(Get-PipIndexArguments -IndexUrl $pipIndexUrls[0])

Ensure-Pip

# NOTE: the Python string literals below MUST use single quotes. Windows PowerShell
# 5.1 -- which run_portable.bat launches -- strips double quotes out of native
# command arguments, so "Flask" reaches Python as a bare name and raises NameError.
# Keep this string free of $ and backticks: it is a double-quoted PowerShell literal.
$dependencyCheckCode = "import importlib.metadata as m; [m.version(p) for p in ('Flask','imageio-ffmpeg','sherpa-onnx','gguf','onnx','onnxruntime-directml','sentencepiece','sounddevice','torch','transformers','qwen-tts')]; import onnxruntime as ort, qwen_tts; ps=ort.get_available_providers(); assert 'DmlExecutionProvider' in ps, f'Missing DML: {ps}'"
$dependencyCheck = Invoke-NativeCommandCapture { & $Python -c $dependencyCheckCode }
if ($dependencyCheck.ExitCode -eq 0) {
    '[STEP] dependency check ok' | Add-Content -Path $LogFile -Encoding utf8
}
else {
    ('[STEP] dependency check failed (exit {0})' -f $dependencyCheck.ExitCode) | Add-Content -Path $LogFile -Encoding utf8
    if ($dependencyCheck.Lines.Count -gt 0) {
        $dependencyCheck.Lines | Add-Content -Path $LogFile -Encoding utf8
    }
    $dependencyCheckOutput = $dependencyCheck.Lines -join "`n"
    $isFirstDependencyInstall = $dependencyCheckOutput -match 'PackageNotFoundError|No package metadata was found'
    if ($isFirstDependencyInstall) {
        Write-Host '[INFO] Installing dependencies for the first time.'
        Write-Host '[INFO] 首次安装依赖。'
    }
    else {
        Write-Host '[WARN] Dependency check failed; details were saved to launch_log.txt.'
        Write-Host '[WARN] 依赖检查失败；完整原因已写入 launch_log.txt。'
    }
    Write-Host ""
    Write-Host '[INFO] Installing or repairing dependencies. This usually takes 8-10 minutes on a good connection, longer on entry-level CPUs.'
    Write-Host '[INFO] 正在安装或修复依赖。网络顺畅时通常需要 8-10 分钟；入门级 CPU 可能需要 15 分钟以上。'
    Write-Host '[INFO] Per-package progress will scroll below — please wait, do not close this window.'
    Write-Host '[INFO] 下方会持续滚动每个依赖包的下载进度——请耐心等待，不要关闭此窗口。'
    Write-Host ""
    '[STEP] pip install -r requirements.txt' | Add-Content -Path $LogFile -Encoding utf8

    $pipMaxAttempts = 3
    $pipInstallExit = -1
    $firstFailedStepIndex = 0
    $pipOutputLines = [System.Collections.Generic.List[string]]::new()
    $lastPipFailureText = ""
    # Keep Python string literals single-quoted here for the same Windows PowerShell
    # 5.1 native-argument rule. Do not add $ or backticks to this double-quoted literal.
    $directMlProbeCode = "import onnxruntime as ort; assert 'DmlExecutionProvider' in ort.get_available_providers()"
    $pipSteps = @(
        [pscustomobject]@{
            LogStep = 'install Python build tooling'
            Command = { & $Python -m pip install setuptools==79.0.1 wheel==0.45.1 --prefer-binary --no-warn-script-location --progress-bar on --isolated --timeout 60 @pipIndexArgs }
        },
        [pscustomobject]@{
            LogStep = $null
            Command = { & $Python -m pip install -r requirements.txt --no-build-isolation --prefer-binary --no-warn-script-location --progress-bar on --isolated --timeout 60 @pipIndexArgs }
        },
        [pscustomobject]@{
            LogStep = 'pip install qwen-tts --no-deps'
            Command = { & $Python -m pip install qwen-tts==0.1.1 --no-deps --prefer-binary --no-warn-script-location --progress-bar on --isolated --timeout 60 @pipIndexArgs }
        },
        [pscustomobject]@{
            LogStep = 'force-reinstall onnxruntime-directml'
            Command = { & $Python -m pip install --force-reinstall --no-deps onnxruntime-directml==1.23.0 --prefer-binary --no-warn-script-location --progress-bar on --isolated --timeout 60 @pipIndexArgs }
        }
    )
    for ($attempt = 1; $attempt -le $pipMaxAttempts; $attempt++) {
        $pipIndexPosition = [Math]::Min($attempt - 1, $pipIndexUrls.Count - 1)
        $currentPipIndexUrl = $pipIndexUrls[$pipIndexPosition]
        $pipIndexArgs = @(Get-PipIndexArguments -IndexUrl $currentPipIndexUrl)
        if ($attempt -gt 1) {
            $wait = $pipBackoffSeconds[$attempt - 2]
            Write-Host ""
            $previousPipIndexPosition = [Math]::Min($attempt - 2, $pipIndexUrls.Count - 1)
            $previousPipIndexUrl = $pipIndexUrls[$previousPipIndexPosition]
            if ($lastPipFailureText -match '(?i)403|Forbidden|denied by IP ACL') {
                if ($currentPipIndexUrl -ne $previousPipIndexUrl) {
                    Write-Host ('[INFO] The mirror refused this IP; switching to {0} in {1}s (attempt {2}/{3})...' -f $currentPipIndexUrl, $wait, $attempt, $pipMaxAttempts)
                    Write-Host ('[INFO] 镜像拒绝了本机 IP；{0} 秒后切换到 {1}（第 {2}/{3} 次）...' -f $wait, $currentPipIndexUrl, $attempt, $pipMaxAttempts)
                }
                else {
                    Write-Host ('[INFO] The package index refused this IP; retrying {0} in {1}s (attempt {2}/{3})...' -f $currentPipIndexUrl, $wait, $attempt, $pipMaxAttempts)
                    Write-Host ('[INFO] 依赖源拒绝了本机 IP；{0} 秒后重试 {1}（第 {2}/{3} 次）...' -f $wait, $currentPipIndexUrl, $attempt, $pipMaxAttempts)
                }
            }
            elseif ($currentPipIndexUrl -ne $previousPipIndexUrl) {
                Write-Host ('[INFO] Package index attempt failed; switching to {0} in {1}s (attempt {2}/{3})...' -f $currentPipIndexUrl, $wait, $attempt, $pipMaxAttempts)
                Write-Host ('[INFO] 当前依赖源尝试失败；{0} 秒后切换到 {1}（第 {2}/{3} 次）...' -f $wait, $currentPipIndexUrl, $attempt, $pipMaxAttempts)
            }
            else {
                Write-Host ('[INFO] Package index attempt failed; retrying {0} in {1}s (attempt {2}/{3})...' -f $currentPipIndexUrl, $wait, $attempt, $pipMaxAttempts)
                Write-Host ('[INFO] 依赖源尝试失败；{0} 秒后重试 {1}（第 {2}/{3} 次）...' -f $wait, $currentPipIndexUrl, $attempt, $pipMaxAttempts)
            }
            Start-Sleep -Seconds $wait
        }
        Write-Host ('[INFO] Dependency index attempt {0}/{1}: {2}' -f $attempt, $pipMaxAttempts, $currentPipIndexUrl)
        ('[STEP] pip index attempt {0}/{1}: {2}' -f $attempt, $pipMaxAttempts, $currentPipIndexUrl) |
            Add-Content -Path $LogFile -Encoding utf8
        for ($stepIndex = $firstFailedStepIndex; $stepIndex -lt $pipSteps.Count; $stepIndex++) {
            $step = $pipSteps[$stepIndex]
            if ($stepIndex -eq 3) {
                $directMlProbe = Invoke-NativeCommandCapture { & $Python -c $directMlProbeCode }
                if ($directMlProbe.ExitCode -eq 0) {
                    '[STEP] DirectML already authoritative, skipping force-reinstall' | Add-Content -Path $LogFile -Encoding utf8
                    $pipInstallExit = 0
                    $firstFailedStepIndex = $pipSteps.Count
                    break
                }
            }
            if ($step.LogStep) {
                ('[STEP] ' + $step.LogStep) | Add-Content -Path $LogFile -Encoding utf8
            }
            $pipResult = Invoke-NativeCommandCapture -Command $step.Command -WriteToHost -WriteToLog
            foreach ($line in $pipResult.Lines) {
                [void]$pipOutputLines.Add($line)
            }
            $pipInstallExit = $pipResult.ExitCode
            if ($pipInstallExit -ne 0) {
                $lastPipFailureText = $pipResult.Lines -join [Environment]::NewLine
                $firstFailedStepIndex = $stepIndex
                break
            }
            $firstFailedStepIndex = $stepIndex + 1
        }
        if ($pipInstallExit -eq 0 -and $firstFailedStepIndex -ge $pipSteps.Count) { break }
    }

    if ($pipInstallExit -ne 0) {
        Write-Host ""
        $pipFailureText = $pipOutputLines -join [Environment]::NewLine
        if ($pipFailureText -match '(?i)403|Forbidden|denied by IP ACL') {
            Write-Host '[ERROR] A configured package index refused this IP (access control or blacklist). See launch_log.txt for the rejected mirror.'
            Write-Host '[ERROR] 配置的依赖源拒绝了本机 IP（访问控制或黑名单）。请查看 launch_log.txt 确认具体镜像。'
        }
        elseif ($pipFailureText -match '(?i)No matching distribution found|from versions:\s*none') {
            Write-Host '[ERROR] Configured package indexes were unreachable or returned no package versions. Please retry later or set BASHI_PIP_INDEX_URL.'
            Write-Host '[ERROR] 配置的依赖源不可达或未返回任何版本。请稍后重试，或设置 BASHI_PIP_INDEX_URL。'
        }
        else {
            Write-Host '[ERROR] pip install failed across the configured package indexes. See launch_log.txt for mirror-specific details.'
            Write-Host '[ERROR] pip 在配置的依赖源上均安装失败。请查看 launch_log.txt 中的镜像详情。'
        }
        Write-Host ('Logs: app.log: {0}; launch_log.txt: {1}' -f (Join-Path $AppRoot 'app.log'), $LogFile)
        Read-Host "Press Enter to exit / 按回车退出"
        exit 1
    }
}

$env:BASHI_DEPS_READY_EPOCH = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()

$ModelDownloadScript = Join-Path $AppRoot "download_gguf_model.py"
if (Test-Path $ModelDownloadScript) {
    '[STEP] Checking GGUF runtime model pack' | Add-Content -Path $LogFile -Encoding utf8
    $modelCheckExit = Invoke-NativeCommandWithUtf8Log { & $Python $ModelDownloadScript --check-only }
    if ($modelCheckExit -ne 0) {
        Write-Host ""
        Write-Host '[WARN] GGUF runtime model pack is missing or incomplete.'
        Write-Host "       未检测到完整 GGUF 运行模型包。"
        Write-Host "       First model download is about 2.2 GiB and can take 5-15 minutes."
        Write-Host "       首次模型下载约 2.2 GiB，通常需要 5-15 分钟。"
        Write-Host "       After that, synthesis runs offline."
        Write-Host "       下载完成后，语音合成可本地离线运行。"
        Write-Host ""
        Write-Host '[INFO] Starting GGUF model download now. Press Ctrl+C to cancel; re-run this launcher to resume.'
        Write-Host '[INFO] 现在开始下载 GGUF 模型。可按 Ctrl+C 取消；重新运行启动器会自动续传。'
        Write-Host ""
        Write-Host '[INFO] Downloading GGUF runtime model pack...'
        Write-Host '[INFO] 正在下载 GGUF 运行模型包...'
        '[STEP] download_gguf_model.py' | Add-Content -Path $LogFile -Encoding utf8

        $ggufMaxAttempts = 3
        $ggufBackoffSeconds = @(5, 30, 120)
        $modelDownloadExit = -1
        for ($attempt = 1; $attempt -le $ggufMaxAttempts; $attempt++) {
            if ($attempt -gt 1) {
                $wait = $ggufBackoffSeconds[$attempt - 2]
                Write-Host ""
                Write-Host ('[INFO] GGUF download interrupted. Resuming in {0}s (attempt {1}/{2}); already-downloaded bytes are reused.' -f $wait, $attempt, $ggufMaxAttempts)
                Write-Host ('[INFO] GGUF 下载中断。{0} 秒后续传（第 {1}/{2} 次）；已下载部分会自动复用。' -f $wait, $attempt, $ggufMaxAttempts)
                Start-Sleep -Seconds $wait
            }
            $modelDownloadExit = Invoke-NativeCommandWithUtf8Log { & $Python $ModelDownloadScript }
            if ($modelDownloadExit -eq 0) { break }
        }

        if ($modelDownloadExit -ne 0) {
            Write-Host ""
            Write-Host '[WARN] GGUF model download did not complete after retries.'
            Write-Host "       GGUF 模型多次重试后仍未下载完成。"
            Write-Host "       The app will continue to start; you can retry later from the launcher."
            Write-Host "       程序将继续启动；可稍后再次运行启动器自动续传。"
            Write-Host ("       Log: " + $LogFile)
        }
        else {
            Write-Host '[OK] GGUF runtime model pack is ready.'
            Write-Host '[OK] GGUF 运行模型包已就绪。'
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
    Write-Host '[N] No / 仅本机 (127.0.0.1) — 10 秒未选择默认 N / defaults to N in 10s'
    Write-Host "========================================================"
    $BindHost = Read-LanBindHost
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

# Align the console with app/worker UTF-8 stdio after all pip operations are complete.
chcp 65001 > $null

('[STEP] Starting app.py with host={0} port={1}' -f $BindHost, $Port) | Add-Content -Path $LogFile -Encoding utf8
$pythonCommand = "`"$Python`" app.py --host `"$BindHost`" --port `"$Port`" 2>> `"$LogFile`""
$exitCode = -1
try {
    & cmd.exe /d /c $pythonCommand
    $exitCode = $LASTEXITCODE
}
finally {
    if ($exitCode -lt 0) {
        $exitCode = 130
    }
    ('[DONE] app.py exited with code {0}' -f $exitCode) | Add-Content -Path $LogFile -Encoding utf8

    Write-Host ""
    Write-Host "App exited. (Exit code: $exitCode)"
    Write-Host "程序已退出。（退出代码: $exitCode）"
    Write-Host "If the app crashed, check app.log and launch_log.txt for details."
    Write-Host "如果程序异常退出，请查看 app.log 和 launch_log.txt 了解详情。"
    Read-Host "Press Enter to exit / 按回车退出"
}
exit $exitCode
