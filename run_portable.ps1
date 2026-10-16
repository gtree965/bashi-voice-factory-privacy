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
$pipBackoffSeconds = @(5, 30, 30, 30)
# The candidates for the speed test, in the order that is used when the test
# cannot run or every mirror fails. mirror_probe.py holds the matching short
# names and the probe file path; a test keeps the two lists in step.
$pipMirrorIndexUrls = [ordered]@{
    aliyun = "https://mirrors.aliyun.com/pypi/simple/"
    tuna = "https://pypi.tuna.tsinghua.edu.cn/simple/"
    tencent = "https://mirrors.cloud.tencent.com/pypi/simple/"
    huawei = "https://repo.huaweicloud.com/repository/pypi/simple/"
    pypi = "https://pypi.org/simple/"
}
$chinaPipIndexUrls = @($pipMirrorIndexUrls.Values)
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

    # Parse with TryCreate and never echo $IndexUrl in a failure: an index from
    # BASHI_PIP_INDEX_URL may carry credentials in its user information, and a
    # cast to [System.Uri] would put the whole value into its conversion error.
    # An unserialisable or non-http(s) address therefore fails with a reason
    # only, and the caller reports that reason without the address.
    $uri = $null
    if (-not [System.Uri]::TryCreate($IndexUrl, [System.UriKind]::Absolute, [ref]$uri) -or
        -not $uri.IsAbsoluteUri -or
        -not $uri.Host -or
        $uri.Scheme -notin @("http", "https")) {
        throw "Invalid pip index URL. BASHI_PIP_INDEX_URL must be an absolute http:// or https:// address."
    }
    # --trusted-host is not "allow plain http": pip attaches an adapter that
    # skips certificate verification for both the http:// and the https:// URLs
    # of that host. The built-in indexes are HTTPS and must be verified, so the
    # flag is never added for them. Only an index the user selected through
    # BASHI_PIP_INDEX_URL needs it, and only when that index is plain http,
    # because pip refuses an http index without it.
    $arguments = @("-i", $uri.AbsoluteUri)
    if ($uri.Scheme -eq "http") {
        $arguments += @("--trusted-host", $uri.Host)
    }
    return $arguments
}

function Get-PipIndexDisplayUrl {
    param([Parameter(Mandatory = $true)][string]$IndexUrl)

    # An index URL may carry a credential in its user information or in a query
    # parameter; pip still receives the real URL, but nothing the launcher
    # prints or logs may show either, and the fragment is dropped as well.
    #
    # The cut has to happen on the raw text: System.Uri only treats "?" as a
    # query separator for schemes that define one, and folds it into the path
    # for the rest (ftp://host/simple/?token=x becomes the path
    # /simple/%3Ftoken=x), which would carry the token straight through.
    $cutIndex = -1
    foreach ($delimiter in @("?", "#")) {
        $position = $IndexUrl.IndexOf($delimiter)
        if ($position -ge 0 -and ($cutIndex -lt 0 -or $position -lt $cutIndex)) {
            $cutIndex = $position
        }
    }
    $visible = $IndexUrl
    $queryPart = ""
    if ($cutIndex -ge 0) {
        $visible = $IndexUrl.Substring(0, $cutIndex)
        if ($IndexUrl[$cutIndex] -eq "?") { $queryPart = "?***" }
    }

    $uri = $null
    if (-not [System.Uri]::TryCreate($visible, [System.UriKind]::Absolute, [ref]$uri) -or -not $uri.Host) {
        return "<unparsable index URL>"
    }
    $userPart = ""
    if ($uri.UserInfo) { $userPart = "***@" }
    $portPart = ""
    if (-not $uri.IsDefaultPort) { $portPart = ":" + $uri.Port }
    return ("{0}://{1}{2}{3}{4}{5}" -f $uri.Scheme, $userPart, $uri.Host, $portPart, $uri.AbsolutePath, $queryPart)
}

function Test-PipProbeEligible {
    param(
        [string]$Override = $env:BASHI_PIP_INDEX_URL,
        [string]$TimeZoneId = (Get-TimeZone).Id,
        [string]$CultureName = [System.Globalization.CultureInfo]::CurrentCulture.Name
    )

    # The speed test only ranks the built-in Chinese chain. An override is the
    # user's own choice and is used as is, and every other locale keeps the
    # single official index without contacting additional mirrors.
    if (-not [string]::IsNullOrWhiteSpace($Override)) { return $false }
    return ($TimeZoneId -like "*China*" -or $CultureName -like "zh-*")
}

