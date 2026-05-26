# Bashi Voice Factory Privacy Edition — Roadmap

> Living document. Pinned at repository root for community review.
> Detailed in-flight task tracking lives in local planning notes and PR descriptions; this file is the strategic version-by-version view.

## Version overview

| Version | Theme | Status | Target |
|---|---|---|---|
| **v0.1.0** | Windows initial release | Released 2026-05 | shipped |
| **v0.1.1** | NVIDIA CUDA dual-backend (Windows) | Planned | ~1-2 weeks after v0.1.0 |
| **v0.2.0** | Cross-platform: macOS Apple Silicon + Linux Ubuntu/Debian | Planned | 3-4 weeks after v0.1.0 |
| **v0.3.0** | Native ARM64 Windows + formal hardware testing | Planned / research | longer term |
| **v0.4.0+** | NPU acceleration research, optional STT engines, manual update UX | Idea pool | — |

Semver convention: pre-1.0, MINOR = new feature surface (new OS, new backend class), PATCH = additive within the same surface (e.g., adding CUDA backend within Windows = patch).

### Review history

- **2026-05-26**: v0.1.1 / v0.2 / v0.3 refined after technical review:
  - ✅ Confirmed: `llama.cpp` auto-selects CUDA over Vulkan via lexicographic DLL load order in `ggml_backend_load_all()` — `ggml-cuda.dll` < `ggml-vulkan.dll` alphabetically → CUDA registered at lower index → scheduler prefers it. No env var or wrapper override needed.
  - ✅ Confirmed: `llama.cpp` does **not** use cuDNN. Minimum CUDA DLL set is `ggml-cuda.dll` + `cudart64_12.dll` + `cublas64_12.dll` + `cublasLt64_12.dll`; cuDNN entirely omitted.
  - ⚠️ Measured (2026-05-26): official `b7798` CUDA DLLs are much larger than the early estimate. The four required CUDA DLLs add ~567.5 MiB compressed inside the final zip; a single universal CUDA+Vulkan probe package measured 704,261,799 bytes / 671.64 MiB. Distribution shape must be decided before shipping v0.1.1.
  - ⚠️ Caught: v0.1.1 cannot be "pure distribution-side" — current UI / `/api/system-info` / `backend_probe.py` label every GGUF path as "Vulkan + DirectML" even on NVIDIA, and would not surface that CUDA is actually active. Minimal Python-layer changes required (backend reporting only).
  - ⚠️ Caught: bin folder currently contains `llama.dll` + `ggml.dll` + `ggml-base.dll` + `ggml-vulkan.dll` + many CPU variants. Bundling CUDA needs explicit verification of whether `ggml-cuda.dll` plugs into the existing `llama.dll` / `ggml.dll` (plugin model), or whether the CUDA llama.cpp build's versions of those files must coexist / replace.
  - ✅ Confirmed: upstream `llama.cpp` macOS-arm64 releases ship pre-built `libllama.dylib` + `libggml-metal.dylib` with Metal compiled in by default. v0.2 Phase 0a outcome 1 locked → no local-compile or PyTorch+MPS pivot needed.
  - ⚠️ Caught: `backend_probe.py` selection ladder is per-vendor not per-OS. Linux NVIDIA+CUDA and Linux AMD+ROCm both probe PyTorch first; default fallback is PyTorch only. v0.2 needs explicit rewrite to make Linux all-vendor prefer GGUF when bundled.
  - ❌ Hard blocker: NPU EPs (Qualcomm QNN, DirectML NPU) require static shapes. Current `StatefulDecoder` has dynamic `audio_codes` sequence length, dynamic KV cache concat, dynamic slice/concat on conv history. Direct NPU compile is impossible — would require full model refactor to static padded shapes + masking. v0.3-α scope/risk recalibrated.
  - 📊 Calibrated timelines: v0.1.1 1-2 weeks → ~1 week. v0.2 4-6 weeks → 3-4 weeks. v0.3-α 4-6 weeks → 6+ weeks (or much more if decoder refactor needed).
  - 🔀 Priority swap: v0.3.0 should ship ARM64 Windows native (β) BEFORE NPU (α). ARM64 is standard engineering; NPU is gated by intensive ML refactor.

---

