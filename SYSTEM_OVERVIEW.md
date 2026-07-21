# System Overview

This document is for AI tools and contributors who need a current, code-level mental model of Bashi Voice Factory Privacy Edition.

## Project Identity

`Bashi Voice Factory Privacy Edition` is a local Flask web application for:

- `TTS`: local Qwen3-TTS-12Hz-1.7B-CustomVoice synthesis
- `STT`: local sherpa-onnx transcription

The browser is the UI, Flask is the local server, runtime state is stored on disk or in memory, and the product is optimized for portable Windows distribution.

## High-Level Architecture

```text
Browser UI
  |
  | HTTP / SSE
  v
Flask app (app.py)
  |
  +-- TTS Blueprint (tts_routes.py)
  |     |
  |     +-- request validation and chunking
  |     +-- backend status / ETA / CUDA add-on routes
  |     +-- local_tts_engine.py backend selector
  |     |     |
  |     |     +-- local_tts_engine_gguf.py
  |     |     |     +-- Qwen3-TTS-GGUF runtime
  |     |     |     +-- Vulkan / CUDA / CPU ggml backend
  |     |     |     +-- DirectML or CPU ONNX decoder
  |     |     |
  |     |     +-- local_tts_engine_pytorch.py
  |     |           +-- bashi_tts_kernel package
  |     |           +-- PyTorch / qwen-tts path
  |     |
  |     +-- output files in static/audio/
  |
  +-- STT Blueprint (stt_routes.py)
        |
        +-- upload media to static/uploads/
        +-- utils.extract_audio_wav() to 16 kHz WAV
        +-- model_manager.py model registry / downloads
        +-- sherpa-onnx engine wrappers
        |     +-- engines/sherpa_sensevoice.py
        |     +-- engines/sherpa_parakeet.py
        |
        +-- zh_confusion.py static Chinese correction layer
        +-- optional speaker_diarization.py path, UI disabled by default
        +-- background transcription thread
        +-- SSE progress stream
        +-- TXT / SRT / VTT export
```

## Runtime Flows

### Startup

```text
run_portable.ps1 / run_portable.bat
-> ensure embedded Python and dependencies
-> ensure GGUF runtime model pack when needed
-> app.py calls backend_probe.bootstrap_backend_selection()
-> local_tts_engine.py imports the selected TTS service
-> Flask registers TTS and STT blueprints
```

Important startup files:

- `backend_probe.py`
- `run_portable.ps1`
- `run_portable.bat`
- `download_gguf_model.py`
- `download_cuda_runtime.py`

### TTS

```text
User submits text
-> static/js/app.js posts to tts_routes.py
-> tts_routes.py validates mode, speaker, language, and chunking settings
-> selected local TTS service synthesizes audio
-> audio is saved in static/audio/
-> browser receives playback/download metadata
```

Current TTS backends:

- GGUF path: `local_tts_engine_gguf.py`
- PyTorch path: `local_tts_engine_pytorch.py`
- common import switch: `local_tts_engine.py`
- shared PyTorch kernel package: `bashi_tts_kernel/`

### STT

```text
User uploads audio/video
-> stt_routes.py stores the original upload in static/uploads/
-> utils.extract_audio_wav() creates a 16 kHz WAV
-> stt_routes.acquire_engine() loads selected sherpa wrapper
-> engine runs Silero VAD and sherpa-onnx recognition
-> SenseVoice output passes through zh_confusion.py before subtitle splitting
-> stt_jobs[job_id] accumulates segments
-> browser receives progress via SSE
-> export_result() returns TXT / SRT / VTT
```

Current STT engines:

- `sensevoice-small-int8`: default multilingual model, zh/en/ja/ko/yue
- `parakeet-tdt-0.6b-v2-int8`: English-specialist model

## Core Source Tree

```text
bashi-privacy-app/
├─ app.py
├─ backend_probe.py
├─ tts_routes.py
├─ stt_routes.py
├─ local_tts_engine.py
├─ local_tts_engine_gguf.py
├─ local_tts_engine_pytorch.py
├─ local_voice_catalog.py
├─ model_manager.py
├─ speaker_diarization.py
├─ stt_engine.py
├─ zh_confusion.py
├─ utils.py
├─ audio_encoding.py
├─ download_gguf_model.py
├─ download_cuda_runtime.py
├─ requirements.txt
├─ VERSION
├─ data/
│  └─ zh_confusion.tsv
├─ bashi_tts_kernel/
│  ├─ __init__.py
│  ├─ bashi_tts_core.py
│  ├─ speakers.json
│  └─ zh_normalizer_lite.py
├─ engines/
│  ├─ sherpa_sensevoice.py
│  └─ sherpa_parakeet.py
├─ templates/
│  └─ index.html
├─ static/
│  ├─ css/style.css
│  ├─ js/app.js
│  ├─ images/
│  ├─ audio/
│  └─ uploads/
├─ scripts/
│  ├─ build_portable_zip.ps1
│  ├─ precheck_py312_embed.ps1
│  └─ run_speaker_diarization_probe.py
└─ release_docs/
```