$pipMirrorProbeCache = @{ Done = $false; RankedUrls = $null }

function Invoke-PipMirrorProbeProcess {
    param(
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [int]$TimeoutSeconds = 15
    )

    # Only the probe's own [mirror-probe] lines are kept; anything else on its
    # stdout or stderr (a traceback, for example) never reaches the console or
    # launch_log.txt.
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $Python
    $startInfo.Arguments = '"{0}"' -f $ScriptPath
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true

    $process = [System.Diagnostics.Process]::Start($startInfo)
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    [void]$process.StandardError.ReadToEndAsync()
    $exited = $process.WaitForExit($TimeoutSeconds * 1000)
    if (-not $exited) {
        try { $process.Kill() } catch { }
        [void]$process.WaitForExit(5000)
        return [pscustomobject]@{ TimedOut = $true; ExitCode = -1; Lines = @() }
    }

    $lines = @()
    foreach ($line in @(([string]$stdoutTask.Result) -split "`r?`n")) {
        if ($line -match '^\[mirror-probe\] ') { $lines += $line.TrimEnd() }
    }
    return [pscustomobject]@{ TimedOut = $false; ExitCode = $process.ExitCode; Lines = @($lines) }
}

function Get-PipRankedPipIndexUrls {
    param(
        [Parameter(Mandatory = $true)][string[]]$FallbackUrls,
        [Parameter(Mandatory = $true)][bool]$ProbeEligible,
        [int]$ProbeTimeoutSeconds = 15
    )

    # One probe per launch: the first caller runs it, every later caller reuses
    # the result, and both install entry points share this function.
    if ($pipMirrorProbeCache.Done) {
        if ($pipMirrorProbeCache.RankedUrls) { return @($pipMirrorProbeCache.RankedUrls) }
        return @($FallbackUrls)
    }
    $pipMirrorProbeCache.Done = $true

    if (-not $ProbeEligible -or @($FallbackUrls).Count -lt 2) {
        return @($FallbackUrls)
    }

    $probeScript = Join-Path $AppRoot "mirror_probe.py"
    if (-not (Test-Path -LiteralPath $probeScript)) {
        '[STEP] mirror probe skipped: mirror_probe.py is missing' | Add-Content -Path $LogFile -Encoding utf8
        return @($FallbackUrls)
    }

    $probeNames = @(
        $pipMirrorIndexUrls.GetEnumerator() |
            Where-Object { $FallbackUrls -contains $_.Value } |
            ForEach-Object { $_.Key }
    )
    Write-Host ("[INFO] Testing the package mirrors before downloading: {0} (at most 1 MiB each)." -f ($probeNames -join ', '))
    Write-Host ("[INFO] 下载前先测试依赖源：{0}（每个最多 1 MiB）。" -f ($probeNames -join '、'))
    Write-Host "[INFO] Normally about 10 seconds, at most 15 seconds before falling back to the fixed order."
    Write-Host "[INFO] 正常约 10 秒；异常时最迟 15 秒回退到固定顺序。"

    $probe = Invoke-PipMirrorProbeProcess -ScriptPath $probeScript -TimeoutSeconds $ProbeTimeoutSeconds
    foreach ($line in @($probe.Lines)) {
        Write-Host $line
        Add-Content -Path $LogFile -Encoding utf8 -Value $line
    }
    if ($probe.TimedOut) {
        Write-Host "[INFO] The mirror test did not finish in time; using the fixed order."
        Write-Host "[INFO] 依赖源测速未在时限内完成；改用固定顺序。"
        '[STEP] mirror probe timed out' | Add-Content -Path $LogFile -Encoding utf8
        return @($FallbackUrls)
    }

    $rankLine = @($probe.Lines | Where-Object { $_ -match '^\[mirror-probe\] rank ' } | Select-Object -Last 1)
    if (-not $rankLine) {
        '[STEP] mirror probe output had no ranking; using the fixed order' | Add-Content -Path $LogFile -Encoding utf8
        return @($FallbackUrls)
    }

    $rankedUrls = New-Object System.Collections.Generic.List[string]
    foreach ($name in @(($rankLine[0] -replace '^\[mirror-probe\] rank ', '') -split ',')) {
        $trimmedName = $name.Trim()
        if (-not $trimmedName) { continue }
        if ($pipMirrorIndexUrls.Contains($trimmedName)) {
            $url = [string]$pipMirrorIndexUrls[$trimmedName]
            if (-not $rankedUrls.Contains($url)) { [void]$rankedUrls.Add($url) }
        }
    }
    foreach ($url in @($FallbackUrls)) {
        if (-not $rankedUrls.Contains($url)) { [void]$rankedUrls.Add($url) }
    }

    if ($probe.ExitCode -ne 0) {
        '[STEP] mirror probe found no usable mirror; using the fixed order' | Add-Content -Path $LogFile -Encoding utf8
        return @($FallbackUrls)
    }

    $pipMirrorProbeCache.RankedUrls = @($rankedUrls)
    return @($rankedUrls)
}