## v0.1.0 — Windows initial release (shipped)

**Scope**

- Windows 10/11 x64
- Local TTS: Qwen3-TTS-12Hz-1.7B-CustomVoice via GGUF runtime + `ggml-vulkan.dll` (universal: AMD / Intel / NVIDIA via Vulkan driver)
- Local STT: SenseVoice Small (default) + optional Parakeet TDT, via sherpa-onnx
- DirectML execution provider for ONNX decoder
- Embedded Python 3.12.10 (no system Python dependency)
- Thin-zip distribution (~108 MB) + JIT model downloads from ModelScope (GGUF 2.2 GB) and hf-mirror.com (STT 242 MB)
- Bilingual top-level READMEs + bilingual launcher (`Start_启动.bat`)
- Network resilience: HTTP Range/resume, 3-attempt retry with exponential backoff, China-friendly mirrors
- Documented privacy posture: no telemetry, no auto-update probes, air-gap-portable after first launch

**Known limitations carried into v0.1.x patches**

- NVIDIA discrete GPU users run via Vulkan, not CUDA (~1.5-3× slower than upstream-supported CUDA path)
- Entry-level iGPU (Intel N100/N305) cannot do long-form audio in reasonable time
- NPU silicon (Snapdragon X / Lunar Lake / Ryzen AI 300) unused
- ARM64 Windows unsupported (x64 emulation only)

---

## v0.1.1 — NVIDIA CUDA dual-backend (Windows patch)

**Goal**: NVIDIA discrete GPU users on Windows get native CUDA acceleration with minimal setup. Original "same single zip" goal is under review after the 2026-05-26 size probe showed a universal CUDA+Vulkan zip would be ~672 MiB.

**Why now**: Upstream HaujetZhao/Qwen3-TTS-GGUF uses llama.cpp, which ships CUDA-flavored binaries for every release. v0.1 chose Vulkan-only as a universal solution; v0.1.1 closes the obvious gap for NVIDIA users. Distribution may become either a separate NVIDIA zip or an optional CUDA add-on pack if the single-zip size is unacceptable.

### Approach

Bundle the **CUDA llama.cpp build matching the same `b<NNNN>` version** alongside the existing Vulkan build. `llama.cpp`'s `ggml_backend_load_all()` scans the bin folder lexicographically — `ggml-cuda.dll` loads before `ggml-vulkan.dll`, registers at lower index, and the backend scheduler prefers it automatically. On NVIDIA + CUDA driver ≥ 550.x → CUDA wins. On AMD/Intel/no-CUDA-driver → `LoadLibrary`/`cudaInit` fails gracefully, CUDA backend is excluded from scheduler, falls back to Vulkan transparently. **Minimal Python-layer changes required** for backend reporting — the review surfaced that the current UI / `/api/system-info` would still report "Vulkan + DirectML" on NVIDIA even when CUDA is actually active. Without backend-reporting fix, the feature is unverifiable end-to-end.

### Concrete steps

1. **Identify matching upstream release**. Current bundled: `llama-b7798-bin-win-vulkan-x64.zip`. Match: `llama-b7798-bin-win-cuda-12.4-x64.zip`. Same `b<NNNN>` is critical — ggml ABI changes between builds.
2. **Verify the bundling model** (Finding 2 — small but load-bearing): determine whether `ggml-cuda.dll` plugs into the existing `llama.dll` + `ggml.dll` + `ggml-base.dll` (plugin model, drop-in alongside Vulkan), OR whether the CUDA build's versions of those core files must coexist / replace. Current bin folder contains: `llama.dll`, `ggml.dll`, `ggml-base.dll`, `ggml-vulkan.dll`, plus many `ggml-cpu-*.dll` variants. If the CUDA build of `llama.dll` is binary-incompatible with the Vulkan build of `llama.dll`, we have an actual problem. Decide before committing to "single zip dual backend".
3. **Final DLL inventory** (cuDNN deliberately omitted — llama.cpp uses cuBLAS, not cuDNN):
   - `ggml-cuda.dll` (the backend)
   - `cudart64_12.dll` (CUDA runtime)
   - `cublas64_12.dll` (cuBLAS)
   - `cublasLt64_12.dll` (cuBLAS Linear Algebra)
   - Total: ~150-200 MB compressed (was 200-400 MB estimate; cuDNN omission saved 100-500 MB)
