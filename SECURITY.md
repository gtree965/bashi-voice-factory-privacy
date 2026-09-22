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

## Known limitation: LAN mode has no authentication

This is a known limitation, reported here so you can decide for yourself:

- The service listens on `127.0.0.1` by default.
- In a standard start where the bind address is not preset — that is, without a `BASHI_HOST`
  environment variable and without a `-BindHost` argument — the launcher asks every time; if
  nothing is selected within 10 seconds, the answer is treated as "do not expose".
- If you choose to expose it (or preset `0.0.0.0`), the service binds `0.0.0.0`, and **the
  application has no authentication**: **any device that can reach that service port** can use it.
  The reachable set depends on your network; it is not limited to the same WiFi.
- **Only enable it on a network you trust.**
- Reporting boundary: a finding that is **exactly the behaviour disclosed above** does not need a
  private report. But if the default localhost-only mode is bypassed, if data is accessed
  unexpectedly, or for **any other new impact**, **please still use the private channel** above.

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

## 已知限制：局域网模式没有鉴权

这是一条已知限制，写在这里是为了让你自行判断：

- 服务默认只监听 `127.0.0.1`。
- 在**未预设绑定地址的标准启动**中（即没有设置 `BASHI_HOST` 环境变量、也没有传 `-BindHost` 参数），
  启动器每次都会询问；10 秒内未选择，按「不开放」处理。
- 若你选择开放（或预设为 `0.0.0.0`），服务会绑定 `0.0.0.0`，而**应用没有任何鉴权**：
  **任何能连到该服务端口的设备**都能使用它。可连到的范围取决于你的网络，不限于同一个 WiFi。
- **只在你信任的网络上开启。**
- 私密报告的边界：与上述**已披露行为完全相同**的发现，不必再走私密报告；但**默认本机模式被绕过**、
  发生意外的数据访问、或**任何其他新的影响**，**仍请通过上面的私密渠道报告**。