## File Responsibilities

### App Wiring

- `app.py`
  - creates the Flask app
  - registers TTS and STT blueprints
  - runs backend preflight selection before serving
  - cleans old runtime audio/upload files on startup

- `backend_probe.py`
  - chooses GGUF or PyTorch backend
  - detects hardware and GGUF accelerator class
  - runs isolated real probes so native crashes do not kill startup silently
  - caches probe results for faster relaunch

### TTS Domain

- `tts_routes.py`
  - synthesis routes
  - speaker and style handling
  - text chunking
  - output file serving
  - benchmark / ETA routes
  - system-info route
  - CUDA add-on status and download routes

- `local_tts_engine.py`
  - imports the active TTS service according to `USE_GGUF_BACKEND`

- `local_tts_engine_gguf.py`
  - wraps the GGUF runtime under `vulkan_backend_spike/Qwen3-TTS-GGUF`
  - manages long-text chunk grouping
  - trims per-chunk silence for long-mode output
  - uses `bashi_tts_kernel.zh_normalizer_lite` for conservative Chinese text normalization

- `local_tts_engine_pytorch.py`
  - wraps the PyTorch/qwen-tts path
  - uses model weights under `bashi_tts_kernel/models/`

- `local_voice_catalog.py`
  - exposes bundled speaker metadata and preview mapping

- `bashi_tts_kernel/`
  - local kernel support for the PyTorch path
  - includes speaker metadata and the lightweight Chinese normalizer

### STT Domain

- `stt_routes.py`
  - STT API endpoints
  - upload handling
  - model listing and download routes
  - single-job admission control
  - background transcription worker
  - SSE progress stream
  - optional Speaker ID orchestration
  - TXT / SRT / VTT export helpers

- `model_manager.py`
  - ASR model registry
  - shared Silero VAD model metadata
  - optional Speaker ID model metadata
  - model completeness checks
  - byte-progress download generator with mirror fallback
  - tar extraction for Speaker ID assets

- `stt_engine.py`
  - shared `Segment` and `TranscriptionResult` dataclasses
  - abstract STT engine interface

- `engines/sherpa_sensevoice.py`
  - SenseVoice + Silero VAD wrapper
  - default multilingual STT path
  - applies `zh_confusion.py` after `result.text.strip()` and before subtitle splitting

- `engines/sherpa_parakeet.py`
  - Parakeet TDT + Silero VAD wrapper
  - English-specialized STT path

- `zh_confusion.py`
  - loads `data/zh_confusion.tsv`
  - caches by mtime
  - applies longest-key-first static Chinese corrections
  - fails safe to no-op when the table is missing or unreadable

- `data/zh_confusion.tsv`
  - user-editable wrong/right table
  - active entries are conservative, high-confidence corrections
  - dangerous common-word replacements remain commented out by default

- `speaker_diarization.py`
  - experimental local speaker labeling wrapper
  - maps diarization turns onto ASR segments
  - release UI stays hidden unless `BASHI_SPEAKER_ID_UI=1`

### Shared Helpers

- `utils.py`
  - ffmpeg-backed audio extraction through `imageio_ffmpeg`
  - runtime cleanup helpers

- `audio_encoding.py`
  - audio encoding/format utilities used by TTS routes and tests

### Front End

- `templates/index.html`
  - single-page shell for TTS and STT

- `static/js/app.js`
  - all browser behavior
  - TTS request flow
  - backend/ETA display
  - CUDA upgrade UI
  - STT model/language routing
  - STT upload/progress/result/export flow

- `static/css/style.css`
  - UI styling

### Packaging

- `scripts/build_portable_zip.ps1`
  - stages the Windows portable package
  - copies required Python files, `data/`, `engines/`, templates, static assets, and launchers
  - excludes caches, tests, generated audio, generated transcripts, and local model files

- `scripts/precheck_py312_embed.ps1`
  - validates the embedded Python environment before release

- `run_portable.ps1` / `run_portable.bat`
  - first-launch dependency setup
  - GGUF runtime pack check/download
  - local Flask launch

- `run-gguf.*` and `run-pytorch.*`
  - backend-pinned launchers for debugging and comparison

## Runtime Directories

- `static/audio/`
  - generated TTS files

- `static/uploads/`
  - uploaded media and extracted WAV files while STT jobs run

- `models/`
  - downloaded STT and Speaker ID models

- `.stt_metrics/`
  - JSON timing and Speaker ID diagnostic records for completed STT jobs

- `.tmp/`
  - local temporary probes and development artifacts

- `dist/`
  - packaged release output

## Internal Concepts

### Backend Selection

The app chooses a TTS backend before serving requests.

- `USE_GGUF_BACKEND=1` pins GGUF.
- `USE_PYTORCH_BACKEND=1` pins PyTorch.
- Conflicting overrides abort startup with a clear error.
- GGUF accelerator reporting distinguishes CUDA, Vulkan, CPU, and unknown/fallback states.

### TTS Chunking

`tts_routes.split_into_chunks()` is the route-layer splitter. GGUF long mode reuses it and then applies GGUF-specific phrase grouping in `local_tts_engine_gguf.py`.