4. **Bundle**: drop the above into `vulkan_backend_spike/Qwen3-TTS-GGUF/qwen3_tts_gguf/inference/bin/` alongside Vulkan DLLs. If Step 2 says core llama.dll must change, document that decision (probably ship the CUDA-built `llama.dll` since it should still expose Vulkan via the runtime registry; verify in testing).
5. **Backend-reporting fix** (NEW step from Finding 1, ~half-day work):
   - Extend `backend_probe.py` GGUF probe to detect which ggml accelerator backend actually got chosen (CUDA vs Vulkan vs CPU). `llama.cpp` exposes this via `llama_print_system_info()` or per-device query; pick whichever the Python wrapper makes easiest.
   - Surface the chosen accelerator in `tts_routes.py` `/api/system-info` response (new field `gguf_accelerator` alongside existing `backend`).
   - Update the UI backend chip in `static/js/app.js` to render `GGUF + CUDA` when applicable, in addition to existing `GGUF + Vulkan + DirectML`.
   - User can now verify CUDA is active by glancing at the chip — load-bearing for the v0.1.1 acceptance gate.
6. **Verify auto-selection** (now actually verifiable thanks to Step 5):
   - NVIDIA + current CUDA driver: chip says `GGUF + CUDA`, token/sec ≥ 1.5× the Vulkan-only number on the same card
   - AMD / Intel / NVIDIA with outdated driver: chip says `GGUF + Vulkan`, no regression
   - All: app boots, no startup crash, decoder output identical
7. **Measure size impact / choose distribution shape**. The size probe already measured the single universal CUDA+Vulkan zip at 704,261,799 bytes / 671.64 MiB. Removing unused llama CLI tools and the archived Vulkan source zip saves only ~66.8 MiB compressed, so the single-zip package still lands around ~605 MiB. Decide before release:
   - Option A: accept the larger universal zip and document the size bump.
   - Option B: ship separate `windows-vulkan` and `windows-nvidia-cuda` zips.
   - Option C: keep the main zip Vulkan-only and add a user-triggered CUDA add-on downloader.
8. **README update**:
   - Hardware Coverage Matrix: NVIDIA rows change from ⚠️ to ✓ Tested (after NVIDIA verification)
   - Network Behavior: no change (no new download)
   - Version badge bump
