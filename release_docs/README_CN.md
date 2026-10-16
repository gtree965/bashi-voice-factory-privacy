[English](README.md) | **中文文档**

# 巴适声工厂 · 隐私版 (Bashi Voice Factory Privacy Edition)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.1.6-blue.svg)](VERSION)
![Python](https://img.shields.io/badge/python-3.12_embed-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)

**版本：** 0.1.6

在自己电脑上运行的语音工具：合成与转写使用本地模型，不向云端语音服务上传文本或音频。断网使用前须联网备齐所需资产。默认仅本机访问；主动开启局域网后，数据会经明文 HTTP 在设备之间传输。

**作者：** Alex Li (ncorecpu@gmail.com)
**许可：** [MIT License](LICENSE)
**源码：** <https://github.com/gtree965/bashi-voice-factory-privacy> · <https://gitee.com/gtree965/bashi-voice-factory-privacy>（国内镜像）
**贡献指南：** <https://github.com/gtree965/bashi-voice-factory-privacy/blob/main/CONTRIBUTING.md>
**下载：** [GitHub Releases](https://github.com/gtree965/bashi-voice-factory-privacy/releases) · [Gitee](https://gitee.com/gtree965/)（国内推荐）

---

## 🆕 v0.1.6 更新内容

- 局域网一次性 PIN、失败次数限制、Host 与跨站请求检查；HTTP 仍未加密，仅用于可信网络。见[安全边界与修复](SECURITY.md)。
- 依赖源测速排序和回退，恢复 HTTPS 证书校验；启动询问等待 20 秒，默认仅本机，改进局域网地址提示。
- 随包提供双语隐私说明和断网核查方法；出包前核对手册链接及提取后的可读文本。

---

## v0.1.5 更新内容

- **发行包内首次附带完整第三方许可材料：** `THIRD_PARTY.md`、`THIRD_PARTY_GAPS.md` 与 `licenses/` 整目录，共 34 份（含上游 Qwen3-TTS-GGUF 转换运行时的 MIT 原文）。
- **界面页脚许可表述修正：** 改为「项目代码 MIT；模型与第三方组件遵循各自许可条款」，不再对整个发行包作统一授权承诺。
- **导出文件名修正。**
- **快速开始的启动说明修正。**
- **构建期新增许可材料落包门禁：** 确保每次发行包内的许可原文与仓库一致。

---

## v0.1.4 更新内容

- **首次合成更快：** 界面加载时即异步预热完整 TTS 链路，用一次丢弃式合成代替单纯加载模型。界面显示中性的预热状态；预热期间的早到请求会等待，而不是直接失败。
- **修复 PDF 使用手册：** 随包分发的手册不再带有指向构建机器本地目录的失效内链，手册内所有链接均为公开 HTTPS 地址。
- **构建期门禁：** 打包时若手册中存在任何非 HTTPS 链接即拒绝出包，杜绝此类缺陷复发。
- **Gitee 镜像：** 源码与下载新增 Gitee 入口，方便中国大陆用户访问。

---

## ✨ 核心亮点

### 🔒 完全本地文字转语音
- **Qwen3-TTS-12Hz-1.7B-CustomVoice 本地推理** — 合成过程零云端调用。
- **9 个精选音色**，内置母语试听样例。
- **10 种语言**：中文（普通话、粤语、四川话、北京话、东北话）、英文（美/英）、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语。
- **自然语言指令控制** — 风格、口音、情绪都可通过 instruct 提示调整。
- **长文与跟读流式控制** — 可停止合成并保留已完成片段；默认自动播放首个就绪片段，后续片段生成后自动续播；GGUF 长文试听结束后仍保留可拖动、可下载的完整 MP3。

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
- **失败重试与恢复** — 依赖安装失败时重试或换源；模型下载保留断点和指数退避。
- **下载源选择**：中国语言或时区环境下先测速排序，失败时换源；合成资产来自 ModelScope，转写模型优先 hf-mirror.com、失败后回退上游。

### 📱 局域网共享，手机平板可访问
- 启动时询问是否允许局域网内其他设备连接（等待 20 秒，默认仅本机）。
- 允许后，控制台会显示访问地址（例如 `http://192.168.1.52:5050`）和一次性 6 位 PIN，其他设备须先输入 PIN。
- 链路是明文 HTTP，请只在信任的网络上开启。PIN 能挡住什么、挡不住什么，见 [SECURITY.md](SECURITY.md)。

---

## 🚀 快速上手

### 最简流程

**系统前提：** 64 位 Windows、Windows 长路径支持，以及 [Microsoft Visual C++ x64 运行库](https://aka.ms/vs/17/release/vc_redist.x64.exe)。全新 Windows 或隔离环境可能需要单独安装此运行库，便携 ZIP 不包含它。若启动器提示长路径未启用，请先按控制台指引完成设置，再重试。断网前须备齐这些系统条件。

1. 把下载的 zip 解压到任意文件夹（桌面或随便哪里都行）。
2. 在解压后的顶层目录里 **双击 `Start_启动.bat`**。
3. 首次启动会：
   - 安装 Python 依赖（约 700 MB，根据网速 / CPU 不同需要 8-15 分钟）
   - 缺少 GGUF 模型时自动下载（约 2.2 GB，2-15 分钟；可按 Ctrl+C 取消，下次启动会续传）
   - 启动完成后，命令行窗口会显示访问地址；请在你想用的浏览器里手动打开 `http://127.0.0.1:5050`（应用不会自动打开浏览器）
4. 依赖和所需模型备齐后，核心任务可断网使用。断网前须在模型管理器下载转写模型及 VAD；修复和可选下载仍需联网。

### 进阶

如果想跳过顶层启动器，可以直接运行 `bashi-privacy-app\run_portable.bat`，效果完全一样。

---

## 🌐 网络行为说明

合成与转写使用本地模型，不向云端语音服务上传文本或音频。默认仅本机访问；局域网模式下，数据会经明文 HTTP 在设备之间传输。

- 首次准备或依赖检查失败时，启动器可能安装、修复依赖和引导 pip；合成资产未齐时会下载。中国语言或时区环境先对阿里云、清华、腾讯云、华为云、PyPI 测速，再按结果安装和回退；其他环境用 PyPI。内置 HTTPS 源校验证书；自定义 `BASHI_PIP_INDEX_URL` 不测速，HTTP 覆盖源没有 HTTPS 保护。
- 用户下载转写模型时先尝试 `hf-mirror.com`，失败后用 `huggingface.co`；同时从 GitHub 准备缺失的 Silero VAD。说话人标注界面默认隐藏，相关模型只在用户请求时从 GitHub 下载。
- 可选 NVIDIA CUDA 包由用户点击升级后从 ModelScope 下载。“查看最新版本”只在浏览器打开 `https://gitee.com/gtree965/`；没有遥测或后台更新轮询。
- 断网前须准备好合成资产、转写模型及 VAD。可选下载和修复仍需联网，不能无条件承诺每次后续启动都离线。

[隐私说明](PRIVACY.md) 列出下载来源、回退与覆盖设置的边界。[断网验证方法](docs/OFFLINE_VERIFICATION.md) 提供辅助脚本和空白记录模板，不宣称某个发行包已经通过。隔离环境使用前，先联网备齐所需资产，再按方法核查；TCP 轮询和代理观察均有盲区，也不是抓包。

---

## 💻 硬件要求

下表是**作者实测**的数据。首次运行后点右侧面板的"测速"按钮，程序会根据你这台机器实际表现重新校准 ETA 估算 — 不用照搬此表。

| 硬件 | 自动选择的后端 | "你好。" 探测（25 字） | 1,000 字合成预计 | 状态 |
|---|---|---|---|---|
| AMD RX 9060 XT (16 GB) | GGUF + Vulkan | 约 3 秒 | 几分钟 | ✓ 2026-05 实测 |
| AMD RX 590 (8 GB) | GGUF + Vulkan | 3-5 秒 | 约 5-10 分钟 | ✓ 实测 |
| Intel N305 笔记本 + UHD 集显 | GGUF + Vulkan / DirectML | 53 秒 | 25-46 分钟 | ✓ 2026-05-25 实测 |
| Intel N100 迷你主机 + UHD 集显 | GGUF + Vulkan / DirectML | 126 秒 | 58 分钟 - 1 小时 49 分 | ✓ 2026-05-25 实测 |
| NVIDIA RTX 5070（12 GB，云电脑，Blackwell） | GGUF + Vulkan/CUDA + DirectML | 约 1 秒 | 41 秒 - 1 分 17 秒 | ✓ 2026-06-12（Vulkan）& 2026-07-24（海马云 HMv Cloud PC）实测：全冷启动合成确认；可选 CUDA 附加包已实证可用（LLM 28 层跑 CUDA0、解码 DirectML fp16）。CUDA-vs-Vulkan A/B 仍欢迎反馈。 |
| 其它 NVIDIA RTX / GTX（桌面） | GGUF + Vulkan + DirectML · 可选 CUDA 附加包 | 待社区报数 | 待社区报数 | 等待桌面 tester 通过 GitHub Issues 报数 |
| Apple Silicon / Intel Arc | — | 暂未实测 | 暂未实测 | 尚未验证 |

> ⚠️ **入门级 CPU（Intel N100 / N305 一类）仅适合短句试用 — 单次生成建议不超过 200 字。** 这类机器跑 5,000 字长文需要 2-9 小时。如果想做长文音频（讲座、有声书），请用独立显卡硬件（AMD RX 500/600/9000 系、NVIDIA RTX 类）。

> ℹ️ **NVIDIA 用户（桌面 RTX / GTX）**：默认路线是 GGUF + Vulkan（NVIDIA 驱动支持 Vulkan）。想要原生 CUDA 加速，点击应用内一键升级横幅（v0.1.1+）— 会下载 ~595 MB CUDA 运行时附加包，无需手动配置权重。**需要 NVIDIA 驱动 ≥ 545.x 才能使用 CUDA 12.4 运行时。** Vulkan 路径在 RTX 5070（云电脑）实测：**25 字探测 1 秒**，桌面 NVIDIA 用户的默认 Vulkan 体验已经非常顺畅。CUDA 附加包 A/B 数字 + 其它 RTX/GTX 卡的报数欢迎通过 [GitHub Issues](https://github.com/gtree965/bashi-voice-factory-privacy/issues) 反馈。云端数据中心 NVIDIA 显卡（A10/A100/T4）在 TCC 模式下需要额外设置 — 见下方常见问题排查。

### 🧩 硬件兼容性矩阵

除了上表里具体测过的几台机器，下表说明主流 Windows 硬件在自动后端选择下走的加速路径：

| 硬件类别 | 实际加速路径 | 状态 |
|---|---|---|
| NVIDIA RTX 30 / 40 / 50（桌面） | 默认 GGUF + Vulkan · 可选 CUDA 应用内升级 | ✅ RTX 5070（Blackwell）海马云云电脑已验证——2026-06-12 Vulkan 探测约 1 秒；2026-07-24 全冷启动合成 + 可选 CUDA 附加包实证可用（LLM 28 层跑 CUDA0、解码 DirectML fp16、驱动 610.47）。CUDA-vs-Vulkan A/B 数字 + 其它卡报数仍欢迎通过 Issues 反馈。CUDA add-on 需驱动 ≥ 545.x。 |
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
| 双击 `Start_启动.bat` 报 "Array index expression is missing" | 旧版 zip。请从 GitHub Releases 或 Gitee 重新下载最新版；该 BOM 问题在 v0.1.0 正式版已修复 |
| pip 安装途中 WiFi 闪断后中止 | 启动器会重试或切换依赖源。仍失败时修复连接后重启，已安装部分可从缓存复用。 |
| pip 安装失败并提示 "long path support" | 按启动器提示，在管理员 PowerShell 中运行一次注册表命令，然后重新启动 |
| 所有镜像都装不上，或镜像拒绝本机 IP（`403` / `denied by IP ACL`） | 中国环境下先对五个内置源测速排序，失败时换源；其他环境用 PyPI。若要指定某一个源，启动前设置 `BASHI_PIP_INDEX_URL`，例如 `set BASHI_PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple/` |
| GGUF 下载中断 | 同样自动重试，且支持 HTTP Range 续传，重新运行启动器从 `.part` 文件续传 |
| 启动报 "No usable backend was found" | 查 `app.log`（带时间戳的结构化应用日志）和 `launch_log.txt`（启动器步骤与原生 stderr）。常见原因：GGUF 运行 DLL 缺失、显卡驱动过旧、可用内存 <8 GB。程序会打印中英双语提示告知具体原因 |
| STT 下载闪过 "镜像失败" | v0.1.0 正式版不会出现 — 是旧版残留的 ModelScope 路径，已删除 |
| 云端 / 数据中心 NVIDIA 显卡（A10 / A100 / T4，国内云 Windows 镜像）：`access violation reading 0x0000000000000000` 或 `GGUF probe failed` | 数据中心 NVIDIA 显卡通常运行在 **TCC 模式**（Vulkan/DirectML 被屏蔽），且驱动版本较旧（~538.x）跟 CUDA 12.4 add-on 不兼容。**桌面 RTX/GTX 显卡不受影响**（默认 WDDM 模式 + 现代驱动）。v0.1.2 会隔离并报告原生启动探测崩溃，不再让启动器直接退出，但 TCC 配置仍需手动 workaround：(1) 把 `vulkan_backend_spike\Qwen3-TTS-GGUF\qwen3_tts_gguf\inference\bin\ggml-vulkan.dll` 重命名为 `.disabled`；(2) 编辑 `bashi-privacy-app\run_portable.ps1`，在 `Remove-Item Env:USE_GGUF_BACKEND` 行（约第 270 行）之后加上 `$env:USE_GGUF_BACKEND = "1"` + `$env:GGUF_ONNX_PROVIDER = "CPU"`；(3) 命令行预装 CUDA add-on：`python download_cuda_runtime.py`。CUDA 12.4 需要 NVIDIA 驱动 ≥ 545.x。TCC 自动处理仍计划在后续补丁实现。 |

完整日志路径：`bashi-privacy-app\app.log` 和 `bashi-privacy-app\launch_log.txt`

---

## 📦 zip 包目录结构

```
bashi-voice-factory-privacy-v0.1.6/
├── Start_启动.bat                                       ← 双击这里
├── Start_CPU_only_仅CPU启动.bat                         ← 强制 CPU 模式（入门集显 A/B 对比用）
├── README.md                                            ← 英文文档
├── README_CN.md                                         ← 本文件
├── LICENSE                                              ← MIT 许可证
├── VERSION                                              ← 发布版本号
├── PRIVACY.md / SECURITY.md                            ← 网络与安全边界
├── docs/OFFLINE_VERIFICATION.md                         ← 方法与空白记录模板
├── 巴适声工厂隐私版使用手册_Bashi_Voice_Factory_Privacy_Edition_User_Guide.pdf
│                                                         ← 中英双语帮助 PDF
├── bashi-privacy-app/                                   ← 程序代码 + 嵌入式 Python
│   ├── run_portable.bat                                 ← 等效启动器（直接路径）
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

欢迎通过 [GitHub Issues](https://github.com/gtree965/bashi-voice-factory-privacy/issues) 提交 issue、反馈或功能建议。
