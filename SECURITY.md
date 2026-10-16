# Security Policy

**English** | [中文](#安全策略)

## Reporting a vulnerability

Please report security issues **privately** through GitHub private vulnerability reporting:
<https://github.com/gtree965/bashi-voice-factory-privacy/security/advisories/new>

Please do **not** open a public issue for a vulnerability: a public report describes the problem
before it can be handled. Feature requests, bugs that are not security issues, and questions about
the privacy posture belong in the public issue tracker instead:
<https://github.com/gtree965/bashi-voice-factory-privacy/issues>

## Scope

Security reports are handled for the **latest released version**
(<https://github.com/gtree965/bashi-voice-factory-privacy/releases>). This project has a **single
maintainer**, and how reports are triaged is documented in
<https://github.com/gtree965/bashi-voice-factory-privacy/blob/main/docs/MAINTENANCE.md>: security
and blocking problems are looked at first. We **do not promise response times, fix times, or a
triage frequency** — with one maintainer, promising a schedule would not be honest.

## What to include

- the affected version (the release you observed it on);
- the steps to reproduce it;
- the impact you observed, and what you expected instead.

## Please do not attach raw logs

This application runs on your own machine and is privacy-first, and its logs can contain file
paths, text you submitted for synthesis or transcription, and other content from your machine.
**Do not paste raw logs** into a report; quote only the minimum needed, and remove anything
personal first.

## LAN access: what the PIN protects and what it does not

The service listens on `127.0.0.1` by default. In a standard start (no `BASHI_HOST` environment
variable and no `-BindHost` argument) the launcher asks every time whether other devices on your
network may connect; if you do not answer within 20 seconds, it stays local-only.

If you allow it, other devices must first enter a **one-time six-digit PIN** that is printed in the
console of the computer running the app. The PIN changes on every start and is never written to a
log. These are the boundaries of that protection, stated here so you can decide for yourself:

- **The connection is plain HTTP, not encrypted.** Anyone who can watch traffic on the same network
  can read the PIN and the session cookie. The PIN stops "anyone who connects can use it"; it does
  not make the link secure. **Only enable LAN access on a network you trust.**
- **Do not put the app behind a reverse proxy** (for example a local Caddy or nginx that adds HTTPS).
  Requests forwarded by a proxy on the same computer arrive from `127.0.0.1`, which the app treats as
  the computer itself, so they would skip the PIN.
- Other devices must use the computer's **IP address**, such as `http://192.168.1.52:5050`. Host names,
  including `*.local` names, are refused on purpose.
- Supported bind addresses are loopback, `0.0.0.0`, or one IPv4 address. A non-loopback IPv6 address
  or a host name is refused at start-up. If you preset one specific IPv4 address, `127.0.0.1` is not
  listening, so the computer itself must also open that address and enter the PIN.
- **Lockouts can be abused.** Someone on the same network can enter wrong PINs on purpose so that new
  devices cannot sign in for a while. The global lockout lasts at most 60 minutes. Devices that are
  already signed in keep working. When LAN access was allowed at the start-up prompt (the app then
  listens on all addresses, `0.0.0.0`), the computer's own browser at `http://127.0.0.1:5050` also keeps
  working; if you preset one specific IPv4 address instead, the computer signs in like any other device.
  Restarting the app clears the lockout and issues a new PIN. For a demonstration, sign in on the demo
  device before you start.
- A session ends when the app restarts, or 12 hours after sign-in, whichever comes first. Closing the
  browser is **not** guaranteed to end it: browsers that restore the previous session may keep the
  cookie.
- Reporting boundary: a finding that is **exactly the behaviour described above** does not need a
  private report. If the default local-only mode is bypassed, data is accessed unexpectedly, the PIN
  can be skipped, or you see **any other new impact**, please use the private channel above.


## Security fixes in v0.1.6

These problems exist in earlier releases and are fixed in v0.1.6. Details are in the changelog.

- **Dependency installation did not verify HTTPS certificates.** The launcher passed pip's
  `--trusted-host` option, which also switches off certificate checks for that host. Someone able to
  intercept traffic on your network could therefore have tampered with packages during installation.
  It only affected the start that installs or repairs dependencies (the first start, or a start after
  the dependency check failed):
  - v0.1.0–v0.1.2: only when a Chinese language or China time zone was detected, for
    `mirrors.aliyun.com`;
  - v0.1.3–v0.1.5: for every user, for each package index in use (Aliyun, Tsinghua and `pypi.org` in
    China; `pypi.org` elsewhere; and any index set with `BASHI_PIP_INDEX_URL`).
  If you first installed on a network you do not trust, extract v0.1.6 into a **new folder** and start
  it once, so that the dependencies are installed again with certificate checks, instead of upgrading
  the old folder in place.
- **Any web page could trigger three actions in the default local-only mode.** While the app was
  running, a page open in the same computer's browser could send a simple cross-site request that
  started loading the model (`POST /api/warmup`), started downloading the CUDA runtime
  (`POST /api/cuda-upgrade/download`), or uploaded a file for transcription (`POST /api/stt/transcribe`).
  Such a page could not read the results. From v0.1.6, a request that changes state is checked for the
  `Sec-Fetch-Site` and `Origin` headers that browsers attach: if either is present, the request is
  refused unless it comes from the app's own page. Current browsers attach at least one of these
  headers to such cross-site requests, so a web page can no longer trigger these actions. A request that
  carries neither header, such as one sent by a command-line tool, is not blocked by this check.


---

# 安全策略

[English](#security-policy) | **中文**

## 报告漏洞

请通过 GitHub 私密漏洞报告**私下**提交安全问题：
<https://github.com/gtree965/bashi-voice-factory-privacy/security/advisories/new>

**请不要**用公开 Issue 报告漏洞：公开报告会在问题被处理之前把它描述出来。功能建议、非安全类缺陷，
以及关于隐私立场的疑问，请走公开 Issue 跟踪器：
<https://github.com/gtree965/bashi-voice-factory-privacy/issues>

## 处理范围

安全问题只针对**最新发布版**处理
（<https://github.com/gtree965/bashi-voice-factory-privacy/releases>）。本项目由**单一维护者**维护，
分诊方式记录在
<https://github.com/gtree965/bashi-voice-factory-privacy/blob/main/docs/MAINTENANCE.md>：安全与阻断类
问题优先看。我们**不承诺响应时限、修复时限，也不承诺分诊频率**——只有一位维护者，承诺时间表是不诚实的。

## 报告里请包含

- 受影响的版本（你观察到问题的那个发布版）；
- 复现步骤；
- 你观察到的影响，以及你原本预期的结果。

## 请不要附日志原文

本应用在你自己的机器上运行、隐私优先，其日志可能包含文件路径、你提交合成或转写的文本，
以及来自你机器的其他内容。**不要把日志原文**贴进报告；只引用必需的最小片段，并先去掉个人信息。

## 局域网访问：PIN 能挡住什么、挡不住什么

服务默认只监听 `127.0.0.1`。在**未预设绑定地址的标准启动**中（没有设置 `BASHI_HOST` 环境变量、也没有传 `-BindHost`
参数），启动器每次都会询问是否允许局域网内其他设备连接；20 秒内未作选择，就保持仅本机。

如果你选择允许，其他设备必须先输入**一次性 6 位 PIN**，它打印在运行本程序那台电脑的控制台里，每次启动都会更换，
不会写入任何日志。下面是这层保护的边界，写在这里是为了让你自行判断：

- **链路是明文 HTTP，不是加密。** 同一网络里能监听流量的人可以读到 PIN 和会话 cookie。PIN 挡的是「谁连上来都能用」，
  不能让链路变安全。**只在你信任的网络上开启局域网访问。**
- **不要把本程序放在反向代理之后**（例如在本机用 Caddy、nginx 加一层 HTTPS）。本机代理转发来的请求来源是
  `127.0.0.1`，本程序会把它当作这台电脑本身，从而跳过 PIN。
- 其他设备必须用这台电脑的 **IP 地址**访问，例如 `http://192.168.1.52:5050`。主机名（包括 `*.local` 这类名字）会被有意拒绝。
- 绑定地址只支持三类：回环地址、`0.0.0.0`、一个具体的 IPv4 地址。非回环 IPv6 地址和主机名会在启动时被拒绝。如果预设的是
  某一个具体 IPv4 地址，`127.0.0.1` 并不监听，这台电脑本身也要打开那个地址并输入 PIN。
- **锁定可能被滥用。** 同一网络里的人可以故意输错 PIN，让新设备在一段时间内登录不了。全局锁定最长 60 分钟。已经登录的
  设备不受影响。如果是在启动询问时允许了局域网访问（此时程序监听所有地址 `0.0.0.0`），这台电脑经 `http://127.0.0.1:5050`
  访问的浏览器也不受影响；如果预设的是某一个具体 IPv4 地址，这台电脑和其他设备一样需要登录。重启程序会清零并换一个新 PIN。
  演示前，请先在演示设备上登录好。
- 会话在程序重启时、或登录满 12 小时时结束，以先到者为准。**不保证关掉浏览器就会结束**：会恢复上次会话的浏览器可能保留
  这个 cookie。
- 私密报告的边界：与上述**已说明的行为完全相同**的发现，不必走私密报告；但如果**默认本机模式被绕过**、发生意外的数据访问、
  PIN 可以被跳过，或出现**任何其他新的影响**，仍请通过上面的私密渠道报告。


## v0.1.6 修复的安全问题

以下问题存在于此前的版本，已在 v0.1.6 修复。细节见更新日志。

- **安装依赖时没有校验 HTTPS 证书。** 启动器给 pip 传了 `--trusted-host` 选项，而这个选项会同时关闭对该主机的证书校验。
  因此，能在你的网络上截获流量的人，可能在安装过程中篡改安装包。它只影响**安装或修复依赖的那次启动**（首次启动，
  或依赖检查失败后的启动）：
  - v0.1.0–v0.1.2：仅当检测到中文语言或中国时区时，影响 `mirrors.aliyun.com`；
  - v0.1.3–v0.1.5：影响所有用户所用的每个依赖源（中国环境下的阿里云、清华、`pypi.org`；其他环境下的 `pypi.org`；
    以及用 `BASHI_PIP_INDEX_URL` 指定的源）。
  如果你当初是在不可信的网络上首次安装的，请把 v0.1.6 解压到一个**新文件夹**里启动一次，让依赖在校验证书的前提下重新安装，
  不要在旧文件夹上直接覆盖升级。
- **默认本机模式下，任意网页都能触发三个操作。** 本程序运行时，同一台电脑的浏览器里打开的网页，可以发送一种简单的跨站请求，
  让本程序开始加载模型（`POST /api/warmup`）、开始下载 CUDA 运行库（`POST /api/cuda-upgrade/download`），或上传文件进行转写
  （`POST /api/stt/transcribe`）。那个网页读不到结果。从 v0.1.6 起，改变状态的请求会检查浏览器附带的 `Sec-Fetch-Site` 与
  `Origin` 请求头：只要带了其中任何一个，就只接受来自本程序自己页面的请求。当前的浏览器在这类跨站请求上至少会带其中一个，
  所以网页已无法再触发这些操作。两个请求头都不带的请求（例如命令行工具发出的）不受这项检查拦截。
