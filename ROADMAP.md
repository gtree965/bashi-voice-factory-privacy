# Bashi Voice Factory Privacy Edition — Roadmap

> Living document. Pinned at repository root for community review.
> Detailed in-flight task tracking lives in local planning notes and PR descriptions; this file is the strategic version-by-version view.

## Version overview

| Version | Theme | Status | Target |
|---|---|---|---|
| **v0.1.0** | Windows initial release | Released 2026-05 | shipped |
| **v0.1.1** | NVIDIA CUDA dual-backend (Windows) | Released 2026-06 | shipped |
| **v0.1.2** | NVIDIA detection and backend robustness (Windows) | Released 2026-06-15 | shipped |
| **v0.1.3** | STT quality/safety patch: SenseVoice default + disabled Speaker ID UI | In progress | next patch |
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
- **2026-05-26 (later same day)**: v0.1.1 distribution shape locked as **Option C (Vulkan main zip + user-triggered CUDA add-on download)** after the universal-zip size measurement made Option A unattractive and Option B's "two zips on the release page" risked non-technical Chinese users picking the wrong one. Option C reuses the existing JIT-download infrastructure (parallel to GGUF model download), preserves the zero-auto-network privacy posture, and pays the ~600 MiB compressed add-on cost only for users who actually benefit. ModelScope add-on repo: `gtree592/bashi-qwen3-tts-cuda-runtime` with `win-x64/` subdirectory.

---

## v0.1.0 — Windows initial release (shipped)

**Scope**

- Windows 10/11 x64
- Local TTS: Qwen3-TTS-12Hz-1.7B-CustomVoice via GGUF runtime + `ggml-vulkan.dll` (universal: AMD / Intel / NVIDIA via Vulkan driver)
- Local STT: SenseVoice Small (default multilingual fast lane), optional Parakeet TDT English, via sherpa-onnx
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

**Goal**: NVIDIA discrete GPU users on Windows get native CUDA acceleration as a one-click in-app upgrade, without inflating the main zip for the AMD / Intel / CPU majority.

**Why now**: Upstream HaujetZhao/Qwen3-TTS-GGUF uses llama.cpp, which ships CUDA-flavored binaries for every release. v0.1 chose Vulkan-only as a universal solution; v0.1.1 closes the obvious gap for NVIDIA users.

### Distribution shape (decided 2026-05-26, Option C)

After the size probe showed a universal CUDA+Vulkan zip lands at ~672 MiB (and ~605 MiB even after trimming unused CLI tools), three options were considered:

- A: accept the larger universal zip → ~2× the v0.1 download size penalizes the AMD/Intel/CPU majority who can't use CUDA
- B: ship separate `windows-vulkan` and `windows-nvidia-cuda` zips → non-technical Chinese users likely pick the wrong one; doubles release-page artifacts
- **C (chosen): main zip stays Vulkan-only; CUDA bundle is a user-triggered in-app download** → reuses the JIT-download infrastructure (`download_gguf_model.py` already does the same for the 2.2 GiB model on first launch), pays the cost only for users who benefit, preserves the zero-auto-network privacy posture (still user-initiated)

Approach detail: when an NVIDIA user launches v0.1.1, the backend chip reports `GGUF + Vulkan (Vulkan fallback)`; the UI surfaces an "Upgrade to NVIDIA CUDA acceleration" banner next to the chip with a one-click download (~600 MiB compressed from a separate ModelScope repo: `gtree592/bashi-qwen3-tts-cuda-runtime`, subdirectory `win-x64/`). After download + restart, `llama.cpp`'s `ggml_backend_load_all()` scans the bin folder lexicographically — `ggml-cuda.dll` loads before `ggml-vulkan.dll`, registers at lower index, scheduler prefers it. AMD/Intel/older-NVIDIA-driver users never see the banner (`/api/cuda-upgrade/status` returns `applicable: false`).

### Concrete steps

