# 巴适声工厂隐私版

下载模型后离线运行的本地语音工具。文本转语音、音频生成、转写处理和运行缓存都保存在用户自己的电脑上。

## 主要功能

- 本地 TTS：基于 `Qwen3-TTS-12Hz-1.7B-CustomVoice`
- 9 个预设音色，内置试听样例
- 自动选择可用后端，支持 GGUF/Vulkan 路线
- 浏览器界面，本机 Flask 服务
- 首次测速后显示更贴近当前机器的等待时间估算
- 用户主动点击才打开“查看最新版本”链接，不自动联网检查更新

## Windows 便携版启动

正式发布包内置 `python-3.12.10-embed-amd64`，不使用系统 Python，也不读取用户已有 Python 环境。

1. 解压 `bashi-voice-factory-privacy-v0.1.0-windows.zip`
2. 双击 `bashi-privacy-app/run_portable.bat`
3. 首次启动按提示下载依赖和 GGUF 模型
4. 浏览器打开 `http://127.0.0.1:5050`

首次启动需要联网：

- 初始化 pip：从 `https://bootstrap.pypa.io/get-pip.py`
- 安装 Python 依赖：约 700 MB，默认中国环境使用阿里云 PyPI 镜像
- 下载 GGUF 运行模型：约 2.2 GB，从 ModelScope

首次启动通常约 15-25 分钟，取决于网络速度。完成后，断网也可以继续做语音合成。

## 下载源

默认 GGUF 模型源：

```text
gtree592/bashi-qwen3-tts-1.7b-customvoice-gguf-runtime
```

如果 ModelScope 临时不可用，可设置备用 zip：

```powershell
$env:BASHI_GGUF_FILESFM_URL = "https://.../gguf-runtime.zip"
$env:BASHI_GGUF_FILESFM_SHA256 = "<sha256-if-known>"
.\python-3.12.10-embed-amd64\python.exe download_gguf_model.py
```

## 发布包内容

主包包含：

- `bashi-privacy-app/`：Flask 应用、UI、启动器、内置 Python
- `LocalBashiVoiceFactory/`：本地 TTS kernel
- `vulkan_backend_spike/Qwen3-TTS-GGUF/`：GGUF runtime 代码和空 `model-custom/`

主包不包含：

- GGUF 模型权重文件
- 测试脚本和开发 probe 输出
- `.git/`
- ODT 外部参考资料

## 开发者说明

以下命令面向 GitHub 仓库/开发工作区，不是给最终用户发布包使用。本仓库根目录是 `bashi-privacy-app/`，它引用同级目录：

```text
../LocalBashiVoiceFactory/
../vulkan_backend_spike/Qwen3-TTS-GGUF/
```

修改 `requirements.txt` 或 `../LocalBashiVoiceFactory/requirements.txt` 后，必须重跑 Python 3.12 embed 预检：

```powershell
.\scripts\precheck_py312_embed.ps1 -Index aliyun
```

完整 GGUF 合成 smoke：

```powershell
.\scripts\precheck_py312_embed.ps1 -Index aliyun -KeepExisting -RunSynthesisSmoke
```

构建 Windows 主包：

```powershell
.\scripts\build_portable_zip.ps1
```

构建脚本会校验官方 `python-3.12.10-embed-amd64.zip`：

```text
SHA256: 4ACBED6DD1C744B0376E3B1CF57CE906F9DC9E95E68824584C8099A63025A3C3
```

## 第三方来源

本项目使用的模型和 GGUF runtime 源自公开项目与公开模型：

- `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`
- `HaujetZhao/Qwen3-TTS-GGUF`

巴适声工厂隐私版发布的是 runtime-only 组合包，不是 Qwen 官方发布，也不是 HaujetZhao 官方发布。
