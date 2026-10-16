# Privacy Policy / 隐私说明

合成与转写使用本地模型，不向云端语音服务上传文本或音频。默认仅本机访问；用户开启局域网访问后，文本、上传媒体和返回音频会在访问设备与运行应用的电脑之间传输。局域网使用明文 HTTP，PIN 控制访问而不加密。

Synthesis and transcription use local models; text and audio are not uploaded to cloud speech services. Access defaults to this computer. In LAN mode, text, uploaded media and returned audio travel between the accessing device and the computer running the app. LAN connections use plain HTTP; the PIN controls access and does not encrypt traffic.

本页列出的预设下载入口对应默认便携 GGUF 路径和应用内下载操作。高级 PyTorch 入口须自行准备本地模型目录；其模型准备不属于默认后端的断网核验范围。/ The preset sources below describe the default portable GGUF path and in-app downloads. The advanced PyTorch entry requires separately prepared local model files and is outside the default-backend verification.

## 准备与修复 / Preparation and repair

首次启动或依赖检查失败时，启动器可能自动下载依赖；合成模型缺失或不完整时也会下载。所需资产全部准备好后，默认本机模式的合成、转写与导出可以断网使用。首次准备与用户另行触发下载不属于断网使用。

The launcher may download dependencies on first start or after a failed dependency check, and download missing or incomplete synthesis assets. With all required assets prepared, synthesis, transcription and export in default local mode can run with the network disconnected. Preparation and user-requested downloads require a connection.

| 资产 / Asset | 入口与来源 / Trigger and source |
|---|---|
| pip 引导 / bootstrap | 缺少 pip 时 / when pip is missing: `https://bootstrap.pypa.io/get-pip.py` |
| Python 依赖，约 700 MB / dependencies, about 700 MB | 安装或修复。中国语言或时区环境会对阿里云、清华、腾讯云、华为云、PyPI 各试下载最多 1 MiB，再按结果安装和回退；其他环境用 PyPI。/ Installation or repair: Chinese language/time-zone environments test up to 1 MiB per source, rank them and fall back on failure; elsewhere, PyPI. |
| 合成模型，约 2.2 GB / synthesis model, about 2.2 GB | 资产未齐时 / when incomplete: `https://modelscope.cn/models/gtree592/bashi-qwen3-tts-1.7b-customvoice-gguf-runtime` |

内置依赖入口 / Built-in package indexes:

- `https://mirrors.aliyun.com/pypi/simple/`
- `https://pypi.tuna.tsinghua.edu.cn/simple/`
- `https://mirrors.cloud.tencent.com/pypi/simple/`
- `https://repo.huaweicloud.com/repository/pypi/simple/`
- `https://pypi.org/simple/`（包文件来自 / package files from `files.pythonhosted.org`）

内置 HTTPS 源保留证书校验。设置 `BASHI_PIP_INDEX_URL` 时只使用指定源、不测速；显式指定 HTTP 源没有 HTTPS 保护。合成下载器也允许用参数/环境变量指定仓库和备用 ZIP 地址；这些设置会改变下载目标，备用 ZIP 校验使用用户提供的哈希及包内清单。服务商可能将请求重定向到其文件分发域名。

Built-in HTTPS sources retain certificate checks. `BASHI_PIP_INDEX_URL` selects a single index and skips testing; an explicit HTTP index has no HTTPS protection. The synthesis downloader also accepts a configured repository and fallback ZIP URL, changing the destination; the fallback uses a supplied archive hash, when provided, and the included file manifest. Providers may redirect downloads to their file-delivery domains.

## 用户触发的下载 / User-requested downloads

| 操作 / Action | 来源 / Source |
|---|---|
| 转写模型 / transcription models | 在模型管理器点击下载：优先 `hf-mirror.com`，失败后 `huggingface.co`，仓库为 `csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17` 或 `csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8`。/ Click download in Model Manager; mirror first, upstream fallback. |
| Silero VAD，默认转写的前提 / VAD, a transcription prerequisite | 随转写模型下载、缺失时获取：`https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx`。/ Fetched when missing during a transcription-model download. |
| 说话人标注模型 / speaker-label models | 界面默认隐藏，仅 `BASHI_SPEAKER_ID_UI=1` 显示；点击下载时访问 `github.com/k2-fsa/sherpa-onnx/releases` 的 `speaker-segmentation-models`、`speaker-recongition-models` 附件。/ Hidden by default; downloads are requested through the optional interface. |
| CUDA 附加包，约 595 MB / CUDA add-on, about 595 MB | NVIDIA 用户点击升级：`https://modelscope.cn/models/gtree592/bashi-qwen3-tts-cuda-runtime`；下载器参数可指定其他仓库。/ Requested upgrade; downloader options may select another repository. |
| 查看最新版本 / Check for updates | 在浏览器新标签页打开 `https://gitee.com/gtree965/`；应用不后台检查。/ Opens a browser tab; no background update check. |

这些模型和可选包不随主 ZIP 全部提供。断网转写前须另行准备转写模型及 VAD；下载说明不是已执行的断网验收结果。/ These assets are not all bundled in the main ZIP. Prepare the transcription model and VAD before disconnecting; a method is not a completed verification result.

## 本机数据与局域网 / Local data and LAN access

- 默认模式：浏览器访问 `127.0.0.1`；本机服务处理文本、媒体、合成、转写和导出。/ Default mode uses the loopback service for processing and export.
- 局域网模式：数据在设备之间传输；仅在可信网络使用，不要暴露到公网或放在本机反向代理之后。/ LAN mode transfers data between devices; use a trusted network and follow [SECURITY.md](SECURITY.md).
- 音频和上传媒体分别保存在 `static/audio/`、`static/uploads/`；模型在本机目录。/ Audio, uploads and models are stored locally.
- 日志为 `app.log` 和 `launch_log.txt`，可能含本机路径或任务内容，分享前须去除私人信息。/ Logs may contain paths or task content; redact before sharing.
- 浏览器 `localStorage` 保存后端测速结果以估算等待时间。/ Backend timing is stored in browser local storage.

## 不包含的收集机制 / Collection mechanisms not included

没有在线账号、遥测、崩溃上报、云端日志上传或后台更新轮询。局域网 PIN 和会话只用于本次本机服务的访问控制，不是云端账号。/ There is no online account system, telemetry, crash reporting, cloud log upload or background update polling. The LAN PIN and session control this local service.

## 如何核查 / Verification

见[断网验证方法与空白记录模板](docs/OFFLINE_VERIFICATION.md)。它区分断网完成任务与联网状态下的连接观察；代理和 TCP 轮询都有覆盖边界。/ See the [method and blank record template](docs/OFFLINE_VERIFICATION.md), which separates offline task completion from observation of connection attempts.

## 第三方来源 / Third-party sources

依赖和模型遵循各自的许可与署名要求。The runtime pack is a Bashi Voice Factory runtime-only redistribution of files derived from `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` using the `HaujetZhao/Qwen3-TTS-GGUF` export pipeline. It is not an official Qwen release and not an official HaujetZhao release.