function Read-LanBindHost {
    param(
        [int]$TimeoutSeconds = 20,
        [scriptblock]$KeyAvailable = { [Console]::KeyAvailable },
        [scriptblock]$ReadKey = { [Console]::ReadKey($true).KeyChar },
        [scriptblock]$Wait = { param([int]$Milliseconds) Start-Sleep -Milliseconds $Milliseconds },
        [scriptblock]$Now = { Get-Date },
        [scriptblock]$ReportRemaining = {
            param([int]$Seconds)
            # Redrawn in place so a 20-second wait does not scroll the answer
            # away; the padding hides the tail of a longer previous number.
            Write-Host -NoNewline ("`r{0}" -f ('按 Y 允许局域网访问；按其他任意键立即选择仅本机（剩余 {0} 秒）      ' -f $Seconds))
        },
        [scriptblock]$ReportChoice = {
            param([string]$Message)
            Write-Host ""
            Write-Host $Message
        }
    )

    $selectedHost = "127.0.0.1"
    $choiceMessage = "已选择：仅本机（超时默认）"
    try {
        $deadline = (& $Now).AddSeconds($TimeoutSeconds)
        $remaining = $TimeoutSeconds
        & $ReportRemaining $remaining
        while ((& $Now) -lt $deadline) {
            if (& $KeyAvailable) {
                $key = & $ReadKey
                if ($key -match '^[Yy]$') {
                    $selectedHost = "0.0.0.0"
                    $choiceMessage = "已选择：允许局域网访问"
                }
                else {
                    $choiceMessage = "已选择：仅本机（按键）"
                }
                break
            }
            & $Wait 200
            $secondsLeft = [int][Math]::Ceiling(($deadline - (& $Now)).TotalSeconds)
            if ($secondsLeft -lt 0) { $secondsLeft = 0 }
            if ($secondsLeft -ne $remaining) {
                $remaining = $secondsLeft
                & $ReportRemaining $remaining
            }
        }
    }
    catch {
        # Redirected stdin and hosts without a console safely keep the default.
    }
    try {
        & $ReportChoice $choiceMessage
    }
    catch {
        # The echo is cosmetic; a host without a console must not change the choice.
    }
    return $selectedHost
}

function Get-BindHostMode {
    param([Parameter(Mandatory = $true)][string]$BindHost)

    # 'Local'      -- loopback only, the app runs exactly as before
    # 'Network'    -- 0.0.0.0, every IPv4 interface of this machine
    # 'Specific'   -- one concrete IPv4 address
    # 'Unsupported'-- non-loopback IPv6 or a host name; app.py refuses to start
    $value = $BindHost.Trim()
    if ($value -eq 'localhost') { return 'Local' }

    $address = $null
    if (-not [System.Net.IPAddress]::TryParse($value, [ref]$address)) {
        return 'Unsupported'
    }
    if ([System.Net.IPAddress]::IsLoopback($address)) { return 'Local' }
    if ($address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetworkV6) {
        return 'Unsupported'
    }
    if ($value -eq '0.0.0.0') { return 'Network' }
    return 'Specific'
}

function Get-BindHostDisplayHost {
    param(
        [Parameter(Mandatory = $true)][string]$BindHost,
        [string]$DetectedLanIp = ''
    )

    # Binding a concrete IP means 127.0.0.1 is not listening, so showing it
    # here would send the user to an address that cannot connect.
    switch (Get-BindHostMode -BindHost $BindHost) {
        'Local' {
            return '127.0.0.1'
        }
        'Network' {
            if ($DetectedLanIp) { return $DetectedLanIp }
            return 'YOUR_LOCAL_IP'
        }
        default {
            return $BindHost.Trim()
        }
    }
}