9. **Other small items consolidated into v0.1.1** (only if they don't slip the timeline):
   - `Start_CPU_only_仅CPU启动.bat` top-level convenience launcher (5-min add) so N100/N305 users can A/B-test CPU vs iGPU without env var fiddling
   - Whatever bug reports surface from v0.1 public release

### Acceptance criteria

- New zip extracts + boots on NVIDIA + AMD machines without regression
- On NVIDIA discrete GPU: UI chip displays `GGUF + CUDA`; measured token/sec ≥ 1.5× the same card's previous Vulkan number
- On AMD RX 590 / RX 9060 XT / Intel N100 / N305: UI chip displays `GGUF + Vulkan` (or `+ DirectML`); no regression vs v0.1
- Distribution shape decided explicitly (universal large zip vs separate NVIDIA zip vs optional CUDA add-on), with measured size documented in release notes
- README hardware table reflects measured CUDA numbers

### Risks (updated after review)

- **No NVIDIA test hardware available** (Alex's discrete GPU is AMD). Mitigations: community tester recruited via the WeChat group or GitHub issues; or a temporary NVIDIA box is sourced; or release as "v0.1.1-rc1" tagged for community NVIDIA verification before final.
- **DLL coexistence may not be plug-and-play** (Finding 2 — until Step 2 confirms otherwise): if the CUDA build's `llama.dll` / `ggml.dll` aren't binary-compatible with the Vulkan ones, "single zip dual backend" may need a tiny dispatcher (e.g., launcher copies the right `llama.dll` into bin before app start based on detected NVIDIA presence). Falls back to v0.2 "separate NVIDIA zip" approach if dispatcher gets complicated.
- **NVIDIA driver compatibility**: CUDA 12.4 needs driver ≥ 550.x. Older NVIDIA drivers won't get CUDA — Vulkan fallback handles it transparently (verified).
- ~~**Backend auto-selection priority**~~ — **resolved** by source review: `llama.cpp` registers backends in lexicographic DLL discovery order; CUDA naturally takes precedence over Vulkan on NVIDIA hardware without any wrapper override.
- **CUDA package size is larger than expected** (size probe, 2026-05-26): required CUDA DLLs alone contribute ~567.5 MiB compressed to the final package. This likely invalidates the original "single zip under 500 MB" target unless Alex explicitly accepts a larger download.
- ~~**cuDNN size**~~ — **resolved**: cuDNN not used by llama.cpp, omitted entirely; however cuBLASLt + ggml-cuda are still large.

### Effort estimate

**~1 week calendar** (recalibrated, down from 1-2). ~3-4 working days: Step 2 verification (½ day), Step 5 backend reporting (½ day), bundle + test on NVIDIA box (1-2 days), README + release notes (½ day). Gated mostly on NVIDIA test machine access.

---

## v0.2.0 — Cross-platform: macOS Apple Silicon + Linux Ubuntu/Debian

**Goal**: Match Speed Edition's three-OS coverage (Windows + macOS + Linux) with unified backend story: GGUF runtime + platform-native accelerator.

### Locked decisions (from 2026-05-25 planning)

- macOS: Apple Silicon only (M1/M2/M3/M4). No Intel Mac.
- Linux: Ubuntu/Debian family only. RHEL/Fedora/Arch users adapt manually.
- Backend: GGUF + Metal (macOS), GGUF + Vulkan (Linux). No Mac-specific PyTorch fork.
- Distribution: `.tar.gz` per OS (Speed Edition pattern; preserves `+x` bits).
- Python: system Python 3 + `.venv` on Mac/Linux (no embed). Windows keeps embed.

### Critical-path research — RESOLVED 2026-05-26

**Question**: Does upstream `llama.cpp` provide a pre-built Mac Metal binary for the ggml runtime?

**Answer**: ✅ **Outcome 1 confirmed.** Official `llama.cpp` releases for `macos-arm64` ship as `.tar.gz` archives containing precompiled `libllama.dylib`, `libggml.dylib`, and `libggml-metal.dylib` with Metal compiled in by default. No external SDKs needed at runtime. No local Xcode CLT / CMake build needed. No PyTorch + MPS pivot (saves 3 GB weight downloader work). Direct parity with the Windows Vulkan/CUDA distribution model.

### Phased delivery within v0.2

#### v0.2.0-α — macOS Apple Silicon

- GGUF + Metal runtime bundled (per Phase 0a outcome)
- `Bashi-Voice-Factory-Privacy-Mac.command` + adapted `run_venv.sh`
- `requirements_macos.txt`: swap `onnxruntime-directml` → `onnxruntime`
- `backend_probe.py` macOS Apple Silicon branch updated for Metal
- `scripts/build_portable_macos.sh` produces `.tar.gz`
- Verified on real M-series Mac (Alex hardware TBD)
- macOS Gatekeeper friction documented (Speed Edition pattern: "System Settings → Privacy & Security → Open Anyway"; unsigned release; Apple Developer ID $99/year noted as v0.3+ option if user demand high)

#### v0.2.0-β — Linux Ubuntu/Debian

- GGUF + Vulkan runtime for Linux x86_64 (`libggml-vulkan.so`)
- Shared `run_venv.sh` with Mac (Speed Edition already handles both)
- `requirements_linux.txt`: `onnxruntime` (no `-directml`); document `apt install python3-venv portaudio19-dev`
- `Start_启动.sh` top-level launcher
- `scripts/build_portable_linux.sh` produces `.tar.gz`
- Verified on Ubuntu 22.04 + 24.04
- **NEW task per Finding 3 — rewrite `backend_probe.py` selection ladder by OS+vendor**: current ladder probes PyTorch first for NVIDIA+CUDA and AMD+ROCm on Linux, default fallback is PyTorch-only. With GGUF runtime now bundled cross-platform, Linux AMD/Intel/NVIDIA should all prefer GGUF (Vulkan or CUDA via dual-backend) when present. macOS Apple Silicon should prefer GGUF + Metal. Specific changes:
  - `get_probe_order()` returns `["gguf", "pytorch"]` for Linux NVIDIA (was `["pytorch", "gguf"]`)
  - Same for Linux AMD ROCm (was `["pytorch", "gguf"]`)
  - macOS Apple Silicon returns `["gguf"]` only (PyTorch path has no shipped weights — same short-circuit as Windows)
  - Default fallback becomes `["gguf", "pytorch"]` instead of `["pytorch"]`
  - Backend reporting (from v0.1.1 Step 5) extended so each OS shows the actual accelerator: `GGUF + Metal`, `GGUF + Vulkan`, `GGUF + CUDA`, `GGUF + CPU`

#### v0.2.0 release combines α + β + Windows v0.1.1 baseline

Three artifacts ship together:
- `bashi-voice-factory-privacy-v0.2.0-windows.zip` (includes CUDA from v0.1.1)
- `bashi-voice-factory-privacy-v0.2.0-macos-aarch64.tar.gz`
- `bashi-voice-factory-privacy-v0.2.0-linux-x86_64.tar.gz`

### Linux CUDA stretch goal (v0.2.0 or v0.2.1)

NVIDIA Linux users would benefit from llama.cpp CUDA Linux build (`libggml-cuda.so`). Same dual-backend approach as Windows v0.1.1 — bundle alongside Vulkan in the same Linux tarball. If size comfortable, include in v0.2.0; otherwise punt to v0.2.1.

### Other v0.2 items (decided earlier)

- B3 first-run onboarding banner (UI)
- STT player after upload (UI — audio/video controls below upload zone)
- Optional Qwen3-ASR-0.6B as second STT engine (download size +~600 MB, autoregressive so slower on CPU than SenseVoice — gated by user demand)

### Effort estimate

**3-4 weeks calendar** (recalibrated, down from 4-6; Phase 0a outcome 1 removed the macOS unknown). Gated mostly on Mac test hardware availability.

---

## v0.3.0 — Native ARM64 Windows + hardware coverage expansion

**Goal**: bring the app to the newer hardware classes that are starting to ship in volume (2025+) but are currently underserved.

**Priority order updated 2026-05-26**: the review identified NPU as a hard-blocker scope (model refactor required). ARM64 is standard engineering. Therefore **v0.3.0-β (ARM64) ships before v0.3.0-α (NPU)**, possibly in different minors (v0.3 = ARM64, v0.4 = NPU).

### v0.3.0-β — Native ARM64 Windows build (PRIORITY)

Target hardware: Snapdragon X Copilot+ PCs running Windows on ARM. Currently x64 emulation on these devices works but is slow (~30-50% native speed) and burns extra battery.

Work involved:
- Python embed: `python-3.12.x-embed-arm64.zip` (python.org publishes ARM64 embed)
- All Python deps: pip wheels for ARM64 Windows. Current state: most major packages (Flask, transformers, sherpa-onnx) ship ARM64 wheels; `torch` ARM64 Windows wheels were added in late 2024
- llama.cpp ARM64 Windows build (upstream ships these for some releases)
- ONNX runtime ARM64 Windows
- Separate variant zip: `bashi-voice-factory-privacy-v0.3.0-windows-arm64.zip`
- Verify on a real Snapdragon X box (Alex hardware TBD)
- Effort estimate: ~3-4 weeks (similar to one v0.2 phase)

### v0.4.0-α — NPU acceleration (REFRAMED — stretch / research, was v0.3.0-α)

Target silicon:
- **Qualcomm Snapdragon X Elite** (Surface Pro 11, Galaxy Book4 Edge, Lenovo Yoga Slim 7x, etc.) — Hexagon NPU, ~45 TOPS
- **Intel Lunar Lake AI Boost** (Surface Laptop 7 Intel, ASUS Zenbook S 14 OLED, etc.) — 48 TOPS
- **AMD Ryzen AI 300 series** (XDNA 2) — 50 TOPS

Acceleration paths originally considered:
- **DirectML NPU EP** (onnxruntime ≥ 1.20): NPU as ONNX execution provider, in principle
- **QNN HTP EP** (Qualcomm-specific): faster than generic DirectML on Snapdragon
- **OpenVINO NPU EP** (Intel-specific): faster than generic DirectML on Lunar Lake

**Hard blocker identified in review (2026-05-26)**: NPU compilers (QNN, DirectML NPU) require **static input and intermediate tensor shapes**. The Qwen3-TTS `StatefulDecoder` (`qwen3_tts_decoder.fp16.onnx`) has three sources of dynamic shapes that defeat static compilation:

1. **Dynamic sequence length on `audio_codes`**: streaming chunks are `[1, N, 16]` with `N ≤ 12`; final chunk almost always smaller than max → variable `N` per call
2. **Dynamic KV cache growth**: `past_key` / `past_value` third dimension expands every iteration as tokens generate; impossible to pre-compile
3. **Dynamic slice / concat on conv history**: `pre_conv_history` and `latent_buffer` updates use dynamic-dim operators that fail or fall back to CPU under NPU EPs

**Implication**: running the current decoder ONNX directly on QNN / DirectML NPU EPs is **technically impossible** without a non-trivial model refactor — padding KV cache and sequence dimensions to fixed sizes (e.g., 72 or 128), using active masking to ignore padded regions. This is a real ML engineering effort, not a packaging task.

Possible paths forward (each its own ~4-8 week effort beyond standard packaging):
- (a) Refactor `StatefulDecoder` ONNX to static padded shapes + masking; verify accuracy regression acceptable
- (b) Try the **LLM path on NPU instead** if a future llama.cpp release adds an NPU backend (currently doesn't exist)
- (c) Use NPU for a side workload only (e.g., VAD model is much simpler — might compile cleanly)

Given the scope, v0.4 is a more honest target than v0.3.

### Additional v0.3 items (smaller scope, easy bundling)

- **Intel Arc A-series formal testing** — claim status moves from "should work" to "tested" or "not supported"
- **AMD APU iGPU formal testing** — same
- **AMD ROCm Linux variant** for AMD discrete GPU Linux users (parallel to NVIDIA CUDA Linux)
- macOS Apple Developer ID + notarization (if user demand for friction-free install reached threshold)

---

## Beyond v0.3 (idea pool, not committed)

- **Manual update check UX improvements** (NOT auto-updater): things like a one-click "copy changelog URL" button, version-string comparison helper when user manually pastes the latest version number, picking which of GitHub Releases / files.fm to open. Strictly user-initiated; no background polling of any kind. (Earlier draft mentioned an "in-app notification badge" — dropped per Finding 4, since badges imply background checking which conflicts with the v0.1 privacy posture.)
- **Optional Qwen3-ASR** as third STT engine (if v0.2's evaluation shows it's worth the size + speed cost)
- **Web app version** (no installer, runs in browser via WebGPU + WASM ggml — speculative, depends on llama.cpp WASM maturity)
- **Linux NVIDIA-CUDA-only variant** specifically optimized for headless server deployments (no UI deps, REST API only)
- **CHANGELOG.md** added as separate doc once v0.1.1 ships (version history will outgrow this roadmap doc's brief notes)

---

## Out of scope (intentionally not planned)

| Item | Why not |
|---|---|
| Intel Mac support | Apple Silicon transition is effectively complete in target market; CPU-only on Intel Mac wouldn't be usable |
| iOS / Android | Mobile inference of 1.7B model is impractical on consumer phones; better served by Speed Edition (cloud) |
| Other Linux distros (RHEL, Fedora, Arch, openSUSE) | Speed Edition same scope; community can adapt the Ubuntu launcher |
| Multi-GPU inference | Single 1.7B model fits one GPU; no realistic benefit |
| Larger model variants (Qwen3-TTS 7B) | Hardware bar shoots up; defeats accessible local-edition positioning |
| Telemetry / analytics of any kind | Violates v0.1 privacy commitment; non-negotiable |
| Cloud fallback when local fails | Same — privacy-first means local-only by design |

---

## How to suggest a roadmap change

Open an issue on <https://github.com/gtree965/bashi-voice-factory-privacy/issues> tagged `roadmap`. Concrete proposals (with rationale + estimated effort) more useful than abstract wishes. For private channels: ncorecpu@gmail.com.

---

*Last updated: 2026-05-26 (incorporated technical review — see "Review history" near the top). Next review: after v0.1.1 ships.*
