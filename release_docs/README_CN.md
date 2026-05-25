[English](README.md) | **中文文档**

# 巴适声工厂 · 隐私版 (Bashi Voice Factory Privacy Edition)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](bashi-privacy-app/LICENSE)
[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](bashi-privacy-app/VERSION)
![Python](https://img.shields.io/badge/python-3.12_embed-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)

**版本：** 0.1.0

完全离线运行的本地语音工厂网页应用。首次启动联网下载完依赖与模型之后，**所有文字转语音、语音转文字、音频生成、文件保存都在你自己的电脑上完成**，没有任何音频数据上传云端。

> ⚡ 想要云端语音质量、更快的合成速度？请关注 [巴适声工厂 · 极速版 (Bashi Voice Factory Turbo)](https://github.com/gtree965/bashi-voice-factory-turbo) — 微软 Edge TTS 引擎、14 种语言、5 万字长文。需要联网。

**作者：** Alex Li (ncorecpu@gmail.com)
**许可：** [MIT License](bashi-privacy-app/LICENSE)

---

## ✨ 核心亮点

### 🔒 完全本地文字转语音
- **Qwen3-TTS-12Hz-1.7B-CustomVoice 本地推理** — 合成过程零云端调用。
- **9 个精选音色**，内置母语试听样例。
- **10 种语言**：中文（普通话、粤语、四川话、北京话、东北话）、英文（美/英）、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语。
- **自然语言指令控制** — 风格、口音、情绪都可通过 instruct 提示调整。

### 🎯 后端自动选择
- **GGUF + Vulkan**：AMD / Intel / 集成显卡用户默认路线（速度快、内存友好）。
- **PyTorch + CUDA**：NVIDIA 用户进阶路线（权重需单独下载）。
- **CPU 回退**：入门级硬件（如 Intel N100 系列）也能跑。
- 一键 **测速** 校准 ETA 估算，让等待时间贴合你这台机器。

### 🎙️ 本地离线音视频转文字 (STT)
- **SenseVoice Small**（默认，242 MB）— 中英日韩粤多语种，非自回归架构，CPU 上速度快。
- **Parakeet TDT 0.6B**（可选，661 MB）— 英文专用，NVIDIA 出品，WER 约 1.7%。
- **Silero VAD 精准分段** — 时间戳准确、零重叠、零卡顿。
- **实时滚屏字幕** SSE 流式输出；支持导出 TXT、SRT、VTT。

### 🛡️ 智能首次下载，断点续传
- **HTTP Range / resume 内置** — 一次 WiFi 闪断不会让 2.2 GB 的 GGUF 下载从零开始。
- **3 次重试，指数退避** — pip 依赖与模型文件都有同样的兜底逻辑。
- **国内友好镜像**：自动识别中国时区使用阿里云 PyPI；GGUF 运行模型走 ModelScope；STT 模型走 hf-mirror.cn。

### 📱 局域网共享，手机平板可访问
- 首次启动询问是否绑定 `0.0.0.0`，允许同一 WiFi 下其他设备访问。
- 手机浏览器输入电脑的局域网 IP 即可使用，跟本地网页一样流畅。

---

## 🚀 快速上手

### 最简流程

1. 把下载的 zip 解压到任意文件夹（桌面或随便哪里都行）。
2. 在解压后的顶层目录里 **双击 `Start_启动.bat`**。
3. 首次启动会：
   - 安装 Python 依赖（约 700 MB，根据网速 / CPU 不同需要 8-15 分钟）
   - 询问是否下载 GGUF 模型（约 2.2 GB，2-15 分钟）
   - 自动在默认浏览器打开 `http://127.0.0.1:5050`
4. 首次完成后，**之后每次启动都是离线**，5 秒左右即可打开。

### 进阶

如果想跳过顶层启动器，可以直接运行 `bashi-privacy-app\run_portable.bat`，效果完全一样。

---

## 🌐 网络行为说明

**隐私承诺**：本程序不主动联网、不上传音频、不收集使用数据。

**仅首次启动**（一次性，约 700 MB + 约 2.2 GB）：

- pip 依赖来自 `https://mirrors.aliyun.com/pypi/simple/`（海外用户默认 PyPI）
- GGUF 模型来自 `https://modelscope.cn/models/gtree592/bashi-qwen3-tts-1.7b-customvoice-gguf-runtime`
- STT 模型（用户主动点击下载）来自 `https://hf-mirror.com/csukuangfj/...`（备用 HuggingFace）

**运行时网络行为**：零。文字转语音、音视频转文字、音频导出全部本机完成。

**唯一可选联网**：UI 右下角"查看最新版本"按钮，由你主动点击时打开 files.fm 发布页。程序不自动检查更新，不在后台联网。

---

## 💻 硬件要求

下表是**作者实测**的数据。首次运行后点右侧面板的"测速"按钮，程序会根据你这台机器实际表现重新校准 ETA 估算 — 不用照搬此表。

| 硬件 | 自动选择的后端 | "你好。" 探测（25 字） | 1,000 字合成预计 | 状态 |
|---|---|---|---|---|
| AMD RX 9060 XT (16 GB) | GGUF + Vulkan | 约 3 秒 | 几分钟 | ✓ 2026-05 实测 |
| AMD RX 590 (8 GB) | GGUF + Vulkan | 3-5 秒 | 约 5-10 分钟 | ✓ 实测 |
| Intel N305 笔记本 + UHD 集显 | GGUF + Vulkan / DirectML | 53 秒 | 25-46 分钟 | ✓ 2026-05-25 实测 |
| Intel N100 迷你主机 + UHD 集显 | GGUF + Vulkan / DirectML | 126 秒 | 58 分钟 - 1 小时 49 分 | ✓ 2026-05-25 实测 |
| NVIDIA RTX / Apple Silicon / Intel Arc | — | 暂未实测 | 暂未实测 | v0.1 未验证 |

> ⚠️ **入门级 CPU（Intel N100 / N305 一类）仅适合短句试用 — 单次生成建议不超过 200 字。** 这类机器跑 5,000 字长文需要 2-9 小时。如果想做长文音频（讲座、有声书），请用独立显卡硬件（AMD RX 500/600/9000 系、NVIDIA RTX 类）。

> ℹ️ Windows 上的 NVIDIA 用户也可以走 GGUF + Vulkan 路线（NVIDIA 驱动支持 Vulkan）。PyTorch + CUDA 路线在 v0.1 需要手动配置权重，不会自动启用。

---

## 🐛 常见问题排查

| 现象 | 可能原因 / 处理 |
|---|---|
| 双击 `Start_启动.bat` 报 "Array index expression is missing" | 旧版 zip。请从 files.fm 重新下载最新版；该 BOM 问题在 v0.1.0 正式版已修复 |
| pip 安装途中 WiFi 闪断后中止 | 自动重试 3 次（5/30/120 秒退避）。3 次都失败时，修好网络后重新运行启动器即可（pip 会跳过已装好的包） |
| GGUF 下载中断 | 同样自动重试，且支持 HTTP Range 续传，重新运行启动器从 `.part` 文件续传 |
| 启动报 "No usable backend was found" | 查 `launch_log.txt`。常见原因：GGUF 运行 DLL 缺失、显卡驱动过旧、可用内存 <8 GB。程序会打印中英双语提示告知具体原因 |
| STT 下载闪过 "镜像失败" | v0.1.0 正式版不会出现 — 是旧版残留的 ModelScope 路径，已删除 |

完整日志路径：`bashi-privacy-app\launch_log.txt`

---

## 📦 zip 包目录结构

```
bashi-voice-factory-privacy-v0.1.0/
├── Start_启动.bat                                       ← 双击这里
├── README.md                                            ← 英文文档
├── README_CN.md                                         ← 本文件
├── 巴适声工厂使用手册_Bashi_Voice_Factory_User_Guide.pdf  ← 中英双语帮助 PDF
├── bashi-privacy-app/                                   ← 程序代码 + 嵌入式 Python
│   ├── run_portable.bat                                 ← 等效启动器（直接路径）
│   ├── README.md                                        ← 开发者 / 技术文档
│   └── ...
└── vulkan_backend_spike/                                ← GGUF 运行时（首次启动自动填充）
    └── Qwen3-TTS-GGUF/
```

---

## 📄 许可

[MIT License](bashi-privacy-app/LICENSE) © 2026 Alex Li

第三方组件保留各自原始许可：

- **Qwen3-TTS-12Hz-1.7B-CustomVoice**：通义实验室（阿里巴巴）Apache 2.0
- **GGUF runtime**：基于 HaujetZhao/Qwen3-TTS-GGUF
- **SenseVoice Small / Silero VAD / Parakeet TDT**：详见各自模型卡

---

## 👤 作者

**Alex Li** — ncorecpu@gmail.com

欢迎通过 GitHub release 页面或邮件提交 issue、反馈或功能建议。