1. **Identify matching upstream release**. Current bundled: `llama-b7798-bin-win-vulkan-x64.zip`. Match: `llama-b7798-bin-win-cuda-12.4-x64.zip`. Same `b<NNNN>` is critical — ggml ABI changes between builds.
2. **Verify the bundling model** (Finding 2): confirm whether `ggml-cuda.dll` plugs into the existing `llama.dll` + `ggml.dll` + `ggml-base.dll` shipped with the Vulkan build (plugin model, drop-in alongside Vulkan after CUDA add-on download), OR whether the CUDA build's versions of those core files must coexist / replace. If the latter, the CUDA add-on may need to overwrite `llama.dll` / `ggml.dll` (CUDA-built version of those files should still expose Vulkan via the runtime registry — verify in testing).
3. **Final DLL inventory** (cuDNN deliberately omitted — llama.cpp uses cuBLAS, not cuDNN):
   - `ggml-cuda.dll` (the backend)
   - `cudart64_12.dll` (CUDA runtime)
   - `cublas64_12.dll` (cuBLAS)
   - `cublasLt64_12.dll` (cuBLAS Linear Algebra)
   - Plus core `llama.dll` / `ggml.dll` / `ggml-base.dll` from the CUDA build, if Step 2 says they must replace the Vulkan-build versions
   - Total: ~600 MiB compressed for the in-app add-on payload
4. **Publish the CUDA add-on bundle on ModelScope**:
   - Repo: `gtree592/bashi-qwen3-tts-cuda-runtime`
   - Layout: `win-x64/manifest.json` + `win-x64/cuda-runtime-b7798-win-cuda-12.4-x64.zip`; future Linux NVIDIA support (v0.2.1) populates `linux-x64/`
   - Manifest schema: `{ "platform": "win-x64", "llama_cpp_build": "b7798", "cuda_version": "12.4", "archives": [{ "path": ..., "sha256": ..., "size": ..., "extract": [{ "path": ..., "sha256": ..., "size": ... }, ...] }] }`
5. **Backend-reporting fix** (Finding 1 — landed in working copy):
   - `backend_probe.detect_gguf_accelerator()` does a filesystem inventory of `inference/bin/` + hardware vendor check, returns `"cuda" | "vulkan" | "cpu"`. (Filesystem-based detection is robust and avoids re-invoking the kernel just to read its print-system-info output.)
   - `/api/system-info` exposes new `gguf_accelerator` field; chip label dispatches: `GGUF + CUDA` (CUDA active) / `GGUF + Vulkan (Vulkan fallback)` (NVIDIA without CUDA DLL) / `GGUF + CPU` (user-forced via `GGUF_LLM_USE_GPU=0`)
6. **CUDA add-on download infrastructure** (NEW for Option C — landed in working copy):
   - `download_cuda_runtime.py`: dependency-free generator-based downloader (Range/resume, idle timeout, SHA256, manifest-driven). Mirrors `download_gguf_model.py`'s pattern + `model_manager.py`'s SSE event shape so the frontend reuses existing download UI plumbing.
   - `/api/cuda-upgrade/status` (GET): reports `{applicable, installed, platform_supported, requires_restart, ...}` — drives banner visibility
   - `/api/cuda-upgrade/download` (POST, SSE): single-flight; yields byte-progress events; sets in-memory `requires_restart` flag on completion (the already-loaded kernel was Vulkan-bound; CUDA only kicks in on next launch)
   - Frontend: "Upgrade to NVIDIA CUDA acceleration / 升级到 CUDA 加速" banner under the backend chip when `applicable === true`; replaced by "Restart app to enable CUDA / 重启应用以启用 CUDA" success banner after install
7. **End-to-end verification** (on NVIDIA box):
   - Fresh extract on NVIDIA Windows machine → chip says `GGUF + Vulkan (Vulkan fallback)` + upgrade banner visible
   - Click upgrade → download progress → success banner → app restart → chip says `GGUF + CUDA`
   - Measured token/sec ≥ 1.5× the same card's Vulkan number
   - AMD RX 590 / RX 9060 XT / Intel N100 / N305: chip says `GGUF + Vulkan` (or appropriate vendor label); upgrade banner hidden; no regression vs v0.1
   - User-forced CPU mode (`Start_CPU_only_仅CPU启动.bat`): chip says `GGUF + CPU`; upgrade banner hidden
