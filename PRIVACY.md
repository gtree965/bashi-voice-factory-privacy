# Privacy Policy / 隐私说明

巴适声工厂隐私版是一款本机运行的语音工具。它的设计目标是：用户文本、生成音频、转写文件和运行缓存都保留在用户自己的电脑上。

Bashi Voice Factory Privacy Edition is designed as a local desktop web app. User text, generated audio, transcription files, and runtime cache stay on the user's own computer.

## 唯一的网络行为 / Network Behavior

**首次启动**会从公开镜像下载所需资产（一次性）：

- pip 初始化脚本：从 `https://bootstrap.pypa.io/get-pip.py`
- pip 依赖：约 700 MB，从 `https://mirrors.aliyun.com/pypi/simple/`
- GGUF 模型：约 2.2 GB，从 `https://modelscope.cn/models/gtree592/bashi-qwen3-tts-1.7b-customvoice-gguf-runtime`

首次启动通常需要约 15-25 分钟，具体取决于网速。下载完成后，软件**完全离线运行**，所有 TTS 推理、音频生成、文件保存均在本机。

First launch usually takes about 15-25 minutes, depending on network speed. After these first-time downloads complete, the app runs offline. TTS inference, audio generation, and file saving happen locally.

**唯一的运行时网络行为**：UI “查看最新版本” 按钮，由用户主动点击时跳转到 `https://files.fm/u/juvstxmrez`。软件本身不自动联网检查更新、不上传任何使用数据。

The only runtime network action is the user-initiated "Check for updates" button, which opens `https://files.fm/u/juvstxmrez`. The app does not automatically check for updates and does not upload usage data.

## 本机数据 / Local Data

- 输入文本只发送到本机 Flask 服务。
- 生成的音频默认保存在本机 `static/audio/`。
- 上传用于转写的音频/视频只在本机处理。
- 启动日志默认写入本机 `launch_log.txt`。
- 后端测速结果保存在浏览器 `localStorage` 中，用于估算后续等待时间。

## 不收集的内容 / What Is Not Collected

本软件不包含：

- 账号系统
- 遥测
- 崩溃上报
- 云端日志上传
- 自动更新检查
- 用户文本或音频上传

## 第三方来源 / Third-Party Sources

首次安装所需依赖和模型来自公开下载源。请遵守上游模型、转换工具和 Python 包的 license / attribution 要求。

The runtime pack is a Bashi Voice Factory runtime-only redistribution of files derived from `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` using the `HaujetZhao/Qwen3-TTS-GGUF` export pipeline. It is not an official Qwen release and not an official HaujetZhao release.