function Get-LanDisplayAddress {
    param(
        [object[]]$Adapters = @(),
        [object[]]$Addresses = @(),
        [object[]]$Routes = @(),
        [object[]]$InterfaceMetrics = @(),
        [object[]]$NetworkProfiles = @()
    )

    # Only a physical adapter that is up, with a private IPv4 address and a
    # default route on the same interface whose next hop falls inside that
    # address's own subnet, is a candidate. Everything else is left out on
    # purpose: a virtual adapter may expose addresses that
    # other devices cannot reach, and a machine without a default route has no
    # address this function can say anything about. The inputs are plain
    # objects projected by the caller, so the whole selection can be fed with
    # synthetic snapshots.
    function Test-PrivateLanAddress {
        param([System.Net.IPAddress]$Address)
        $bytes = $Address.GetAddressBytes()
        if ($bytes[0] -eq 10) { return $true }
        if ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) { return $true }
        if ($bytes[0] -eq 192 -and $bytes[1] -eq 168) { return $true }
        return $false
    }

    function Test-SameSubnet {
        param(
            [System.Net.IPAddress]$Address,
            [int]$PrefixLength,
            [System.Net.IPAddress]$Candidate
        )
        if ($PrefixLength -lt 1 -or $PrefixLength -gt 32) { return $false }
        $addressBytes = $Address.GetAddressBytes()
        $candidateBytes = $Candidate.GetAddressBytes()
        if ($candidateBytes.Length -ne 4) { return $false }
        for ($octet = 0; $octet -lt 4; $octet++) {
            $bits = [Math]::Min(8, [Math]::Max(0, $PrefixLength - $octet * 8))
            if ($bits -le 0) { break }
            $mask = [byte]((0xFF -shl (8 - $bits)) -band 0xFF)
            if (($addressBytes[$octet] -band $mask) -ne ($candidateBytes[$octet] -band $mask)) { return $false }
        }
        return $true
    }

    $none = [pscustomobject]@{
        Address = ""
        AdapterName = ""
        NetworkCategory = ""
        Reason = "none"
    }

    $metricByIndex = @{}
    foreach ($record in $InterfaceMetrics) {
        $metricByIndex[[int]$record.InterfaceIndex] = [int]$record.InterfaceMetric
    }

    $categoryByIndex = @{}
    foreach ($profile in $NetworkProfiles) {
        $index = [int]$profile.InterfaceIndex
        if (-not $categoryByIndex.ContainsKey($index)) {
            $categoryByIndex[$index] = [string]$profile.NetworkCategory
        }
    }

    $physicalAdapters = @{}
    foreach ($adapter in $Adapters) {
        if ($adapter.Status -ne "Up" -or $adapter.HardwareInterface -ne $true) { continue }
        $physicalAdapters[[int]$adapter.InterfaceIndex] = $adapter
    }
    if ($physicalAdapters.Count -eq 0) { return $none }

    $best = $null
    foreach ($entry in $Addresses) {
        $interfaceIndex = [int]$entry.InterfaceIndex
        if (-not $physicalAdapters.ContainsKey($interfaceIndex)) { continue }

        $address = $null
        if (-not [System.Net.IPAddress]::TryParse([string]$entry.IPAddress, [ref]$address)) { continue }
        if ($address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { continue }
        if (-not (Test-PrivateLanAddress -Address $address)) { continue }

        foreach ($route in $Routes) {
            if ([int]$route.InterfaceIndex -ne $interfaceIndex) { continue }
            if ([string]$route.DestinationPrefix -ne "0.0.0.0/0") { continue }
            $nextHop = $null
            if (-not [System.Net.IPAddress]::TryParse([string]$route.NextHop, [ref]$nextHop)) { continue }
            if (-not (Test-SameSubnet -Address $address -PrefixLength ([int]$entry.PrefixLength) -Candidate $nextHop)) { continue }

            # Lowest route metric plus interface metric wins; the interface
            # number only breaks a tie. This is the ordering this function
            # uses inside the physical adapters, not the routing decision
            # Windows makes across every route.
            $interfaceMetric = 0
            if ($metricByIndex.ContainsKey($interfaceIndex)) { $interfaceMetric = $metricByIndex[$interfaceIndex] }
            $metric = [int]$route.RouteMetric + $interfaceMetric
            if ($null -eq $best -or $metric -lt $best.Metric -or ($metric -eq $best.Metric -and $interfaceIndex -lt $best.InterfaceIndex)) {
                $best = [pscustomobject]@{
                    Address = $address.ToString()
                    AdapterName = [string]$physicalAdapters[$interfaceIndex].Name
                    InterfaceIndex = $interfaceIndex
                    Metric = $metric
                }
            }
        }
    }

    if ($null -eq $best) { return $none }

    $category = ""
    if ($categoryByIndex.ContainsKey($best.InterfaceIndex)) { $category = $categoryByIndex[$best.InterfaceIndex] }
    return [pscustomobject]@{
        Address = $best.Address
        AdapterName = $best.AdapterName
        NetworkCategory = $category
        Reason = "ok"
    }
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

    # Ranked once per launch; the dependency install below reuses this result.
    $bootstrapPipIndexUrls = @(Get-PipRankedPipIndexUrls -FallbackUrls $pipIndexUrls -ProbeEligible $pipProbeEligible)
    $pipBootstrapMaxAttempts = [Math]::Max(3, $bootstrapPipIndexUrls.Count)
    $pipBootstrapBackoffSeconds = @(2, 5, 10, 10)
    $pipBootstrapExit = -1
    $lastPipBootstrapFailureText = ""
    for ($attempt = 1; $attempt -le $pipBootstrapMaxAttempts; $attempt++) {
        $pipIndexPosition = [Math]::Min($attempt - 1, $bootstrapPipIndexUrls.Count - 1)
        $currentPipIndexUrl = $bootstrapPipIndexUrls[$pipIndexPosition]
        $currentPipIndexDisplayUrl = Get-PipIndexDisplayUrl -IndexUrl $currentPipIndexUrl
        $bootstrapPipIndexArgs = @(Get-PipIndexArguments -IndexUrl $currentPipIndexUrl)
        if ($attempt -gt 1) {
            # The backoff list and the index list can be shorter than the
            # attempt counter, so both indexes are clamped; an attempt must
            # never read past the end and pass $null to Start-Sleep.
            $wait = $pipBootstrapBackoffSeconds[[Math]::Min($attempt - 2, $pipBootstrapBackoffSeconds.Count - 1)]
            $previousPipIndexPosition = [Math]::Min($attempt - 2, $bootstrapPipIndexUrls.Count - 1)
            $previousPipIndexUrl = $bootstrapPipIndexUrls[$previousPipIndexPosition]
            Write-Host ""
            if ($lastPipBootstrapFailureText -match '(?i)403|Forbidden|denied by IP ACL') {
                if ($currentPipIndexUrl -ne $previousPipIndexUrl) {
                    Write-Host ('[INFO] The mirror refused this IP; switching to {0} in {1}s (pip bootstrap attempt {2}/{3})...' -f $currentPipIndexDisplayUrl, $wait, $attempt, $pipBootstrapMaxAttempts)
                    Write-Host ('[INFO] 镜像拒绝了本机 IP；{0} 秒后切换到 {1}（pip 引导第 {2}/{3} 次）...' -f $wait, $currentPipIndexDisplayUrl, $attempt, $pipBootstrapMaxAttempts)
                }
                else {
                    Write-Host ('[INFO] The package index refused this IP; retrying {0} in {1}s (pip bootstrap attempt {2}/{3})...' -f $currentPipIndexDisplayUrl, $wait, $attempt, $pipBootstrapMaxAttempts)
                    Write-Host ('[INFO] 依赖源拒绝了本机 IP；{0} 秒后重试 {1}（pip 引导第 {2}/{3} 次）...' -f $wait, $currentPipIndexDisplayUrl, $attempt, $pipBootstrapMaxAttempts)
                }
            }
            elseif ($currentPipIndexUrl -ne $previousPipIndexUrl) {
                Write-Host ('[INFO] pip bootstrap index failed; switching to {0} in {1}s (attempt {2}/{3})...' -f $currentPipIndexDisplayUrl, $wait, $attempt, $pipBootstrapMaxAttempts)
                Write-Host ('[INFO] pip 引导依赖源失败；{0} 秒后切换到 {1}（第 {2}/{3} 次）...' -f $wait, $currentPipIndexDisplayUrl, $attempt, $pipBootstrapMaxAttempts)
            }
            else {
                Write-Host ('[INFO] pip bootstrap index failed; retrying {0} in {1}s (attempt {2}/{3})...' -f $currentPipIndexDisplayUrl, $wait, $attempt, $pipBootstrapMaxAttempts)
                Write-Host ('[INFO] pip 引导依赖源失败；{0} 秒后重试 {1}（第 {2}/{3} 次）...' -f $wait, $currentPipIndexDisplayUrl, $attempt, $pipBootstrapMaxAttempts)
            }
            Start-Sleep -Seconds $wait
        }

        ('[STEP] pip bootstrap index attempt {0}/{1}: {2}' -f $attempt, $pipBootstrapMaxAttempts, $currentPipIndexDisplayUrl) |
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
Write-Host "Preparation or repair may download ~700 MB dependencies + ~2.2 GB GGUF model."
Write-Host "准备或修复时可能下载约 700 MB 依赖 + 2.2 GB GGUF 模型。"
Write-Host "This notice does not mean a download is running; check the step messages below."
Write-Host "此提示不表示正在下载；请以下方步骤消息为准。"
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
    $pipIndexDisplayUrl = Get-PipIndexDisplayUrl -IndexUrl $pipIndexUrls[0]
    Write-Host ("[INFO] BASHI_PIP_INDEX_URL override active: {0}" -f $pipIndexDisplayUrl)
    Write-Host ("[INFO] 已使用 BASHI_PIP_INDEX_URL 指定依赖源：{0}" -f $pipIndexDisplayUrl)
    $overrideUri = $null
    if ([System.Uri]::TryCreate($pipIndexUrls[0], [System.UriKind]::Absolute, [ref]$overrideUri) -and $overrideUri.Scheme -eq 'http') {
        Write-Host ("[WARN] This override uses plain http; pip will not verify certificates for {0}." -f $overrideUri.Host)
        Write-Host ("[WARN] 该源为 http，pip 对 {0} 不校验证书。" -f $overrideUri.Host)
    }
}
elseif ($timeZone -like "*China*" -or $culture -like "zh-*") {
    $pipIndexUrls = @($chinaPipIndexUrls)
    Write-Host '[INFO] China timezone/locale detected. Using Aliyun -> Tsinghua -> Tencent -> Huawei -> PyPI fallback chain.'
    Write-Host '[INFO] 检测到中国时区/语言环境，将按阿里云 → 清华 → 腾讯云 → 华为云 → PyPI 顺序安装依赖。'
}
else {
    # Overseas users stay on a single explicit PyPI index; retries reuse it to
    # absorb transient failures without routing them through China mirrors.
    $pipIndexUrls = @($officialPipIndexUrl)
    Write-Host '[INFO] Using the official PyPI index with retries.'
    Write-Host '[INFO] 使用官方 PyPI 依赖源并在瞬时失败时重试。'
}
$pipIndexArgs = @(Get-PipIndexArguments -IndexUrl $pipIndexUrls[0])
# Decided once: the speed test ranks the built-in chain and nothing else.
$pipProbeEligible = Test-PipProbeEligible -Override $pipIndexOverride -TimeZoneId $timeZone -CultureName $culture

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

    # Same ranked list as the pip bootstrap used, when that ran; otherwise the
    # first probe of this launch happens here.
    $installPipIndexUrls = @(Get-PipRankedPipIndexUrls -FallbackUrls $pipIndexUrls -ProbeEligible $pipProbeEligible)
    $pipMaxAttempts = [Math]::Max(3, $installPipIndexUrls.Count)
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
        $pipIndexPosition = [Math]::Min($attempt - 1, $installPipIndexUrls.Count - 1)
        $currentPipIndexUrl = $installPipIndexUrls[$pipIndexPosition]
        $currentPipIndexDisplayUrl = Get-PipIndexDisplayUrl -IndexUrl $currentPipIndexUrl
        $pipIndexArgs = @(Get-PipIndexArguments -IndexUrl $currentPipIndexUrl)
        if ($attempt -gt 1) {
            # Clamped like the bootstrap loop: an attempt must never read past
            # the end of the backoff list and pass $null to Start-Sleep.
            $wait = $pipBackoffSeconds[[Math]::Min($attempt - 2, $pipBackoffSeconds.Count - 1)]
            Write-Host ""
            $previousPipIndexPosition = [Math]::Min($attempt - 2, $installPipIndexUrls.Count - 1)
            $previousPipIndexUrl = $installPipIndexUrls[$previousPipIndexPosition]
            if ($lastPipFailureText -match '(?i)403|Forbidden|denied by IP ACL') {
                if ($currentPipIndexUrl -ne $previousPipIndexUrl) {
                    Write-Host ('[INFO] The mirror refused this IP; switching to {0} in {1}s (attempt {2}/{3})...' -f $currentPipIndexDisplayUrl, $wait, $attempt, $pipMaxAttempts)
                    Write-Host ('[INFO] 镜像拒绝了本机 IP；{0} 秒后切换到 {1}（第 {2}/{3} 次）...' -f $wait, $currentPipIndexDisplayUrl, $attempt, $pipMaxAttempts)
                }
                else {
                    Write-Host ('[INFO] The package index refused this IP; retrying {0} in {1}s (attempt {2}/{3})...' -f $currentPipIndexDisplayUrl, $wait, $attempt, $pipMaxAttempts)
                    Write-Host ('[INFO] 依赖源拒绝了本机 IP；{0} 秒后重试 {1}（第 {2}/{3} 次）...' -f $wait, $currentPipIndexDisplayUrl, $attempt, $pipMaxAttempts)
                }
            }
            elseif ($currentPipIndexUrl -ne $previousPipIndexUrl) {
                Write-Host ('[INFO] Package index attempt failed; switching to {0} in {1}s (attempt {2}/{3})...' -f $currentPipIndexDisplayUrl, $wait, $attempt, $pipMaxAttempts)
                Write-Host ('[INFO] 当前依赖源尝试失败；{0} 秒后切换到 {1}（第 {2}/{3} 次）...' -f $wait, $currentPipIndexDisplayUrl, $attempt, $pipMaxAttempts)
            }
            else {
                Write-Host ('[INFO] Package index attempt failed; retrying {0} in {1}s (attempt {2}/{3})...' -f $currentPipIndexDisplayUrl, $wait, $attempt, $pipMaxAttempts)
                Write-Host ('[INFO] 依赖源尝试失败；{0} 秒后重试 {1}（第 {2}/{3} 次）...' -f $wait, $currentPipIndexDisplayUrl, $attempt, $pipMaxAttempts)
            }
            Start-Sleep -Seconds $wait
        }
        Write-Host ('[INFO] Dependency index attempt {0}/{1}: {2}' -f $attempt, $pipMaxAttempts, $currentPipIndexDisplayUrl)
        ('[STEP] pip index attempt {0}/{1}: {2}' -f $attempt, $pipMaxAttempts, $currentPipIndexDisplayUrl) |
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
    Write-Host '[!] WARNING / 警告'
    Write-Host '    Anyone who can reach this port on your network can open this app.'
    Write-Host '    任何能访问该端口的设备都可以打开本程序。'
    Write-Host '    A one-time PIN will be shown in the console and must be entered'
    Write-Host '    on every other device before it can do anything.'
    Write-Host '    控制台会显示一次性 PIN，其他设备必须先输入它才能操作。'
    Write-Host '    Only enable this on a network you trust.'
    Write-Host '    请仅在信任的网络上开启。'
    Write-Host "========================================================"
    Write-Host ""
    Write-Host "DO YOU WANT TO ALLOW OTHER DEVICES ON YOUR NETWORK TO ACCESS THIS SERVER?"
    Write-Host "是否允许局域网内其他设备（如手机、平板）访问本服务器？"
    Write-Host '[Y] Yes / 允许 (Host on 0.0.0.0)'
    Write-Host '[N] No / 仅本机 (127.0.0.1; any other key selects it immediately)'
    Write-Host '[N] 仅本机（按其他任意键立即选择；20 秒未选择默认仅本机）'
    $BindHost = Read-LanBindHost
}

