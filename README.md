**English** | [中文文档](README_CN.md)

# Bashi Voice Factory Privacy Edition (巴适声工厂 · 隐私版)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.1.3-blue.svg)](VERSION)
![Python](https://img.shields.io/badge/python-3.12_embed-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)

**Version:** 0.1.3

A fully offline desktop web app for high-quality text-to-speech and speech-to-text. After the one-time first-launch download, **everything runs on your own machine** — TTS synthesis, audio export, transcription, and storage. No audio data ever leaves your computer.

> ⚡ Need cloud-quality voices and faster generation? Check out [Bashi Voice Factory Turbo (巴适声工厂 · 极速版)](https://github.com/gtree965/bashi-voice-factory-turbo) — Microsoft Edge TTS, 14 languages, 50,000-character long text. Requires internet.

**Author:** Alex Li (ncorecpu@gmail.com)
**License:** [MIT License](LICENSE)
**Source code:** <https://github.com/gtree965/bashi-voice-factory-privacy>
**Download:** [GitHub Releases](https://github.com/gtree965/bashi-voice-factory-privacy/releases) · [files.fm mirror](https://files.fm/u/juvstxmrez)

---

## 🆕 What's New in v0.1.3

- **Safer STT defaults:** SenseVoice Small is now the default multilingual STT model, the Speaker ID UI is disabled, and Paraformer Chinese Large has been removed from the product.
- **Upload and job-state hardening:** a server-side upload ceiling (2 GB by default) rejects oversized requests, and shared `stt_jobs` state is now lock-protected across background work and API reads.
- **Reliable streaming:** affected frontend SSE readers now buffer data across network chunks, preventing split JSON lines or frames from being dropped or misparsed.

---

## ✨ Highlight Features

### 🔒 Fully Local Text-to-Speech
- **Local Qwen3-TTS-12Hz-1.7B-CustomVoice** running entirely on your machine — no cloud calls during synthesis.
- **9 curated voice presets** with native-language sample previews built in.
- **10 languages** supported: Chinese (Mandarin, Cantonese, Sichuanese, Beijing, Northeast), English (US/UK), Japanese, Korean, German, French, Russian, Portuguese, Spanish, Italian.
- **Instruction control** for style, accent, emotion via natural-language prompts.

### 🎯 Automatic Backend Selection
- **GGUF + Vulkan** for AMD / Intel / iGPU users (default, fast, RAM-friendly).
- **GGUF + CUDA** for NVIDIA users via a one-click in-app upgrade (optional ~595 MB add-on download; no manual weight setup). New in v0.1.1.
- **Reliable NVIDIA detection and startup probes**: v0.1.2 detects the physical NVIDIA GPU through virtual-display layers and isolates native probe crashes so the launcher can report an actionable error instead of disappearing.
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
   - Automatically download the GGUF model when missing (~2.2 GB, 2-15 min depending on network; Ctrl+C cancels and the next launch resumes)
   - Open `http://127.0.0.1:5050` in your default browser
4. After first launch, **all subsequent launches are offline** and start in ~5 seconds.

### Advanced

Users who prefer to bypass the top-level launcher can run `bashi-privacy-app\run_portable.bat` directly. Both paths are identical.

---

## 🌐 Network Behavior

**Privacy commitment**: this app does not phone home, does not upload audio, does not collect telemetry. **The app never automatically checks any internet resource.** Every network operation is documented below and requires explicit user action — no background polling, no analytics, no silent update probes.

**First launch only** (one-time, ~700 MB + ~2.2 GB):

- pip dependencies from `https://mirrors.aliyun.com/pypi/simple/` (or PyPI default outside China)
- GGUF model from `https://modelscope.cn/models/gtree592/bashi-qwen3-tts-1.7b-customvoice-gguf-runtime`
- STT model (when user opts in) from `https://hf-mirror.com/csukuangfj/...` (or HuggingFace fallback)

**Runtime network activity**: zero. TTS synthesis, STT transcription, and audio export are 100% on-device.

**Optional CUDA acceleration** (NVIDIA users, user-initiated only): when an NVIDIA GPU is detected, the UI shows an "Upgrade to CUDA acceleration" banner. Clicking it downloads a one-time ~595 MB CUDA runtime add-on from `https://modelscope.cn/models/gtree592/bashi-qwen3-tts-cuda-runtime`. This is entirely optional — the Vulkan path works on NVIDIA without it. Nothing downloads unless you click.

**Manual update check** (user-initiated only, never automatic): the UI footer "Check for updates" button opens a release page in a new browser tab. You can also check manually anytime at:

- GitHub Releases: <https://github.com/gtree965/bashi-voice-factory-privacy/releases>
- files.fm mirror: <https://files.fm/u/juvstxmrez>

**Air-gapped / sensitive deployment** (banks, healthcare, government, internal corporate networks): after first-launch downloads complete on a connected machine, the entire `bashi-voice-factory-privacy-v0.x.0/` extracted folder can be copied to an offline / physically-isolated machine and run with zero further network access required. The app has no telemetry endpoints to firewall, no auto-update worker, no callback URLs. To verify, monitor outbound traffic with Wireshark / Resource Monitor during a normal session — it should be silent.

---

## 💻 Hardware Expectations

The table below shows **actually measured** numbers from author hardware. The built-in speed test (click 测速 / Speed Test on the right-hand panel) calibrates the ETA panel to your specific machine on first use, so you don't have to extrapolate from this table.

| Hardware | Auto-selected backend | "你好。" probe (25 chars) | 1,000-char synthesis ETA | Status |
|---|---|---|---|---|
| AMD RX 9060 XT (16 GB) | GGUF + Vulkan | ~3 s | a few minutes | ✓ Tested 2026-05 |
| AMD RX 590 (8 GB) | GGUF + Vulkan | 3-5 s | ~5-10 min | ✓ Tested |
| Intel N305 laptop + UHD iGPU | GGUF + Vulkan / DirectML | 53 s | 25-46 min | ✓ Tested 2026-05-25 |
| Intel N100 mini-PC + UHD iGPU | GGUF + Vulkan / DirectML | 126 s | 58 min - 1h49 min | ✓ Tested 2026-05-25 |
| NVIDIA RTX 5070 (12 GB, cloud PC, Blackwell) | GGUF + Vulkan/CUDA + DirectML | ~1 s | 41 s - 1 m 17 s | ✓ Tested 2026-06-12 (Vulkan) & 2026-07-24 (海马云 HMv Cloud PC): full cold-start synthesis confirmed; optional CUDA add-on verified working (LLM 28 layers on CUDA0, decoder DirectML fp16). CUDA-vs-Vulkan A/B still welcome. |
| Other NVIDIA RTX / GTX (desktop) | GGUF + Vulkan + DirectML · optional CUDA add-on | community reports welcome | community reports welcome | awaiting desktop tester reports via GitHub Issues |
| Apple Silicon / Intel Arc | — | not yet measured | not yet measured | not validated yet |

> ⚠️ **Entry-level CPUs (Intel N100 / N305 class) are only practical for short text — under ~200 characters per generation.** A 5,000-character essay would take 2-9 hours on these boxes. For long-form audio (lectures, audiobooks), please use discrete-GPU hardware (AMD RX 500/600/9000 series, NVIDIA RTX class).

> ℹ️ **NVIDIA users (desktop RTX / GTX)**: the default path is GGUF + Vulkan (NVIDIA cards support Vulkan via the proprietary driver). For native CUDA acceleration, click the one-click in-app upgrade banner (v0.1.1+) — it downloads a ~595 MB CUDA runtime add-on, no manual weight setup required. **Requires NVIDIA driver ≥ 545.x for the CUDA 12.4 runtime.** Vulkan path measured on RTX 5070 (cloud PC): **1 s for the 25-char probe**, so the default Vulkan experience is already excellent on a desktop NVIDIA card. CUDA add-on A/B numbers + reports from other RTX/GTX cards welcome via [GitHub Issues](https://github.com/gtree965/bashi-voice-factory-privacy/issues). Cloud datacenter NVIDIA cards (A10/A100/T4) running in TCC mode have additional setup steps — see Troubleshooting below.

### 🧩 Hardware Coverage Matrix

Beyond the specific machines benchmarked above, here is how the auto-selected acceleration path maps across mainstream Windows hardware:

| Hardware class | Acceleration path used | Status |
|---|---|---|
| NVIDIA RTX 30 / 40 / 50 (desktop) | GGUF + Vulkan default · optional CUDA in-app upgrade | ✅ RTX 5070 (Blackwell) verified on 海马云 cloud PC — 2026-06-12 Vulkan probe ~1 s; 2026-07-24 full cold-start synthesis + optional CUDA add-on confirmed working (LLM 28 layers on CUDA0, decoder DirectML fp16, driver 610.47). CUDA-vs-Vulkan A/B numbers + other-card reports still welcome via Issues. CUDA add-on requires driver ≥ 545.x. |
| NVIDIA GTX 10 / 16 (desktop) | GGUF + Vulkan default · optional CUDA in-app upgrade | ✅ Same flow, same driver requirement; reports welcome via Issues. |
| NVIDIA datacenter (A10 / A100 / T4) | Manual setup required | ⚠️ TCC mode + old cloud driver = manual workaround. See Troubleshooting. |
| AMD RX 500 / 600 / 7000 / 9000 (discrete) | GGUF + Vulkan + DirectML | ✅ Tested (RX 590, RX 9060 XT) |
| Intel Arc A-series (A380 / A580 / A750 / A770) | GGUF + Vulkan + DirectML | ✅ Should work — not yet measured |
| Intel iGPU (UHD / Iris Xe / Arc iGPU) | GGUF + Vulkan + DirectML | ✅ Tested (Intel N305 UHD) |
| AMD APU iGPU (Vega 7/8, RDNA 2/3) | GGUF + Vulkan + DirectML | ✅ Should work — not yet measured |
| CPU only (no usable GPU / no driver) | GGUF + CPU (ggml-cpu auto-SIMD) | ✅ Works; auto-selected only when no GPU detected |
| NPU (Snapdragon X / Lunar Lake / Ryzen AI 300) | — | ❌ Not yet utilized |
| ARM64 Windows (Snapdragon X Copilot+ PC) | — | ❌ Not supported (runs via slow x64 emulation) |

### ⚙️ Known Limitations (roadmap)

- **NVIDIA CUDA is opt-in, not bundled.** By default NVIDIA cards use the Vulkan path; native CUDA acceleration requires the one-click in-app upgrade (~595 MB add-on, v0.1.1+). This keeps the main download small for the AMD / Intel / CPU majority. Requires NVIDIA driver ≥ 545.x.
- **Weak iGPU may be slower than pure CPU.** On Intel N100-class hardware, DirectML / Vulkan transfer + scheduling overhead can outweigh GPU benefit. A/B test by launching from a cmd window after `set GGUF_LLM_USE_GPU=0 && set GGUF_ONNX_PROVIDER=CPU` — feedback on real speed numbers welcome.
- **NPU acceleration is not yet used** (Snapdragon X Elite, Intel Lunar Lake AI Boost, AMD Ryzen AI 300). Under investigation for v0.2+.
- **ARM64 Windows is not natively supported** (Surface Pro 11, Galaxy Book4 Edge, etc.). x64 emulation works but is slow. Native ARM64 build is a v0.3+ candidate.

---

## 🐛 Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `Start_启动.bat` shows "Array index expression is missing" | Old zip — re-download the latest from GitHub Releases or the files.fm mirror; the BOM bug was fixed in v0.1.0 final |
| pip install stops mid-way after WiFi blip | Retry triggers automatically (3 attempts, 5s/30s/120s backoff). If all 3 fail, fix network and re-run the launcher — pip caches what's already installed |
| pip install fails with a "long path support" message | Run the registry one-liner from the launcher's advisory in an Administrator PowerShell, then re-launch |
| GGUF download interrupted | Same: retries with HTTP Range/resume; re-run launcher to continue from `.part` file |
| App exits with "No usable backend was found" | Check `app.log` (structured, timestamped application logs) and `launch_log.txt` (launcher steps and raw stderr) — usually GGUF runtime DLL missing, GPU driver outdated, or RAM <8 GB. App now prints a bilingual advisory with specific causes |
| STT download says "镜像失败" | Should not happen in v0.1.0 final — old behavior from removed ModelScope path |
| Cloud / datacenter NVIDIA GPU (A10 / A100 / T4 on Chinese cloud Windows images): `access violation reading 0x0000000000000000` or `GGUF probe failed` | Datacenter NVIDIA GPUs typically run in **TCC mode** (Vulkan/DirectML disabled) with older drivers (~538.x) incompatible with the CUDA 12.4 add-on. **Desktop RTX/GTX cards are NOT affected** (they run WDDM mode by default with modern drivers). In v0.1.2, native startup-probe crashes are isolated and reported instead of terminating the launcher, but TCC setup still requires the manual workaround: (1) rename `vulkan_backend_spike\Qwen3-TTS-GGUF\qwen3_tts_gguf\inference\bin\ggml-vulkan.dll` to `.disabled`; (2) edit `bashi-privacy-app\run_portable.ps1` and add `$env:USE_GGUF_BACKEND = "1"` + `$env:GGUF_ONNX_PROVIDER = "CPU"` after the `Remove-Item Env:USE_GGUF_BACKEND` lines (~line 270); (3) pre-install the CUDA add-on via CLI `python download_cuda_runtime.py`. CUDA 12.4 requires NVIDIA driver ≥ 545.x. Automatic TCC handling remains planned for a later patch. |

Full log paths: `bashi-privacy-app\app.log` and `bashi-privacy-app\launch_log.txt`

---

## 📦 What's in the Zip

```
bashi-voice-factory-privacy-v0.1.3/
├── Start_启动.bat                                       ← double-click here
├── Start_CPU_only_仅CPU启动.bat                         ← force CPU mode (entry-level iGPU A/B)
├── README.md                                            ← this file
├── README_CN.md                                         ← Chinese version
├── LICENSE                                              ← MIT license
├── VERSION                                              ← release version
├── 巴适声工厂隐私版使用手册_Bashi_Voice_Factory_Privacy_Edition_User_Guide.pdf
│                                                         ← help PDF (bilingual)
├── bashi-privacy-app/                                   ← app code + embedded Python
│   ├── run_portable.bat                                 ← same launcher, direct path
│   ├── README.md                                        ← project README copy
│   └── ...
└── vulkan_backend_spike/                                ← GGUF runtime (populated on first launch)
    └── Qwen3-TTS-GGUF/
```

---

## 📄 License

[MIT License](LICENSE) © 2026 Alex Li

Bundled third-party components retain their original licenses:

- **Qwen3-TTS-12Hz-1.7B-CustomVoice**: Tongyi Lab (Alibaba), Apache 2.0
- **GGUF runtime**: based on HaujetZhao/Qwen3-TTS-GGUF
- **SenseVoice Small / Silero VAD / Parakeet TDT**: see respective model cards

---

## 👤 Author

**Alex Li** — ncorecpu@gmail.com

Issues, feedback, and feature requests welcome via the GitHub release page or email.
