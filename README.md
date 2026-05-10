# bashi-privacy-app

这是“巴适声工厂隐私版”的 Flask 应用骨架。

## 当前状态

- 基于 `edge-tts-app/` 的 Flask 结构提炼而来
- TTS 已切换到本地 `Qwen3-TTS-12Hz-1.7B-CustomVoice`
- STT 仍沿用现有 sherpa-onnx 路线
- 当前阶段目标是先跑通：
  - `/api/voices`
  - `/api/synthesize`
  - `/api/synthesize-long`
  - `/api/synthesize-sentences`

## 依赖关系

本目录不复制本地 TTS 内核和模型，而是引用：

- `../LocalBashiVoiceFactory/`

默认查找方式：

- 若设置了 `LOCAL_TTS_KERNEL_DIR`，优先使用该目录
- 否则默认使用工作区里的 `LocalBashiVoiceFactory/`

## 运行前提

1. 安装依赖

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

2. 确认本地内核目录存在

```text
LocalBashiVoiceFactory/
```

3. 首次下载 GGUF 运行模型（约 2.2 GiB）

普通用户运行 `run_portable.bat` 时，启动器会检测模型是否完整；缺失时会询问是否从 ModelScope 下载。也可以手动运行：

```powershell
.\.venv\Scripts\python.exe download_gguf_model.py
```

默认主下载源：

```text
gtree592/bashi-qwen3-tts-1.7b-customvoice-gguf-runtime
```

下载完成后，语音合成在本机离线运行。ModelScope 只作为公开模型文件下载镜像。若 ModelScope 临时不可用，可设置 `BASHI_GGUF_FILESFM_URL` 使用备用 zip 下载源。

4. 启动应用

```powershell
.\.venv\Scripts\python.exe app.py
```

### 快速启动

- 推荐普通用户入口：

```powershell
.\run_portable.bat
```

- PyTorch 全量应用：

```powershell
.\run-pytorch.cmd
```

- GGUF 应用：

```powershell
.\run-gguf.cmd
```

说明：

- `run_portable.bat` 借鉴 v3.11 便携版启动器：自动进入应用目录、写入 `launch_log.txt`、自检/安装依赖、按中国时区启用阿里云 pip 镜像、询问是否开放局域网访问，并默认使用 backend selector 自动选择 GGUF/PyTorch
- `run_portable.bat` 会在启动前检查 GGUF 运行模型是否完整；缺失时询问是否从 ModelScope 下载，下载失败时会提示并继续启动应用
- `run_portable.bat` 内部调用 `run_portable.ps1` 并对当前进程使用 `-ExecutionPolicy Bypass`，避免用户机器默认禁止 `.ps1` 的问题
- 默认直接运行 `app.py` 时，backend selector 会自动 probe/cache，并在当前 Windows + RX590 统一环境中选择 GGUF
- `run-pytorch.cmd` 会调用 `run-pytorch.ps1` 并显式设置 `USE_PYTORCH_BACKEND=1`
- `run-gguf.cmd` 会调用 `run-gguf.ps1` 并显式设置 `USE_GGUF_BACKEND=1`
- `.cmd` wrapper 只对当前启动进程使用 `-ExecutionPolicy Bypass`，不会修改系统 PowerShell 策略
- 两个 launcher 都使用同一个 `.venv`，只是作为显式 user-pin 入口，不再切换到独立 GGUF venv
- GGUF 路径已经在统一 `.venv` 内跑通完整 `app.py`，不再需要 `tests/run_tts_only_server.py` 旁路

## 当前限制

- 第一阶段不做浏览器真流式音频播放
- 本地 TTS 默认一次只允许 1 个任务
- 语速 / 音调滑杆目前仍保留在 UI，但本地引擎暂未映射这些参数

## 下一步

1. 继续清理前端里的 Edge 专属文案与行为
2. 给 selector 首次 probe 增加更友好的启动提示
3. 为后续 Windows / macOS / Linux 打包整理安装脚本