Write-Host ""
Write-Host "Starting Bashi Voice Factory Privacy Edition..."
Write-Host "正在启动巴适声工厂隐私版..."
Write-Host "Backend: automatic selector / 后端：自动选择"
Write-Host ""

$bindMode = Get-BindHostMode -BindHost $BindHost
$detectedLanIp = ''
$detectedLanAdapter = ''
$lanNetworkIsPublic = $false
if ($bindMode -eq 'Network') {
    # Read-only queries. The old first-default-gateway query is gone: it
    # returned whichever adapter came first, virtual ones included, and it
    # said nothing about whether the gateway is on that adapter's own subnet.
    $lanAdapters = @(
        Get-NetAdapter -ErrorAction SilentlyContinue | ForEach-Object {
            [pscustomobject]@{
                Name = $_.Name
                Status = $_.Status
                HardwareInterface = $_.HardwareInterface
                InterfaceIndex = $_.ifIndex
            }
        }
    )
    $lanAddresses = @(
        Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | ForEach-Object {
            [pscustomobject]@{
                InterfaceIndex = $_.InterfaceIndex
                IPAddress = $_.IPAddress
                PrefixLength = $_.PrefixLength
            }
        }
    )
    $lanRoutes = @(
        Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | ForEach-Object {
            [pscustomobject]@{
                InterfaceIndex = $_.InterfaceIndex
                DestinationPrefix = $_.DestinationPrefix
                NextHop = $_.NextHop
                RouteMetric = $_.RouteMetric
            }
        }
    )
    $lanInterfaceMetrics = @(
        Get-NetIPInterface -AddressFamily IPv4 -ErrorAction SilentlyContinue | ForEach-Object {
            [pscustomobject]@{
                InterfaceIndex = $_.ifIndex
                InterfaceMetric = $_.InterfaceMetric
            }
        }
    )
    $lanProfiles = @(
        Get-NetConnectionProfile -ErrorAction SilentlyContinue | ForEach-Object {
            [pscustomobject]@{
                InterfaceIndex = $_.InterfaceIndex
                NetworkCategory = $_.NetworkCategory
            }
        }
    )

    $lanSuggestion = Get-LanDisplayAddress -Adapters $lanAdapters -Addresses $lanAddresses -Routes $lanRoutes -InterfaceMetrics $lanInterfaceMetrics -NetworkProfiles $lanProfiles
    if ($lanSuggestion.Address) {
        $detectedLanIp = $lanSuggestion.Address
        $detectedLanAdapter = $lanSuggestion.AdapterName
        $lanNetworkIsPublic = $lanSuggestion.NetworkCategory -eq 'Public'
    }
}
$displayHost = Get-BindHostDisplayHost -BindHost $BindHost -DetectedLanIp $detectedLanIp

