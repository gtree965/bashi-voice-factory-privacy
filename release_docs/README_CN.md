[English](README.md) | **中文文档**

# 巴适声工厂 · 隐私版 (Bashi Voice Factory Privacy Edition)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.1.3-blue.svg)](VERSION)
![Python](https://img.shields.io/badge/python-3.12_embed-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)

**版本：** 0.1.3

完全离线运行的本地语音工厂网页应用。首次启动联网下载完依赖与模型之后，**所有文字转语音、语音转文字、音频生成、文件保存都在你自己的电脑上完成**，没有任何音频数据上传云端。

> ⚡ 想要云端语音质量、更快的合成速度？请关注 [巴适声工厂 · 极速版 (Bashi Voice Factory Turbo)](https://github.com/gtree965/bashi-voice-factory-turbo) — 微软 Edge TTS 引擎、14 种语言、5 万字长文。需要联网。

**作者：** Alex Li (ncorecpu@gmail.com)
**许可：** [MIT License](LICENSE)
**源码：** <https://github.com/gtree965/bashi-voice-factory-privacy>
**下载：** [GitHub Releases](https://github.com/gtree965/bashi-voice-factory-privacy/releases) · [files.fm 镜像](https://files.fm/u/juvstxmrez)

---

## 🆕 v0.1.3 更新内容

- **更稳妥的 STT 默认方案：** SenseVoice Small 现为默认多语种 STT 模型，Speaker ID 界面已停用，并从产品中移除了 Paraformer 中文大模型。
- **上传与任务状态加固：** 新增服务端上传硬上限（默认 2 GB），并为共享 `stt_jobs` 状态加入线程锁，覆盖后台任务与 API 读取路径。
- **更可靠的流式处理：** 受影响的前端 SSE 读取器现在会跨网络 chunk 缓冲数据，避免被拆开的 JSON 行或事件帧丢失、误解析。

---

## ✨ 核心亮点

### 🔒 完全本地文字转语音
- **Qwen3-TTS-12Hz-1.7B-CustomVoice 本地推理** — 合成过程零云端调用。
- **9 个精选音色**，内置母语试听样例。
- **10 种语言**：中文（普通话、粤语、四川话、北京话、东北话）、英文（美/英）、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语。
- **自然语言指令控制** — 风格、口音、情绪都可通过 instruct 提示调整。

### 🎯 后端自动选择
- **GGUF + Vulkan**：AMD / Intel / 集成显卡用户默认路线（速度快、内存友好）。
- **GGUF + CUDA**：NVIDIA 用户一键应用内升级（可选 ~595 MB 附加包下载，无需手动配置权重）。v0.1.1 新增。
- **更可靠的 NVIDIA 检测与启动探测**：v0.1.2 可穿透虚拟显示层识别真实 NVIDIA 显卡，并隔离原生探测崩溃，让启动器显示可处理的错误而不是直接消失。
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
   - 缺少 GGUF 模型时自动下载（约 2.2 GB，2-15 分钟；可按 Ctrl+C 取消，下次启动会续传）
   - 自动在默认浏览器打开 `http://127.0.0.1:5050`
4. 首次完成后，**之后每次启动都是离线**，5 秒左右即可打开。

### 进阶

如果想跳过顶层启动器，可以直接运行 `bashi-privacy-app\run_portable.bat`，效果完全一样。

---

## 🌐 网络行为说明

**隐私承诺**：本程序不主动联网、不上传音频、不收集使用数据。**程序永远不会自动检查任何在线资源。** 所有联网行为均在下文有完整说明，且需要用户主动触发 — 无后台轮询、无统计分析、无静默更新探测。

**仅首次启动**（一次性，约 700 MB + 约 2.2 GB）：

- pip 依赖来自 `https://mirrors.aliyun.com/pypi/simple/`（海外用户默认 PyPI）
- GGUF 模型来自 `https://modelscope.cn/models/gtree592/bashi-qwen3-tts-1.7b-customvoice-gguf-runtime`
- STT 模型（用户主动点击下载）来自 `https://hf-mirror.com/csukuangfj/...`（备用 HuggingFace）

**运行时网络行为**：零。文字转语音、音视频转文字、音频导出全部本机完成。

**可选 CUDA 加速**（NVIDIA 用户，仅用户主动触发）：检测到 NVIDIA 显卡时，UI 会显示"升级到 CUDA 加速"横幅。点击后从 `https://modelscope.cn/models/gtree592/bashi-qwen3-tts-cuda-runtime` 下载一次性 ~595 MB CUDA 运行时附加包。完全可选 — 不下载也能用 Vulkan 路线。不点就不会下载任何东西。

**手动更新检查**（仅用户主动触发，永不自动）：UI 右下角"查看最新版本"按钮在新浏览器标签页打开发布页。也可以随时手动访问：

- GitHub Releases: <https://github.com/gtree965/bashi-voice-factory-privacy/releases>
- files.fm 镜像: <https://files.fm/u/juvstxmrez>

**离网 / 敏感场景部署**（银行、医疗、政务、企业内网）：在联网机器上完成首次启动的所有下载后，整个 `bashi-voice-factory-privacy-v0.x.0/` 解压文件夹可以原样拷贝到离网/物理隔离机器上运行，之后所有功能均无需任何网络访问。程序没有任何遥测端点需要防火墙拦截，没有自动更新守护进程，也没有回调 URL。可用 Wireshark / 资源监视器在正常使用过程中监测出站流量验证 — 应当全程静默。

---

## 💻 硬件要求

下表是**作者实测**的数据。首次运行后点右侧面板的"测速"按钮，程序会根据你这台机器实际表现重新校准 ETA 估算 — 不用照搬此表。

| 硬件 | 自动选择的后端 | "你好。" 探测（25 字） | 1,000 字合成预计 | 状态 |
|---|---|---|---|---|
| AMD RX 9060 XT (16 GB) | GGUF + Vulkan | 约 3 秒 | 几分钟 | ✓ 2026-05 实测 |
| AMD RX 590 (8 GB) | GGUF + Vulkan | 3-5 秒 | 约 5-10 分钟 | ✓ 实测 |
| Intel N305 笔记本 + UHD 集显 | GGUF + Vulkan / DirectML | 53 秒 | 25-46 分钟 | ✓ 2026-05-25 实测 |
| Intel N100 迷你主机 + UHD 集显 | GGUF + Vulkan / DirectML | 126 秒 | 58 分钟 - 1 小时 49 分 | ✓ 2026-05-25 实测 |
| NVIDIA RTX 5070（12 GB，云电脑） | GGUF + Vulkan + DirectML | 约 1 秒 | 41 秒 - 1 分 17 秒 | ✓ 2026-06-12 海马云 HMv Cloud PC 实测（Vulkan 路径） |
| 其它 NVIDIA RTX / GTX（桌面） | GGUF + Vulkan + DirectML · 可选 CUDA 附加包 | 待社区报数 | 待社区报数 | 等待桌面 tester 通过 GitHub Issues 报数 |
| Apple Silicon / Intel Arc | — | 暂未实测 | 暂未实测 | 尚未验证 |

> ⚠️ **入门级 CPU（Intel N100 / N305 一类）仅适合短句试用 — 单次生成建议不超过 200 字。** 这类机器跑 5,000 字长文需要 2-9 小时。如果想做长文音频（讲座、有声书），请用独立显卡硬件（AMD RX 500/600/9000 系、NVIDIA RTX 类）。

> ℹ️ **NVIDIA 用户（桌面 RTX / GTX）**：默认路线是 GGUF + Vulkan（NVIDIA 驱动支持 Vulkan）。想要原生 CUDA 加速，点击应用内一键升级横幅（v0.1.1+）— 会下载 ~595 MB CUDA 运行时附加包，无需手动配置权重。**需要 NVIDIA 驱动 ≥ 545.x 才能使用 CUDA 12.4 运行时。** Vulkan 路径在 RTX 5070（云电脑）实测：**25 字探测 1 秒**，桌面 NVIDIA 用户的默认 Vulkan 体验已经非常顺畅。CUDA 附加包 A/B 数字 + 其它 RTX/GTX 卡的报数欢迎通过 [GitHub Issues](https://github.com/gtree965/bashi-voice-factory-privacy/issues) 反馈。云端数据中心 NVIDIA 显卡（A10/A100/T4）在 TCC 模式下需要额外设置 — 见下方常见问题排查。

### 🧩 硬件兼容性矩阵

除了上表里具体测过的几台机器，下表说明主流 Windows 硬件在自动后端选择下走的加速路径：

| 硬件类别 | 实际加速路径 | 状态 |
|---|---|---|
| NVIDIA RTX 30 / 40 / 50（桌面） | 默认 GGUF + Vulkan · 可选 CUDA 应用内升级 | ✅ RTX 5070 2026-06-12 实测：Vulkan 路径 25 字探测约 1 秒（云电脑 海马云）。CUDA 附加包 A/B 数字 + 其它卡报数欢迎通过 Issues 反馈。CUDA add-on 需驱动 ≥ 545.x。 |
| NVIDIA GTX 10 / 16（桌面） | 默认 GGUF + Vulkan · 可选 CUDA 应用内升级 | ✅ 同一流程，同样驱动要求；报数欢迎通过 Issues。 |
| NVIDIA 数据中心卡（A10 / A100 / T4） | 需要手动配置 | ⚠️ TCC 模式 + 云端老驱动 = 需要手动 workaround。见常见问题排查。 |
| AMD RX 500 / 600 / 7000 / 9000（独立显卡） | GGUF + Vulkan + DirectML | ✅ 实测（RX 590、RX 9060 XT） |
| Intel Arc A 系列（A380 / A580 / A750 / A770） | GGUF + Vulkan + DirectML | ✅ 理论可用、未实测 |
| Intel 集显（UHD / Iris Xe / Arc iGPU） | GGUF + Vulkan + DirectML | ✅ 实测（Intel N305 UHD） |
| AMD APU 集显（Vega 7/8、RDNA 2/3） | GGUF + Vulkan + DirectML | ✅ 理论可用、未实测 |
| 纯 CPU（无可用 GPU / 无驱动） | GGUF + CPU（ggml-cpu 自动 SIMD） | ✅ 可用；仅在无 GPU 时自动选择 |
| NPU（Snapdragon X / Lunar Lake / Ryzen AI 300） | — | ❌ 暂未利用 |
| ARM64 Windows（Snapdragon X Copilot+ PC） | — | ❌ 暂不支持（走 x64 仿真较慢） |

### ⚙️ 已知限制（路线图）

- **NVIDIA CUDA 为可选项，不内置。** NVIDIA 显卡默认走 Vulkan 路线；原生 CUDA 加速需点击应用内一键升级（~595 MB 附加包，v0.1.1+）。这样主下载包对 AMD / Intel / CPU 大多数用户保持精简。需 NVIDIA 驱动 ≥ 545.x。
- **弱集显可能比纯 CPU 还慢。** Intel N100 类硬件上，DirectML / Vulkan 的数据传输与调度开销可能盖过 GPU 收益。可在 cmd 窗口里 `set GGUF_LLM_USE_GPU=0 && set GGUF_ONNX_PROVIDER=CPU` 后再启动来 A/B 测试，欢迎反馈实测数字。
- **NPU 加速尚未利用**（Snapdragon X Elite、Intel Lunar Lake AI Boost、AMD Ryzen AI 300）。v0.2+ 调研中。
- **ARM64 Windows 暂未原生支持**（Surface Pro 11、Galaxy Book4 Edge 等）。x64 仿真能跑但速度受限。原生 ARM64 构建是 v0.3+ 候选。

---

## 🐛 常见问题排查

| 现象 | 可能原因 / 处理 |
|---|---|
| 双击 `Start_启动.bat` 报 "Array index expression is missing" | 旧版 zip。请从 GitHub Releases 或 files.fm 镜像重新下载最新版；该 BOM 问题在 v0.1.0 正式版已修复 |
| pip 安装途中 WiFi 闪断后中止 | 自动重试 3 次（5/30/120 秒退避）。3 次都失败时，修好网络后重新运行启动器即可（pip 会跳过已装好的包） |
| pip 安装失败并提示 "long path support" | 按启动器提示，在管理员 PowerShell 中运行一次注册表命令，然后重新启动 |
| GGUF 下载中断 | 同样自动重试，且支持 HTTP Range 续传，重新运行启动器从 `.part` 文件续传 |
| 启动报 "No usable backend was found" | 查 `launch_log.txt`。常见原因：GGUF 运行 DLL 缺失、显卡驱动过旧、可用内存 <8 GB。程序会打印中英双语提示告知具体原因 |
| STT 下载闪过 "镜像失败" | v0.1.0 正式版不会出现 — 是旧版残留的 ModelScope 路径，已删除 |
| 云端 / 数据中心 NVIDIA 显卡（A10 / A100 / T4，国内云 Windows 镜像）：`access violation reading 0x0000000000000000` 或 `GGUF probe failed` | 数据中心 NVIDIA 显卡通常运行在 **TCC 模式**（Vulkan/DirectML 被屏蔽），且驱动版本较旧（~538.x）跟 CUDA 12.4 add-on 不兼容。**桌面 RTX/GTX 显卡不受影响**（默认 WDDM 模式 + 现代驱动）。v0.1.2 会隔离并报告原生启动探测崩溃，不再让启动器直接退出，但 TCC 配置仍需手动 workaround：(1) 把 `vulkan_backend_spike\Qwen3-TTS-GGUF\qwen3_tts_gguf\inference\bin\ggml-vulkan.dll` 重命名为 `.disabled`；(2) 编辑 `bashi-privacy-app\run_portable.ps1`，在 `Remove-Item Env:USE_GGUF_BACKEND` 行（约第 270 行）之后加上 `$env:USE_GGUF_BACKEND = "1"` + `$env:GGUF_ONNX_PROVIDER = "CPU"`；(3) 命令行预装 CUDA add-on：`python download_cuda_runtime.py`。CUDA 12.4 需要 NVIDIA 驱动 ≥ 545.x。TCC 自动处理仍计划在后续补丁实现。 |

完整日志路径：`bashi-privacy-app\launch_log.txt`

---

## 📦 zip 包目录结构

```
bashi-voice-factory-privacy-v0.1.3/
├── Start_启动.bat                                       ← 双击这里
├── Start_CPU_only_仅CPU启动.bat                         ← 强制 CPU 模式（入门集显 A/B 对比用）
├── README.md                                            ← 英文文档
├── README_CN.md                                         ← 本文件
├── LICENSE                                              ← MIT 许可证
├── VERSION                                              ← 发布版本号
├── 巴适声工厂隐私版使用手册_Bashi_Voice_Factory_Privacy_Edition_User_Guide.pdf
│                                                         ← 中英双语帮助 PDF
├── bashi-privacy-app/                                   ← 程序代码 + 嵌入式 Python
│   ├── run_portable.bat                                 ← 等效启动器（直接路径）
│   ├── README.md                                        ← 项目说明副本
│   └── ...
└── vulkan_backend_spike/                                ← GGUF 运行时（首次启动自动填充）
    └── Qwen3-TTS-GGUF/
```

---

## 📄 许可

[MIT License](LICENSE) © 2026 Alex Li

第三方组件保留各自原始许可：

- **Qwen3-TTS-12Hz-1.7B-CustomVoice**：通义实验室（阿里巴巴）Apache 2.0
- **GGUF runtime**：基于 HaujetZhao/Qwen3-TTS-GGUF
- **SenseVoice Small / Silero VAD / Parakeet TDT**：详见各自模型卡

---

## 👤 作者

**Alex Li** — ncorecpu@gmail.com

欢迎通过 GitHub release 页面或邮件提交 issue、反馈或功能建议。