### STT Job Model

`stt_jobs` is an in-memory dictionary keyed by `job_id`. Jobs include:

- filename and selected model id
- status
- accumulated segments
- optional Speaker ID fields
- timing metrics
- error state
- creation timestamp

Only one transcription job is admitted at a time. `engine_lock`, `_job_active`, `_engine_ref_count`, `engine_instance`, and `current_engine_model_id` coordinate admission and model reuse.

### STT Correction Layer

SenseVoice text is corrected before subtitle splitting:

```text
stream.result.text.strip()
-> zh_confusion.apply_zh_confusions()
-> _is_punctuation_only()
-> _split_text_into_segments()
```

The correction layer is deliberately static and editable. It does not use model-based rewriting, and it avoids broad common-word replacements unless the user explicitly enables them in the TSV file.

### Subtitle Export Pipeline

`stt_routes.export_result()` performs export-only cleanup:

1. merge short fragments for `srt` and `vtt`
2. fix timestamp overlaps
3. normalize subtitle text
4. optionally add speaker prefixes
5. skip empty cues
6. return the requested format

`txt` export stays close to the raw transcript, except for optional speaker labels.

### Speaker ID

Speaker labeling is present as an experimental offline path. It is disabled in the release UI by default because single-mic far-field meeting tests produced unreliable clusters. Enable only for experiments with `BASHI_SPEAKER_ID_UI=1`.

## Dependencies

Declared in `requirements.txt`:

- Flask
- imageio-ffmpeg
- numpy
- soundfile
- torch
- transformers
- accelerate
- huggingface_hub
- safetensors
- qwen-tts
- sherpa-onnx
- gguf
- onnx
- onnxruntime-directml
- sentencepiece
- sounddevice

Functional notes:

- TTS synthesis is local after dependencies and model assets are present.
- STT inference is local after model download.
- First launch may download Python dependencies and the GGUF runtime model pack.
- Optional CUDA and STT model downloads are user-initiated.

## Current Model Inventory

Managed in `model_manager.py`:

- `sensevoice-small-int8`
  - default STT model
  - supports Chinese, English, Japanese, Korean, and Cantonese

- `parakeet-tdt-0.6b-v2-int8`
  - optional English-specialist STT model

- `speaker-diarization-pyannote-3dspeaker`
  - optional experimental Speaker ID pack
  - hidden from the release UI by default

## Testing

Common verification commands:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
node --check static\js\app.js
git diff --check
```

High-signal test files:

- `tests/test_backend_probe.py`
- `tests/test_stt_speaker_id.py`
- `tests/test_zh_confusion.py`
- `tests/test_text_chunking.py`
- `tests/test_tts_routes_instruct.py`
- `tests/test_audio_encoding.py`

## Practical Guidance

### Modify TTS Behavior

Start with:

- `tts_routes.py`
- `local_tts_engine_gguf.py`
- `local_tts_engine_pytorch.py`
- `bashi_tts_kernel/zh_normalizer_lite.py`
- `static/js/app.js`

Keep GGUF-only long-mode behavior inside the GGUF service; do not push it into a shared base unless the PyTorch path actually needs the same behavior.

### Modify STT Behavior

Start with:

- `stt_routes.py`
- `model_manager.py`
- `stt_engine.py`
- `engines/sherpa_sensevoice.py`
- `engines/sherpa_parakeet.py`
- `zh_confusion.py`

Preserve the multilingual-safe `auto` route to SenseVoice unless there is a product decision to change it.

### Modify Chinese STT Corrections

Edit:

- `data/zh_confusion.tsv`

Rules of thumb:

- prefer long phrase keys
- keep common-word homophones commented out unless a narrow domain makes them safe
- validate with `tests/test_zh_confusion.py`

### Modify Export Formatting

Start with:

- `stt_routes.normalize_subtitle_text()`
- `stt_routes.merge_short_segments()`
- `stt_routes.fix_timestamp_overlaps()`
- `stt_routes.export_result()`

Keep raw transcript behavior separate from subtitle readability cleanup.

### Modify Packaging

Start with:

- `scripts/build_portable_zip.ps1`
- `run_portable.ps1`
- `run_portable.bat`
- `download_gguf_model.py`
- `download_cuda_runtime.py`

When adding a runtime Python module or data directory, make sure the portable staging script copies it.

## Design Constraints

- local-first and privacy-first
- no telemetry
- no background update checks
- simple portable Windows distribution is a first-class use case
- one active STT job at a time
- STT model downloads are explicit and user-initiated
- user-facing release notes should avoid internal validation noise

## One-Sentence Summary

This repository is a Flask monolith with a plain-JS front end, local Qwen3 TTS through GGUF or PyTorch, local sherpa-onnx STT through SenseVoice and Parakeet, a static Chinese STT correction table, filesystem-based runtime storage, SSE progress updates, and Windows-portable packaging centered on `app.py`, `tts_routes.py`, `stt_routes.py`, `local_tts_engine*.py`, `model_manager.py`, `backend_probe.py`, and `engines/`.
