# System Overview

This document is intended for AI tools and new contributors who need a fast, accurate mental model of the codebase.

## Project Identity

`Bashi Voice Factory / 巴适声工厂` is a Flask-based local web application with two primary capabilities:

- `TTS`: text-to-speech using Microsoft Edge TTS via the `edge-tts` Python package
- `STT`: speech-to-text using local offline ASR models through `sherpa-onnx`

The app is designed as a single-machine web UI rather than a cloud backend. The browser is the UI, Flask is the application server, TTS is network-backed, and STT is local/offline.

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
  |     +-- input preprocessing
  |     |     - long text chunking
  |     |     - Chinese TTS patch rules
  |     |
  |     +-- Microsoft Edge TTS via edge_tts
  |     |
  |     +-- optional ffmpeg conversion
  |     +-- runtime audio outputs in static/audio/
  |
  +-- STT Blueprint (stt_routes.py)
        |
        +-- upload media to static/uploads/
        +-- ffmpeg audio extraction
        +-- model selection / download
        +-- load local ASR engine
        |     - SenseVoice
        |     - Parakeet
        |
        +-- background transcription thread
        +-- SSE progress stream
        +-- TXT / SRT / VTT export
              - segment merge
              - subtitle normalization
              - timestamp cleanup
```

## Runtime Data Flow

### TTS Flow

```text
User enters text in browser
-> front-end submits TTS request
-> tts_routes.py validates and preprocesses text
-> optional Chinese patching via zh_tts_patch.py
-> edge_tts synthesizes audio
-> optional ffmpeg conversion to wav/ogg/flac
-> output saved to static/audio/
-> browser plays or downloads generated file
```

### STT Flow

```text
User uploads audio/video
-> stt_routes.py saves original file to static/uploads/
-> utils.extract_audio_wav() creates wav
-> model_manager.py resolves selected model
-> sherpa engine transcribes audio in background thread
-> segments stored in in-memory stt_jobs[job_id]
-> browser receives progress via SSE
-> final result available as JSON / TXT / SRT / VTT
```

## Architectural Style

- Monolithic Flask application
- Native server-rendered HTML entry point
- Front-end logic is plain JavaScript, not React/Vue
- No database; operational state is kept in memory or on disk
- Runtime storage is filesystem-based
- STT jobs are ephemeral in-process objects
- Packaging supports portable Windows distribution and shell launchers for other platforms

## Core Source Tree

```text
edge-tts-app/
├─ app.py
├─ tts_routes.py
├─ stt_routes.py
├─ zh_tts_patch.py
├─ model_manager.py
├─ stt_engine.py
├─ utils.py
├─ download_model.py
├─ VERSION
├─ requirements.txt
├─ run_portable.bat
├─ run_venv.sh
├─ templates/
│  └─ index.html
├─ static/
│  ├─ css/
│  │  └─ style.css
│  ├─ js/
│  │  └─ app.js
│  ├─ images/
│  ├─ audio/
│  └─ uploads/
├─ engines/
│  ├─ sherpa_sensevoice.py
│  └─ sherpa_parakeet.py
├─ models/
├─ dist/
├─ test_export_subtitles.py
├─ test_zh_tts_patch.py
├─ test_tts_readback.py
├─ test_models.py
└─ README.md / README_CN.md
```

## File-by-File Responsibilities

### Entry and App Wiring

- `app.py`
  - Flask app entry point
  - registers TTS and STT blueprints
  - serves `/`
  - performs old-file cleanup on startup
  - parses `--host` and `--port`

### TTS Domain

- `tts_routes.py`
  - TTS API endpoints
  - voice registry
  - long-text chunking
  - shadowing / segmented playback logic
  - synthesis via `edge_tts`
  - output file generation
  - ffmpeg-based audio conversion
  - Chinese text preprocessing integration

- `zh_tts_patch.py`
  - lightweight Chinese TTS patch layer
  - intentionally small and high-value only
  - handles:
    - classical chapter references
    - selected phone number formats
    - URL simplification
    - file path simplification
    - punctuation cleanup
  - not intended to be a full Chinese normalizer

### STT Domain

- `stt_routes.py`
  - STT API endpoints
  - upload handling
  - model listing and download APIs
  - job lifecycle and in-memory job storage
  - single-job admission control
  - background transcription thread
  - SSE progress endpoint
  - export to `txt`, `srt`, `vtt`
  - subtitle cleanup and formatting rules

- `model_manager.py`
  - model registry
  - model presence checks
  - model download logic
  - mirror support
  - file hashing / verification
  - default model selection

- `stt_engine.py`
  - shared STT data model / abstractions
  - segment structures used by engine wrappers

- `engines/sherpa_sensevoice.py`
  - wrapper around sherpa-onnx SenseVoice inference
  - multilingual STT path
  - segmentation / punctuation-aware output handling

- `engines/sherpa_parakeet.py`
  - wrapper around sherpa-onnx Parakeet inference
  - English-specialized STT path

### Shared Helpers

- `utils.py`
  - ffmpeg-based audio extraction helper
  - cleanup helpers for old runtime files

- `download_model.py`
  - minimal CLI helper used by `run_portable.bat`
  - downloads the default STT model without launching the web app

### Front-End

- `templates/index.html`
  - single-page shell
  - contains the UI structure for both TTS and STT

- `static/js/app.js`
  - all front-end behavior
  - TTS form submission
  - STT upload and polling/SSE logic
  - UI state transitions
  - export controls
  - model/language dropdown interaction

- `static/css/style.css`
  - main styling for the app

- `static/images/`
  - branding and donation images

### Packaging and Distribution

- `run_portable.bat`
  - Windows portable launcher
  - locates embedded Python
  - bootstraps pip
  - installs requirements
  - optionally downloads the default STT model
  - starts Flask app

- `run_venv.sh`
  - Unix shell launcher

- `build_mac_linux_bundle.py`
  - generates trimmed Mac/Linux distribution bundle

- `dist/`
  - packaged release outputs

## Key Runtime Directories

- `static/audio/`
  - TTS output files created at runtime

- `static/uploads/`
  - uploaded user media and temporary WAV files for STT

- `models/`
  - downloaded STT models

- `dist/`
  - generated release packages

- `tts_readback_outputs/`
  - development-only benchmark outputs for TTS readback testing

## Major Internal Concepts

### TTS Text Preparation

TTS requests may go through a preparation step before synthesis:

- long text is chunked
- Chinese text may be normalized using `zh_tts_patch.py`
- TTS outputs are saved first, then optionally converted to alternative formats

### STT Job Model

STT work is represented in memory using `stt_jobs`, keyed by `job_id`.

Each job typically contains:

- `job_id`
- original filename
- selected model id
- status
- accumulated segments
- error, if any
- creation timestamp

This is not persisted to a database.

### STT Concurrency Model

The current design intentionally allows only one active transcription at a time.

Reasons:

- the shared engine instance is global
- offline recognizers are not assumed thread-safe for concurrent decode
- single-job admission simplifies teardown, model swapping, and portable deployment

Key control variables in `stt_routes.py`:

- `_job_active`
- `_engine_ref_count`
- `engine_instance`
- `current_engine_model_id`
- `engine_lock`

### Subtitle Export Pipeline

For `srt` and `vtt`, the export path is more than a plain dump:

1. merge short ASR fragments
2. fix timestamp overlaps
3. normalize subtitle text
4. skip empty cues
5. write final export

Important helper functions in `stt_routes.py`:

- `merge_short_segments()`
- `fix_timestamp_overlaps()`
- `normalize_subtitle_text()`
- `format_timestamp()`

### Chinese Subtitle Policy

The current subtitle policy is language-sensitive:

- CJK-dominant subtitle text:
  - removes punctuation
  - preserves visual pause with one full-width space
  - protects URLs, times, and formatted numbers

- English-dominant subtitle text:
  - punctuation is preserved

### Chinese TTS Patch Policy

The TTS patch layer is intentionally conservative:

- only high-value, proven cases are patched
- no broad number/date normalization
- English and non-Chinese paths should remain unaffected

## External Dependencies

Declared in `requirements.txt`:

- `flask`
- `edge-tts`
- `imageio-ffmpeg`
- `sherpa-onnx`
- `numpy`

Functional dependency notes:

- TTS depends on Microsoft Edge TTS service over the network
- STT is local/offline after model download
- ffmpeg capability is used through `imageio_ffmpeg`

## Current Model Inventory

Managed by `model_manager.py`:

- `sensevoice-small-int8`
  - multilingual default
  - Chinese / English / Japanese / Korean / Cantonese

- `parakeet-tdt-0.6b-v2-int8`
  - English-specialist model

The model registry is currently code-defined rather than dynamically discovered.

## Testing and Validation Files

- `test_export_subtitles.py`
  - regression tests for subtitle export policy

- `test_zh_tts_patch.py`
  - regression tests for Chinese TTS patch behavior

- `test_tts_readback.py`
  - TTS -> STT readback benchmark harness
  - useful for validating whether TTS preprocessing improves spoken output

- `test_models.py`
  - model comparison / quality evaluation

- `test_stt.py`
  - smaller STT-focused checks

## Non-Core or Development-Only Areas

These are usually not needed for architecture-level edits:

- `.git/`
- `docs_v3/`
- `tts_readback_outputs/`
- test media files in repository root
- prior packaged archives in repository root

## Practical Guidance for AI Tools

### If you need to modify TTS behavior

Start here:

- `tts_routes.py`
- `zh_tts_patch.py`
- `static/js/app.js`

Typical tasks:

- add preprocessing rules
- change chunking behavior
- alter audio export logic
- update voice behavior or UI presentation

### If you need to modify STT behavior

Start here:

- `stt_routes.py`
- `model_manager.py`
- `engines/sherpa_sensevoice.py`
- `engines/sherpa_parakeet.py`

Typical tasks:

- add or change model selection
- adjust concurrency behavior
- modify subtitle export policy
- improve segment merging
- alter progress streaming

### If you need to modify export formatting

Primary file:

- `stt_routes.py`

Focus on:

- `normalize_subtitle_text()`
- `merge_short_segments()`
- `export_result()`

### If you need to modify packaging or portable startup

Start here:

- `run_portable.bat`
- `download_model.py`
- `build_mac_linux_bundle.py`
- `dist/`

## Design Constraints and Assumptions

- The app is optimized for simple local deployment, not clustered deployment
- TTS and STT are implemented in the same Flask app process
- STT state is not persistent across restarts
- Front-end and back-end are tightly coupled through current route contracts
- File paths and packaging matter because Windows portable distribution is a first-class use case

## One-Sentence Summary

This repository is a Flask monolith with a plain-JS front-end, Microsoft-backed TTS, sherpa-onnx-backed offline STT, filesystem-based runtime storage, SSE progress updates, and a portable-distribution-friendly structure centered on `app.py`, `tts_routes.py`, `stt_routes.py`, `zh_tts_patch.py`, `model_manager.py`, and `engines/`.