8. **README update**:
   - Hardware Coverage Matrix: NVIDIA rows change from ⚠️ to ✓ Tested (with the caveat "optional CUDA upgrade via in-app download")
   - Network Behavior section: mention the optional CUDA add-on as another user-initiated download, parallel to GGUF model and STT models
   - Version badge bump
9. **`Start_CPU_only_仅CPU启动.bat`** (landed in working copy): top-level convenience launcher so N100/N305 users can A/B-test CPU vs iGPU without env var fiddling. Sets `GGUF_LLM_USE_GPU=0` + `GGUF_ONNX_PROVIDER=CPU` then delegates to `run_portable.bat`.

### Acceptance criteria

- v0.1.1 main zip stays close to v0.1 size (~108 MB), no penalty for non-NVIDIA users
- On NVIDIA: upgrade banner appears, download succeeds, restart switches chip to `GGUF + CUDA`, token/sec ≥ 1.5× Vulkan baseline
- On AMD / Intel / forced-CPU / non-Windows: upgrade banner hidden by `/api/cuda-upgrade/status`; no regression vs v0.1
- CUDA add-on ModelScope repo populated with manifest + SHA256s; download resumes correctly after network interruption
- README hardware table reflects measured CUDA numbers

### Risks (updated after review)

- **No NVIDIA test hardware available** (Alex's discrete GPU is AMD). Mitigations: community tester recruited via the WeChat group or GitHub issues; or a temporary NVIDIA box is sourced; or release as "v0.1.1-rc1" tagged for community NVIDIA verification before final.
- **DLL coexistence may not be plug-and-play** (Finding 2 — until Step 2 confirms otherwise): if the CUDA build's `llama.dll` / `ggml.dll` aren't binary-compatible with the Vulkan ones, the CUDA add-on may have to overwrite them. Acceptable as long as the CUDA-built core DLLs still expose Vulkan (probable — they're a superset). Worst case the add-on becomes "swap mode" instead of "additive", documented in release notes.
- **NVIDIA driver compatibility**: CUDA 12.4 needs driver ≥ 550.x. Older NVIDIA drivers don't qualify — `/api/cuda-upgrade/status` returns `applicable: false`, banner hidden, Vulkan path used (transparent fallback, verified).
- ~~**Backend auto-selection priority**~~ — **resolved** by source review: `llama.cpp` registers backends in lexicographic DLL discovery order; CUDA naturally takes precedence over Vulkan on NVIDIA hardware without any wrapper override.
- ~~**CUDA package size**~~ — **resolved** by Option C: ~600 MiB add-on download only for users who opt in, not bundled in main zip.
- ~~**cuDNN size**~~ — **resolved**: cuDNN not used by llama.cpp, omitted entirely.

### Effort estimate

**~1 week calendar** (recalibrated, down from 1-2). Working-copy progress: backend reporting (Step 5), download infrastructure (Step 6), CPU-only launcher (Step 9) already implemented. Remaining: ModelScope upload (Step 4, ~½ day), NVIDIA end-to-end verification (Step 7, gated on test hardware), README + release notes (Step 8, ~½ day).

---

## v0.1.2 — NVIDIA detection and backend robustness (Windows patch, shipped 2026-06-15)

**Goal**: make NVIDIA detection reliable on consumer cloud PCs and remote-display setups, while isolating native startup-probe crashes into actionable errors without regressing AMD / Intel / CPU-only users.

### Shipped scope

- **NVIDIA vendor detection fix**: query `nvidia-smi --query-gpu=name --format=csv,noheader` before `Win32_VideoController`, because virtual display layers can make WMI report names such as `HMvMonitorCloudPC Device` instead of the physical GPU.
- **Defense-in-depth executable lookup**: try `nvidia-smi` on `PATH`, the System32 location, the legacy NVIDIA NVSMI location, and the `%ProgramFiles%`-expanded NVSMI location. If all attempts fail, keep the existing WMI behavior. Stop after the first timeout instead of waiting on equivalent paths, and suppress child console windows.
- **Correct post-upgrade backend label**: on Windows NVIDIA systems, an installed `ggml-cuda.dll` reports `GGUF + CUDA` without relying on `torch.cuda.is_available()`, because the shipped PyTorch wheel is CPU-only and cannot describe the independent GGUF CUDA runtime.
- **Regression fixture**: use the real `NVIDIA GeForce RTX 5070` output measured on 海马云 HMv Cloud PC; verify non-NVIDIA and no-driver systems still fall back to WMI.
- **Native startup-probe isolation**: run each real backend probe in a child Python process with a 300-second hard timeout. Native access violations and hung GPU initialization now become actionable failed-probe results so the selector can continue its fallback ladder instead of crashing the launcher process.

### Remaining backlog for later patches

- Extend native-crash isolation into the selected runtime's lazy first-use initialization and add an explicit CUDA → Vulkan → CPU subpath fallback. The current child-process boundary protects startup preflight probes.
- Detect TCC mode and incompatible NVIDIA driver versions before initializing Vulkan, DirectML, or CUDA.
- Recognize a GGUF installation with `ggml-cuda.dll` even when Vulkan is intentionally disabled.
- Preserve legitimate `USE_GGUF_BACKEND` overrides and add a launcher-level Vulkan-disable switch.
- Bundle the small first-launch pip wheel to reduce bootstrap failure risk.

---

## v0.1.3 — STT quality/safety patch (Windows patch, in progress)

**Goal**: improve Chinese STT quality without losing the fast local workflow, and remove UI paths that imply unsupported accuracy.

### Planned / working scope

- Keep **SenseVoice Small** as the default fast multilingual STT model.
- Keep **Parakeet TDT 0.6B** as the optional English-specialist model.
- Remove **Paraformer Chinese Large** from the product surface. Decision locked on 2026-07-04 after three-way subtitle evaluation and review: the integrated Paraformer path did not use true token timestamps, had worse Chinese accuracy than SenseVoice, and added a redundant model/download path.
- Add a static Chinese STT correction layer: `zh_confusion.py` + user-editable `data/zh_confusion.tsv`. It runs on SenseVoice text before subtitle splitting, keeps risky common-word replacements disabled by default, and is the current highest-ROI path for real-domain Chinese quality improvements.
- Stop treating **FireRedASR AED-L** as a candidate product path. Quality was strong, but CPU speed failed the cutoff decisively on the same 68.5min meeting:
  - serial baseline: `asr_seconds=4283s`
  - time-order batch: `asr_seconds=4678.875s`
  - length-bucket batch: `asr_seconds=4802.907s`
  - conclusion: CPU FireRed is ~1x realtime and batch decoding regressed, so the CPU high-quality lane is closed.
- Hide **Speaker ID** UI by default. The single-mic far-field meeting test collapsed into unusable clusters even after CAM++/ERes2Net attempts, so it is not a release feature.
- Add STT upload-size guardrails and tighten audio-conversion filename validation.

### Backlog, not release scope

- Revisit speaker labeling only if the recording condition changes, e.g. one mic per person or multichannel input.
- Consider GPU ASR (for example whisper.cpp Vulkan) for the "high quality + fast" lane.
- Expand `data/zh_confusion.tsv` only from real user audio mistakes, with each candidate classified as safe global replacement, phrase-anchored replacement, or disabled dangerous item.
- Refactor duplicated STT VAD/WAV logic after the product direction settles.

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

*Last updated: 2026-07-05 (v0.1.3 STT quality/safety patch planning). Next review: before the next Windows patch or v0.2 cross-platform work.*