# Hand the address to app.py for the PIN block. Not a secret; a concrete bind
# address answers for itself, and an unresolved one stays empty so that app.py
# points at this output instead of naming a possibly unreachable address.
$env:BASHI_LAN_DISPLAY_HOST = ''
if ($bindMode -eq 'Network' -and $detectedLanIp) {
    $env:BASHI_LAN_DISPLAY_HOST = $detectedLanIp
}
elseif ($bindMode -eq 'Specific') {
    $env:BASHI_LAN_DISPLAY_HOST = $BindHost.Trim()
}

if ($bindMode -eq 'Local') {
    Write-Host "--------------------------------------------------------"
    Write-Host "Server is running locally. Access it at:"
    Write-Host "服务器运行在本地模式。请访问:"
    Write-Host "http://127.0.0.1:$Port"
    Write-Host "--------------------------------------------------------"
}
else {
    Write-Host "--------------------------------------------------------"
    Write-Host "Server is accessible from other devices at:"
    Write-Host "可以从局域网其他设备访问此地址:"
    if ($bindMode -eq 'Network' -and -not $detectedLanIp) {
        Write-Host "Could not determine the address other devices can use."
        Write-Host "未能确定其他设备可用的局域网地址；请在命令行运行 ipconfig，"
        Write-Host "查看「以太网」或「WLAN」的 IPv4 地址。"
    }
    else {
        Write-Host "http://${displayHost}:$Port"
        if ($detectedLanAdapter) {
            Write-Host "（网卡：$detectedLanAdapter）"
        }
    }
    Write-Host ""
    Write-Host "A one-time PIN is printed in this console; enter it on the"
    Write-Host "other device before it can do anything."
    Write-Host "控制台会打印一次性 PIN；其他设备需先输入它才能操作。"
    if ($lanNetworkIsPublic) {
        Write-Host "This network is marked as Public; Windows Firewall may block other devices."
        Write-Host "此网络被 Windows 标为「公用」，防火墙可能阻止其他设备访问。"
        Write-Host "如其他设备打不开，请检查 Windows 防火墙是否有允许本程序入站的规则。"
        Write-Host "仅在你信任这个网络时，才考虑把它改为「专用」；改为专用本身也不保证能连通。"
    }
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
