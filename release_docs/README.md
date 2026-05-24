**English** | [中文文档](README_CN.md)

# Bashi Voice Factory Privacy Edition (巴适声工厂 · 隐私版)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](bashi-privacy-app/LICENSE)
[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](bashi-privacy-app/VERSION)
![Python](https://img.shields.io/badge/python-3.12_embed-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)

**Version:** 0.1.0

A fully offline desktop web app for high-quality text-to-speech and speech-to-text. After the one-time first-launch download, **everything runs on your own machine** — TTS synthesis, audio export, transcription, and storage. No audio data ever leaves your computer.

> ⚡ Need cloud-quality voices and faster generation? Check out [Bashi Voice Factory Turbo (巴适声工厂 · 极速版)](https://github.com/gtree965/bashi-voice-factory-turbo) — Microsoft Edge TTS, 14 languages, 50,000-character long text. Requires internet.

**Author:** Alex Li (ncorecpu@gmail.com)
**License:** [MIT License](bashi-privacy-app/LICENSE)

---

## ✨ Highlight Features

### 🔒 Fully Local Text-to-Speech
- **Local Qwen3-TTS-12Hz-1.7B-CustomVoice** running entirely on your machine — no cloud calls during synthesis.
- **9 curated voice presets** with native-language sample previews built in.
- **10 languages** supported: Chinese (Mandarin, Cantonese, Sichuanese, Beijing, Northeast), English (US/UK), Japanese, Korean, German, French, Russian, Portuguese, Spanish, Italian.
- **Instruction control** for style, accent, emotion via natural-language prompts.

### 🎯 Automatic Backend Selection
- **GGUF + Vulkan** for AMD / Intel / iGPU users (default, fast, RAM-friendly).
- **PyTorch + CUDA** for NVIDIA users (advanced setup; weights download separately).
- **CPU fallback** for entry-level hardware (works on Intel N100-class boxes).
- One-click **speed test** calibrates ETA estimates to your specific machine.

### 🎙️ Local Offline Speech-to-Text (STT)
- **SenseVoice Small** (default, 242 MB) — multilingual zh/en/ja/ko/yue, non-autoregressive (fast on CPU).
- **Parakeet TDT 0.6B** (optional, 661 MB) — English specialist, NVIDIA's ~1.7% WER champion.
- **VAD-based segmentation** via Silero — accurate timestamps, no chunk-boundary stutter.
- **Live transcript streaming** via SSE; exports to TXT / SRT / VTT.

### 🛡️ Smart First-Launch Download with Resume
- **HTTP Range / resume** built in — a transient WiFi drop won't restart your 2.2 GB GGUF download from zero.
- **3-attempt retry** with exponential backoff for both pip dependencies and model files.
- **China-friendly mirrors**: Aliyun PyPI mirror auto-detected by locale; GGUF runtime hosted on ModelScope; STT models hosted on hf-mirror.cn.

### 📱 LAN Sharing for Phone / Tablet Use
- First-launch prompt: bind to `0.0.0.0` to allow access from any device on the same WiFi.
- Compatible with mobile browsers — type the LAN IP and use it like a local web app.

---

## 🚀 Quick Start

### Easiest path

1. Unzip the downloaded file to any folder (Desktop or wherever you like).
2. **Double-click `Start_启动.bat`** at the top level of the extracted folder.
3. First launch will:
   - Install Python dependencies (~700 MB, 8-15 min depending on network/CPU)
   - Prompt to download the GGUF model (~2.2 GB, 2-15 min depending on network)
   - Open `http://127.0.0.1:5050` in your default browser
4. After first launch, **all subsequent launches are offline** and start in ~5 seconds.

### Advanced

Users who prefer to bypass the top-level launcher can run `bashi-privacy-app\run_portable.bat` directly. Both paths are identical.

---

## 🌐 Network Behavior

**Privacy commitment**: this app does not phone home, does not upload audio, does not collect telemetry.

**First launch only** (one-time, ~700 MB + ~2.2 GB):

- pip dependencies from `https://mirrors.aliyun.com/pypi/simple/` (or PyPI default outside China)
- GGUF model from `https://modelscope.cn/models/gtree592/bashi-qwen3-tts-1.7b-customvoice-gguf-runtime`
- STT model (when user opts in) from `https://hf-mirror.com/csukuangfj/...` (or HuggingFace fallback)

**Runtime network activity**: zero. TTS synthesis, STT transcription, and audio export are 100% on-device.

**Optional, user-initiated only**: the UI footer "Check for updates" button opens a files.fm release page in a new tab. No automatic version polling; no background HTTP traffic.

---

## 💻 Hardware Expectations

| Hardware class | Backend | "你好。" probe latency | Long-form synthesis |
|---|---|---|---|
| NVIDIA RTX 30/40 series | PyTorch + CUDA | <2 s | 5-20x realtime |
| AMD RX 590 / 9060 XT, Intel Arc | GGUF + Vulkan | 3-5 s | 1-3x realtime |
| Intel iGPU (UHD, Iris Xe) | GGUF + Vulkan | 7-12 s | ~realtime |
| Intel N100 / N305 (CPU only) | GGUF + CPU | 15-30 s | 0.3-0.5x realtime |

A built-in speed test (click 测速 / Speed Test) calibrates the ETA panel to your specific box on first use.

---

## 🐛 Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `Start_启动.bat` shows "Array index expression is missing" | Old zip — re-download the latest from files.fm; the BOM bug was fixed in v0.1.0 final |
| pip install stops mid-way after WiFi blip | Retry triggers automatically (3 attempts, 5s/30s/120s backoff). If all 3 fail, fix network and re-run the launcher — pip caches what's already installed |
| GGUF download interrupted | Same: retries with HTTP Range/resume; re-run launcher to continue from `.part` file |
| App exits with "No usable backend was found" | Check `launch_log.txt` — usually GGUF runtime DLL missing, GPU driver outdated, or RAM <8 GB. App now prints a bilingual advisory with specific causes |
| STT download says "镜像失败" | Should not happen in v0.1.0 final — old behavior from removed ModelScope path |

Full log path: `bashi-privacy-app\launch_log.txt`

---

## 📦 What's in the Zip

```
bashi-voice-factory-privacy-v0.1.0/
├── Start_启动.bat                                       ← double-click here
├── README.md                                            ← this file
├── README_CN.md                                         ← Chinese version
├── 巴适声工厂使用手册_Bashi_Voice_Factory_User_Guide.pdf  ← help PDF (bilingual)
├── bashi-privacy-app/                                   ← app code + embedded Python
│   ├── run_portable.bat                                 ← same launcher, direct path
│   ├── README.md                                        ← developer / technical README
│   └── ...
└── vulkan_backend_spike/                                ← GGUF runtime (populated on first launch)
    └── Qwen3-TTS-GGUF/
```

---

## 📄 License

[MIT License](bashi-privacy-app/LICENSE) © 2026 Alex Li

Bundled third-party components retain their original licenses:

- **Qwen3-TTS-12Hz-1.7B-CustomVoice**: Tongyi Lab (Alibaba), Apache 2.0
- **GGUF runtime**: based on HaujetZhao/Qwen3-TTS-GGUF
- **SenseVoice Small / Silero VAD / Parakeet TDT**: see respective model cards

---

## 👤 Author

**Alex Li** — ncorecpu@gmail.com

Issues, feedback, and feature requests welcome via the GitHub release page or email.
