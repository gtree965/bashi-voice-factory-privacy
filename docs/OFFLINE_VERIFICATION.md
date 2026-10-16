# Offline verification

**English** | [中文](#断网验证)

> **Status: method only.** This page explains how to check, on your own computer, that the core
> tasks still work with the network switched off. **It records no result for any released
> package.** A result exists only when a filled-in record (section 7) names the package version
> and its SHA-256.

---

## 1. What this checks, and what it does not

The claim under test is narrow: **in the default local-only mode, with the network disconnected,
a package folder that has already been prepared starts through its normal launcher, synthesizes
and exports speech, and transcribes a recording and exports subtitles, without uploading text or
audio to any cloud speech service.**

It does **not** show:

- That installation or first-time preparation works without a network. First preparation
  downloads dependencies and models; this page does not list the download sources (see
  [`../PRIVACY.md`](../PRIVACY.md)).
- Anything about LAN mode. Once other devices are allowed to connect, text, uploaded media and
  returned audio travel between those devices and the computer running the app. The service
  uses plain HTTP; the one-time PIN controls access but does not encrypt the traffic.
- That the program never *tries* to connect. A disconnected run shows that the tasks finish
  without a network; it cannot show whether anything tried. See section 5.
- Anything about other hardware, other backends or other versions.

## 2. Before you disconnect: what must already be on disk

A folder that lacks any of these **cannot** finish the offline tasks. That is a boundary of the
design, not a defect found by this check; record such a run as "assets not ready".

| Asset | How it gets there | How to confirm it |
|---|---|---|
| Python dependencies | Installed by the launcher on first start | On a subsequent prepared start, `launch_log.txt` contains `[STEP] dependency check ok`; first-time installation need not produce that marker |
| Speech-synthesis model pack | Downloaded by the launcher on first start | In a Command Prompt, inside the `bashi-privacy-app` folder, run `python-3.12.10-embed-amd64\python.exe download_gguf_model.py --check-only`, then `echo %ERRORLEVEL%`; expect `0` |
| Transcription model (SenseVoice Small INT8, about 242 MB) and the voice-activity model `silero_vad.onnx` | **Not included in the package**: `models\` ships empty. Download them from the *Speech to Text* tab while online: select the model, press *Download* | The model list shows ✓ beside the model, and files exist under `models\sensevoice-small-int8\` and as `models\silero_vad.onnx` |

Optional models (the English-only transcription model, the GPU add-on, speaker labelling) are
not part of this check.

## 3. Procedure

Use your own text and recordings, or ones you are authorised to use. Nothing is asked of
reviewers; do not send private material to anyone.

**Step 0: prepare online (record it separately).** Extract the package into a new folder. Start
it with `Start_启动.bat`, let first-time preparation finish, answer the LAN question with `N`,
and download the transcription model on the *Speech to Text* tab. You may run one short synthesis
to confirm the preparation worked; note in the record whether you did. Stop the app with Ctrl+C
in the launcher window.

**Step 1: check the assets** (section 2).

**Step 2: disconnect.** Disconnect all active paths to other computers, including Ethernet,
Wi-Fi, mobile connections and any virtual or tunnel adapters. Airplane mode alone may leave
Ethernet connected.
Choose the method yourself and record each connection you disabled; this interrupts programs
using those connections, so restore them at the end. Connections to `127.0.0.1` keep working.
As a supplementary reachability check, in a Command Prompt run:

```
curl.exe --max-time 5 -sS -o NUL https://example.com
echo %ERRORLEVEL%
```

Record the output and exit code. Code `0` means this endpoint was reachable; stop and check the
disconnection. A nonzero code only means this request failed: it does not by itself prove all
network paths are disconnected. Confirm the disabled connections as well.

**Step 3: start through the normal launcher.** In the extracted folder, double-click
`Start_启动.bat`. It calls `run_portable.bat`, which starts `run_portable.ps1` in Windows
PowerShell 5.1. Do not start `app.py` by hand or run the `.ps1` from another PowerShell: that is
not the path users take. At the LAN question press `N` (any key except `Y` selects local-only,
and so does waiting 20 seconds). Wait for `Server is running locally`, then open the address it
prints, normally `http://127.0.0.1:5050`, in a browser.
Confirm the printed address is `127.0.0.1`. If it is not, stop: a preset `BASHI_HOST` or launcher
argument may have bypassed the LAN question. Remove that preset before repeating local mode.

**Step 4: synthesis.** *Text to Speech* tab, paste your text, pick a voice, press *Generate
Speech*, play the result in the page, choose MP3 in the format menu and press *Download*. Record
the text length, the voice, and the time from pressing *Generate Speech* to (a) audio you can
play and (b) completion. Say what the clock includes. Open the downloaded MP3 and check that it
plays the expected speech.

**Step 5: transcription.** *Speech to Text* tab, choose an audio or video file, check that the
model shows ✓, press *Start Transcription*. When the result appears, export TXT, SRT and VTT with
the format menu and *Export*. Open all three exported files and check that they contain the
transcript, and that the subtitle files contain timestamps. Record the recording's length and
the time taken.

**Step 6: finish.** Press Ctrl+C in the launcher window (then Enter to close it). Copy
`launch_log.txt` somewhere safe; the next start overwrites it. Restore the network and note the
time.

If anything fails or you repeat a step, put that in the record. Do not turn several attempts
into one clean run.

## 4. What the launcher log can tell you

The launcher writes `launch_log.txt` in the `bashi-privacy-app` folder. These markers identify
launcher branches that may need the network:

| Marker | Branch taken |
|---|---|
| `[STEP] Bootstrap pip` | fetches the pip bootstrap script |
| `[STEP] pip ...` (for example `pip install`, `pip index attempt`) | installs, repairs or bootstraps dependencies |
| `[mirror-probe]` | speed-tests the package mirrors |
| `[STEP] download_gguf_model.py` | downloads the model pack |

In a Command Prompt, inside the `bashi-privacy-app` folder:

```
type launch_log.txt > NUL
echo %ERRORLEVEL%
findstr /l /c:"[STEP] pip" /c:"[STEP] Bootstrap" /c:"[STEP] download_gguf" /c:"[mirror-probe]" launch_log.txt
echo %ERRORLEVEL%
```

The `type` check must return `0` without an error; otherwise stop and mark the log check invalid.
For `findstr`, code `0` means matching lines were found. Code `1` with no matching lines and no
error means no matching marker was found; a missing or unreadable file can also return `1`, so
the code alone is insufficient. Any `FINDSTR` error invalidates the check. Pip can also satisfy
an install from its cache, so a marker is not proof of an outbound connection. Their absence
does not cover unmarked paths or application behaviour.
On a start that took no network branch you should instead find `[STEP] dependency check ok`,
`[STEP] Checking GGUF runtime model pack` and `[STEP] Starting app.py`.

Two cautions:

- The launcher prints a banner about first-launch downloads on **every** start, whether or not
  anything is downloaded. Treat it as fixed text; the markers above are the signal.
- This log covers the launcher only. It says nothing about what the app does after it starts.

## 5. Looking for connection attempts (network on)

A disconnected run cannot rule out attempted connections: an attempt may fail without reaching
an observed endpoint. To look for attempts, repeat the same tasks with the
network **on** and watch from outside. The two tools below complement each other; neither is
complete. Both are short scripts listed in the appendix at the end of this page; save each as a
`.ps1` file.

**5.1 Connection polling.** In a PowerShell window run:

```
powershell -NoProfile -ExecutionPolicy Bypass -File poll_connections.ps1 -LogPath poll_log.txt
```

then start the app and do the tasks. Every 500 ms it reads the TCP connection table and prints
each new endpoint owned by a `python` or `powershell` process. Expect `listener` rows (the app's
own port) and `local` rows (the browser talking to the app). A `NON-LOOPBACK` row needs an
explanation; note that it includes addresses on your own network.

Blind spots: UDP traffic, including DNS queries, is not observed; a TCP connection shorter than
the sampling interval can be missed; only processes with
those two names are watched (your browser, other programs and the operating system are not); it
reads a table and is not a packet capture. If the tool reports `[observation-error]`, the
observation is invalid. Use a fresh log file for each run and record the observation start/end.

Other processes with these names may appear too. Record the app's PID and executable path so
you can attribute any rows to the tested app rather than an unrelated process.

**5.2 Recording proxy.** Run this in one window:

```
powershell -NoProfile -ExecutionPolicy Bypass -File record_proxy.ps1 -LogPath proxy_log.txt
```

In a Command Prompt in the package root, set the variables and start the launcher from the same
window:

```
set "HTTP_PROXY=http://127.0.0.1:8898"
set "HTTPS_PROXY=http://127.0.0.1:8898"
set "NO_PROXY=127.0.0.1,localhost"
Start_启动.bat
```

A client that honours these variables and tries to reach an outside address connects to the
recorder instead and leaves one line. Only the HTTP method and parsed host/port are retained;
userinfo, paths, query strings and fragments are omitted. A partial or malformed request line
is recorded without its contents. Nothing is
forwarded, so downloads fail in this setup; that is the point.

Blind spots: only clients that honour the variables are seen (Python's `urllib` and pip do). The
launcher's pip-bootstrap download uses Windows PowerShell 5.1's `Invoke-WebRequest`, which does not read these
variables, so it is not covered. A program that connects directly is invisible. Only programs
started from that window inherit the settings. Use a fresh log file for each run. Polling and
the proxy change what is observable; neither establishes that no attempt occurred.

**5.3 Earlier start-up observation.** Earlier checks of start-up plus local synthesis used the
same two types of observation with the network connected; the appendix scripts are new
examples, not byte-identical copies of those historical recorders. The earlier checks did not
disconnect the network and did not
include transcription or export, so they do not replace section 3. Their raw logs are not
published with this page.

## 6. How to word a result

Wording to use **only once a filled-in record supports it**:

> With the network disconnected, on package `<version>` (SHA-256 `<hash>`) on `<hardware>`,
> speech synthesis with export completed in `<completed>` of `<attempted>` attempts, and
> transcription with subtitle export in `<completed>` of `<attempted>` attempts. In a separate
> run with the network on, polling did not observe a non-loopback
> connection from `python` or `powershell` during the sampling window.

Wording that does **not** fit this evidence: "never connects", "zero network traffic",
"installation needs no network", "works on any machine". A record made by the maintainer is the
maintainer's record, not independent user feedback.

## 7. Record template

Copy this block and fill in every line. A blank means "not done", not "passed".

```
Package version:
Package SHA-256:
Where the package came from (download link or build):
Computer (CPU / GPU / RAM / Windows version):
Backend shown in the app:

Step 0   Prepared online on (date):
         Optional online test synthesis done (yes / no):
Assets   --check-only exit code:
         Transcription model shows tick (yes / no):
         models\silero_vad.onnx present (yes / no):
Network  How it was switched off:
         Disabled connections confirmed:
         curl.exe output and exit code:
Start    Started through Start_启动.bat (yes / no):
         Answer to the LAN question:
Log      type readability-check output and exit code:
         findstr output, errors and exit code:
         launch_log.txt copied to:

Synthesis      Text length and voice:
               Attempts / completed attempts:
               Time to first playable audio:
               Time to completion:
               What the clock covers:
               MP3 exported and opened (yes / no):
Transcription  Recording length:
               Attempts / completed attempts:
               Time taken:
               TXT / SRT / VTT exported and opened; subtitle timestamps checked:
Retries, failures, anything unusual:

Observation run (network on)
               Start/end time, watched process names, app PID/path, tool errors:
               Polling, NON-LOOPBACK rows (list them, or "none seen"):
               Proxy, lines recorded (count and what they were):
Network restored at:
Operator and date:
```

## 8. Limits

- One computer and one run per record; nothing here generalises to other hardware, backends or
  versions.
- Polling samples TCP only; the proxy sees only clients that honour the variables; neither covers
  UDP or other programs, and neither is a packet capture.
- Offline success depends on the assets in section 2.
- LAN mode and the optional downloads are outside this check.
- A record made by the maintainer is not independent feedback.

---

# 断网验证

[English](#offline-verification) | **中文**

> **状态：仅有方法。** 本页说明如何在你自己的电脑上检查：断开网络后，核心任务是否仍能完成。
> **本页不记录任何已发布发行包的结果。** 只有一份填好的记录（第 7 节）写明了发行包版本和
> SHA-256，才算有结果。

---

## 1. 检查什么，不检查什么

被检验的说法很窄：**在默认的仅本机模式下，断开网络后，一个已经准备好的发行包目录能经由正常
启动器启动，完成语音合成与导出、录音转写与字幕导出，且不向云端语音服务上传文本或音频。**

它**不**说明：

- 安装或首次准备无需联网。首次准备要下载依赖和模型；本页不列下载来源，见
  [`../PRIVACY.md`](../PRIVACY.md)。
- 局域网模式的任何事。开放给其他设备访问后，文本、上传的媒体和返回的音频会在这些设备与运行
  本应用的电脑之间传输。该服务使用 HTTP；一次性 PIN 控制访问，不加密传输。
- 程序从不“尝试”联网。断网运行只能说明任务无需网络即可完成，看不出有没有发起过连接。见
  第 5 节。
- 其他硬件、其他推理后端、其他版本的情况。

## 2. 断网前：磁盘上必须已有的东西

缺任何一项，都**不能**完成离线任务。这是设计边界，不是本检查发现的缺陷；这种运行请记为
“资产未就绪”。

| 资产 | 如何到位 | 如何确认 |
|---|---|---|
| Python 依赖 | 首次启动时由启动器安装 | 准备完成后的再次启动，`launch_log.txt` 含 `[STEP] dependency check ok`；首次安装不一定产生该标记 |
| 语音合成模型包 | 首次启动时由启动器下载 | 在命令提示符里，进入 `bashi-privacy-app` 文件夹，运行 `python-3.12.10-embed-amd64\python.exe download_gguf_model.py --check-only`，再运行 `echo %ERRORLEVEL%`；应为 `0` |
| 转写模型（SenseVoice Small INT8，约 242 MB）与语音活动检测模型 `silero_vad.onnx` | **不随发行包提供**：`models\` 发行时为空。联网时在“语音转文字”页下载：选中模型，点“下载” | 模型列表中该模型旁显示 ✓，且 `models\sensevoice-small-int8\` 下有文件、`models\silero_vad.onnx` 存在 |

可选模型（仅英文转写模型、GPU 附加包、说话人标注）不属于本检查。

## 3. 步骤

使用你自己的文本和录音，或你有权使用的材料。不要求评审方提交任何东西；不要把私人材料发给任何人。

**第 0 步：联网备料（单独记录）。** 把发行包解压到一个新文件夹。用 `Start_启动.bat` 启动，等首次
准备完成，局域网提示选 `N`，并在“语音转文字”页下载转写模型。可以做一次简短合成，确认备料有效；
在记录里写明做没做。然后在启动器窗口按 Ctrl+C 停止应用。

**第 1 步：核对资产**（第 2 节）。

**第 2 步：断网。** 断开所有通往其他电脑的活动网络路径，包括以太网、Wi-Fi、移动网络以及虚拟
网卡或隧道连接。只打开飞行模式可能仍保留以太网连接。方式由你选择，请逐项记录已断开的连接；使用这些连接
的程序会受影响，结束后请恢复。到 `127.0.0.1` 的本机连接不受影响。在命令提示符里做补充的可达性检查：

```
curl.exe --max-time 5 -sS -o NUL https://example.com
echo %ERRORLEVEL%
```

记录输出和退出码。退出码 `0` 表示这个地址仍可达，应停止并检查断网操作；非零仅说明这一次请求
失败，不能单独证明所有网络路径已断开，还须确认逐项记录的连接状态。

**第 3 步：经正常启动器启动。** 在解压出的文件夹里双击 `Start_启动.bat`。它调用
`run_portable.bat`，再由后者用 Windows PowerShell 5.1 启动 `run_portable.ps1`。不要手工运行
`app.py`，也不要在别的 PowerShell 里运行 `.ps1`：那不是用户实际走的路径。局域网提示按 `N`
（除 `Y` 外的任意键都选“仅本机”，等待 20 秒也一样）。等到出现 `Server is running locally`，
再在浏览器里打开它打印的地址，通常是 `http://127.0.0.1:5050`。
确认打印的地址是 `127.0.0.1`。若不是，先停止：预设的 `BASHI_HOST` 或启动参数可能跳过了局域网
询问；取消该预设，再按仅本机模式重做。

**第 4 步：合成。** “文字转语音”页，粘贴文本，选音色，点“生成语音”，在页面里试听，在格式菜单
选 MP3 并点“下载”。记录文本长度、音色，以及从点“生成语音”到 (a) 能播放出声、(b) 全部完成
各用了多久。写明计时包含什么。
打开下载的 MP3，确认能播放出预期语音。

**第 5 步：转写。** “语音转文字”页，选一个音频或视频文件，确认模型旁显示 ✓，点“开始转写”。
结果出现后，用格式菜单和“导出”分别导出 TXT、SRT、VTT。打开三个文件，确认含有转写内容，
字幕文件还须包含时间戳。记录录音时长和耗时。

**第 6 步：收尾。** 在启动器窗口按 Ctrl+C（再按回车关闭窗口）。把 `launch_log.txt` 复制到别处，
下一次启动会覆盖它。恢复网络并记下时刻。

任何一步失败或重做，都要写进记录。不要把多次尝试写成一次干净的运行。

## 4. 启动器日志能告诉你什么

启动器在 `bashi-privacy-app` 文件夹里写 `launch_log.txt`。下列标记对应可能需要网络的启动器分支：

| 标记 | 对应分支 |
|---|---|
| `[STEP] Bootstrap pip` | 下载 pip 引导脚本 |
| `[STEP] pip ...`（如 `pip install`、`pip index attempt`） | 安装、修复或引导依赖 |
| `[mirror-probe]` | 对依赖镜像测速 |
| `[STEP] download_gguf_model.py` | 下载模型包 |

在命令提示符里，进入 `bashi-privacy-app` 文件夹：

```
type launch_log.txt > NUL
echo %ERRORLEVEL%
findstr /l /c:"[STEP] pip" /c:"[STEP] Bootstrap" /c:"[STEP] download_gguf" /c:"[mirror-probe]" launch_log.txt
echo %ERRORLEVEL%
```

`type` 可读性检查须返回 `0` 且无错误，否则停止并记为日志检查无效。对 `findstr`，退出码 `0` 表示
找到匹配行；`1` 且没有匹配行、没有错误，表示没找到标记。文件不存在或不可读取也可能返回 `1`，
因此不能只看退出码。任何 `FINDSTR` 错误都使检查无效。pip 也可能从缓存完成安装，因此出现标记
不等于发起了外联。没有标记也不覆盖未标记的路径或应用行为。
未进入这些分支的准备完成后启动，应能找到
`[STEP] dependency check ok`、`[STEP] Checking GGUF runtime model pack` 和 `[STEP] Starting app.py`。

两点提醒：

- 启动器**每次**启动都会打印一段关于首次下载的横幅，不论是否真的在下载。把它当作固定文字；
  以上述标记为准。
- 这份日志只覆盖启动器，不说明应用启动之后做了什么。

## 5. 查找连接尝试（联网状态）

断网运行不能排除程序尝试联网：尝试可能在到达被观察的端点前失败。要查找尝试，
请在**联网**状态下重复同样的任务，并从外部观察。下面两个工具互为补充，都不完整。两者都是
很短的脚本，列在本页末尾的附录里，请分别保存为 `.ps1` 文件。

**5.1 连接轮询。** 在 PowerShell 窗口运行：

```
powershell -NoProfile -ExecutionPolicy Bypass -File poll_connections.ps1 -LogPath poll_log.txt
```

然后启动应用并做任务。它每 500 毫秒读一次 TCP 连接表，打印 `python` 或 `powershell` 进程名下
每个新出现的端点。应能看到 `listener` 行（应用自己的端口）和 `local` 行（浏览器与应用通信）。
出现 `NON-LOOPBACK` 行需要解释；注意它也包括你自己所在网络里的地址。

盲区：不观察 UDP（包括 DNS 查询）；比采样间隔更短的 TCP 连接可能漏掉；只监视这两个进程名
（浏览器、其他程序和操作系统都不在内）；它读的是连接表，不是抓包。若工具报
`[observation-error]`，该次观察无效。每次运行使用新的日志文件，并记录观察开始与结束时刻。

同名的其他进程也可能出现。记录被测应用的 PID 和可执行文件路径，以区分应用记录和无关进程。

**5.2 记录代理。** 在一个窗口运行：

```
powershell -NoProfile -ExecutionPolicy Bypass -File record_proxy.ps1 -LogPath proxy_log.txt
```

在发行包根目录打开命令提示符，设置变量并在同一窗口里启动启动器：

```
set "HTTP_PROXY=http://127.0.0.1:8898"
set "HTTPS_PROXY=http://127.0.0.1:8898"
set "NO_PROXY=127.0.0.1,localhost"
Start_启动.bat
```

遵守这些变量、并试图访问外部地址的客户端，会连到记录器，并留下一行。只保留 HTTP 方法与解析出的
主机、端口；用户名密码、路径、查询串和片段均不记录。不完整或无法解析的请求行只记录事件，不记录内容。
它不转发任何东西，所以这种设置下下载会失败，这正是目的。

盲区：只能看到遵守这些变量的客户端（Python 的 `urllib` 和 pip 遵守）。启动器引导 pip 时的下载
用的是 Windows PowerShell 5.1 的 `Invoke-WebRequest`，它不读这些变量，所以不在覆盖范围内。直接连接的程序
看不见。只有从该窗口启动的程序才继承这些设置。每次运行使用新的日志文件。轮询与代理各有观察边界，
两者都不能证明没有发生任何连接尝试。

**5.3 此前的启动观察。** 此前对启动与本机合成的检查用过同类的两种观察方法，当时网络是连着的；
附录脚本是新的示例，并非历史记录器的逐字节副本。
它们没有断网，也不含转写与导出，所以不能替代第 3 节。其原始日志不随本页公开。

## 6. 结果怎么表述

**只有在填好的记录支持时**才可使用的表述：

> 在断开网络的情况下，于 `<硬件>` 上使用发行包 `<版本>`（SHA-256 `<哈希>`），语音合成与导出
> 在 `<尝试次数>` 次尝试中完成 `<完成次数>` 次，转写与字幕导出在 `<尝试次数>` 次尝试中完成
> `<完成次数>` 次。在另一次联网运行中，轮询在采样期间没有观察到
> `python` 或 `powershell` 的非回环连接。

与这些证据不符的说法：“从不联网”“零网络流量”“安装也不需要网络”“在任何机器上都能用”。维护者
自己做的记录是维护者的记录，不是独立的用户反馈。

## 7. 记录模板

复制下面这段并填写每一行。空白表示“没做”，不表示“通过”。

```
发行包版本：
发行包 SHA-256：
发行包来源（下载链接或自行构建）：
电脑（CPU / GPU / 内存 / Windows 版本）：
应用中显示的后端：

第 0 步  联网备料日期：
         是否做过联网试合成（是 / 否）：
资产     --check-only 退出码：
         转写模型旁是否显示 ✓（是 / 否）：
         models\silero_vad.onnx 是否存在（是 / 否）：
网络     断网方式：
         已确认断开的各项连接：
         curl.exe 输出与退出码：
启动     是否经 Start_启动.bat 启动（是 / 否）：
         局域网提示的回答：
日志     type 可读性检查的输出与退出码：
         findstr 输出、错误与退出码：
         launch_log.txt 已复制到：

合成     文本长度与音色：
         尝试次数 / 完成次数：
         到首个可播放音频的时间：
         到全部完成的时间：
         计时包含什么：
         是否导出并打开 MP3（是 / 否）：
转写     录音时长：
         尝试次数 / 完成次数：
         耗时：
         TXT / SRT / VTT 是否导出并打开，字幕时间戳是否已查：
重试、失败、任何异常：

观察运行（联网）
         开始/结束时刻、监视进程名、应用 PID/路径、工具错误：
         轮询中的 NON-LOOPBACK 行（列出，或写“未见”）：
         代理记录的行数及内容：
网络恢复时刻：
操作者与日期：
```

## 8. 局限

- 一台电脑、每份记录一次运行；不能推广到其他硬件、后端或版本。
- 轮询只对 TCP 采样；代理只看得到遵守变量的客户端；两者都不覆盖 UDP 或其他程序，也都不是抓包。
- 离线能否成功取决于第 2 节的资产。
- 局域网模式和可选下载不在本检查范围内。
- 维护者自己做的记录不是独立反馈。

---

# Appendix: helper scripts / 附录：辅助脚本

Save each block as a `.ps1` file with the name shown. They only read the connection table or
listen on `127.0.0.1`; neither makes an outbound request. 每段保存为同名 `.ps1` 文件。它们只读取
连接表，或只监听 `127.0.0.1`，自己都不发起任何外联。

**`poll_connections.ps1`**

```powershell
# poll_connections.ps1 - read-only. Every 500 ms it reads the TCP connection
# table and prints each new endpoint owned by the watched processes.
# Stop with Ctrl+C. -LogPath records ASCII lines to a new file.
param(
    [string[]]$ProcessName = @('python', 'powershell'),
    [ValidateRange(1, 60000)]
    [int]$IntervalMilliseconds = 500,
    [string]$LogPath = ''
)

$ErrorActionPreference = 'Stop'
if ($LogPath) {
    if (Test-Path -LiteralPath $LogPath) { throw 'Use a new log file for each run.' }
    'Timestamp  Class  Endpoint' | Set-Content -LiteralPath $LogPath -Encoding ASCII
}
$seen = @{}
while ($true) {
    $watched = @(Get-Process -Name $ProcessName -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
    try { $connections = @(Get-NetTCPConnection -ErrorAction Stop) }
    catch {
        $line = '[observation-error] TCP table query failed; no conclusion can be drawn.'
        $line
        if ($LogPath) { Add-Content -LiteralPath $LogPath -Value $line -Encoding ASCII }
        exit 1
    }
    foreach ($c in $connections) {
        if ($watched -notcontains [int]$c.OwningProcess) { continue }
        $key = '{0}|{1}:{2}|{3}:{4}' -f $c.OwningProcess, $c.LocalAddress, $c.LocalPort, $c.RemoteAddress, $c.RemotePort
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        if ($c.State -eq 'Listen') { $class = 'listener' }
        elseif ($c.RemoteAddress -match '^(127\.|::1$|0\.0\.0\.0$|::$)') { $class = 'local' }
        else { $class = 'NON-LOOPBACK' }
        $line = '{0:yyyy-MM-dd HH:mm:ss.fff}  {1,-12}  pid={2}  {3}:{4} -> {5}:{6}  {7}' -f (Get-Date), $class, $c.OwningProcess, $c.LocalAddress, $c.LocalPort, $c.RemoteAddress, $c.RemotePort, $c.State
        $line
        if ($LogPath) { Add-Content -LiteralPath $LogPath -Value $line -Encoding ASCII }
    }
    Start-Sleep -Milliseconds $IntervalMilliseconds
}
```

**`record_proxy.ps1`**

```powershell
# record_proxy.ps1 - listens on 127.0.0.1 only. For every connection it prints the
# HTTP method and parsed host/port, forwards nothing and closes the connection.
# Incomplete lines and raw URL contents are never printed.
# Stop with Ctrl+C. -LogPath records ASCII lines to a new file.
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8898,
    [string]$LogPath = ''
)

$ErrorActionPreference = 'Stop'
if ($LogPath) {
    if (Test-Path -LiteralPath $LogPath) { throw 'Use a new log file for each run.' }
    'Timestamp  Client  RequestSummary' | Set-Content -LiteralPath $LogPath -Encoding ASCII
}

function Get-RequestSummary {
    param([string]$RequestLine)
    if ($RequestLine -notmatch '^(GET|HEAD|POST|PUT|DELETE|OPTIONS|PATCH|CONNECT) ([^\s]+) HTTP/1\.[01]$') {
        return '<unparsed request line>'
    }
    $method = $Matches[1]
    $target = $Matches[2]
    if ($method -eq 'CONNECT') { $target = 'http://' + $target + '/' }
    $uri = $null
    if (-not [Uri]::TryCreate($target, [UriKind]::Absolute, [ref]$uri) -or
        $uri.Scheme -notin @('http', 'https') -or -not $uri.Host) {
        return ($method + ' <unparsed target>')
    }
    return ('{0} {1}:{2}' -f $method, $uri.DnsSafeHost, $uri.Port)
}

$listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Port)
$listener.Start()
Write-Host "Recording on 127.0.0.1:$Port - nothing is forwarded. Ctrl+C to stop."
try {
    while ($true) {
        $client = $listener.AcceptTcpClient()
        try {
            $client.ReceiveTimeout = 1500
            $request = '<request line unavailable>'
            $stream = $client.GetStream()
            $bytes = New-Object byte[] 8192
            $used = 0
            while ($used -lt $bytes.Length) {
                $count = $stream.Read($bytes, $used, $bytes.Length - $used)
                if ($count -eq 0) { break }
                $used += $count
                $text = [System.Text.Encoding]::ASCII.GetString($bytes, 0, $used)
                $newline = $text.IndexOf([char]10)
                if ($newline -ge 0) {
                    $request = Get-RequestSummary ($text.Substring(0, $newline).TrimEnd([char]13))
                    break
                }
            }
            $line = '{0:yyyy-MM-dd HH:mm:ss.fff}  {1}  {2}' -f (Get-Date), $client.Client.RemoteEndPoint, $request
            $line
            if ($LogPath) { Add-Content -LiteralPath $LogPath -Value $line -Encoding ASCII }
        }
        catch [System.IO.IOException] {
            $line = '{0:yyyy-MM-dd HH:mm:ss.fff}  {1}  <request line unavailable>' -f (Get-Date), $client.Client.RemoteEndPoint
            $line
            if ($LogPath) { Add-Content -LiteralPath $LogPath -Value $line -Encoding ASCII }
        }
        finally {
            $client.Close()
        }
    }
}
finally {
    $listener.Stop()
}
```
