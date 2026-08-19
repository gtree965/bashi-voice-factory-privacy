import json
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path

import imageio_ffmpeg
from flask import Blueprint, Response, jsonify, request, send_from_directory, stream_with_context
from werkzeug.utils import secure_filename

from backend_probe import (
    MODEL_DEFAULT,
    detect_gguf_accelerator,
    detect_hardware_profile,
    get_probe_cache_path,
    load_probe_cache,
)
from download_cuda_runtime import (
    CudaRuntimeError,
    detect_platform_subdir as detect_cuda_platform_subdir,
    download_cuda_runtime_streaming,
    installed_manifest_summary as cuda_installed_summary,
    is_cuda_runtime_installed,
)
from local_tts_engine import OUTPUT_DIR, LocalTTSBusyError, LocalTTSError, service
from local_tts_service_base import WARMUP_WAIT_TIMEOUT
from logging_setup import get_logger


tts_bp = Blueprint("tts", __name__)
logger = get_logger(__name__)
APP_ROOT = Path(__file__).resolve().parent


def _read_app_version() -> str:
    version_path = APP_ROOT / "VERSION"
    try:
        version = version_path.read_text(encoding="utf-8").strip()
    except OSError:
        version = ""
    return version or "0.1.0"


VERSION = _read_app_version()
BENCHMARK_TEXT = "今天下午三点，我们将在会议室讨论项目进展和预算表。"
BENCHMARK_WARMUP_TEXT = "你好。"
# Keep this as an independent literal even while it matches BENCHMARK_TEXT:
# benchmark wording and UI cold-start coverage have separate product semantics.
WARMUP_TEXT = "今天下午三点，我们将在会议室讨论项目进展和预算表。"
BENCHMARK_TIMEOUT_SECONDS = 180
WARMUP_STARTUP_TIMEOUT_SECONDS = float(
    os.environ.get("BASHI_STARTUP_WARMUP_TIMEOUT", "180")
)
REFERENCE_CHAR_COUNTS = (1000, 5000)
VALID_SYNTHESIS_MODES = {"auto", "single", "long", "sentence", "reference"}
_BENCHMARK_EXECUTOR = ThreadPoolExecutor(max_workers=1)
_BENCHMARK_LOCK = threading.RLock()
_BENCHMARK_FUTURE = None
_WARMUP_EXECUTOR = ThreadPoolExecutor(max_workers=1)
_WARMUP_LOCK = threading.RLock()
_WARMUP_FUTURE = None
_WARMUP_STATE = {
    "state": "cold",
    "started_at": None,
    "elapsed_seconds": None,
    "error": None,
}
_SYSTEM_INFO_LOCK = threading.RLock()
_SYSTEM_INFO_CACHE = None
_CUDA_INSTALL_LOCK = threading.Lock()
# Set True when a CUDA download finishes this process. The running GGUF kernel
# was loaded with Vulkan; CUDA only kicks in on the next launch, so the UI
# needs a restart prompt rather than a silent backend swap.
_CUDA_UPGRADE_PENDING_RESTART = False


def split_long_sentence(sentence: str, limit: int, is_cjk: bool = False) -> list:
    def measure(text: str):
        return len(text) if is_cjk else len(text.split())

    def _hard_split(text: str):
        if is_cjk:
            return [text[i : i + limit] for i in range(0, len(text), limit)]

        words = text.split()
        return [" ".join(words[i : i + limit]) for i in range(0, len(words), limit)]

    def split_recursively(part: str):
        if measure(part) <= limit:
            return [part]
        # A strategy that returns the whole sentence unchanged would recurse forever
        # (e.g. a CJK clause ending in "；": re-joining text + separator reproduces the
        # input exactly). Fall back to the terminal fixed-width split instead.
        if part == sentence:
            return _hard_split(part)
        return split_long_sentence(part, limit, is_cjk)

    if is_cjk and re.search(r"[，、]", sentence):
        parts = re.split(r"([，、])", sentence)
        result = []
        current_chunk = ""
        for i in range(0, len(parts) - 1, 2):
            part = parts[i] + parts[i + 1]
            if measure(current_chunk + part) <= limit and current_chunk:
                current_chunk += part
            else:
                if current_chunk:
                    result.append(current_chunk)
                current_chunk = part
        if parts[-1]:
            if measure(current_chunk + parts[-1]) <= limit and current_chunk:
                current_chunk += parts[-1]
            else:
                if current_chunk:
                    result.append(current_chunk)
                current_chunk = parts[-1]
        if current_chunk:
            result.append(current_chunk)
        if len(result) > 1:
            return result

    if ";" in sentence or "；" in sentence:
        chunks = []
        parts = re.split(r"([;；])", sentence)
        for idx in range(0, len(parts), 2):
            part = parts[idx].strip()
            if not part:
                continue
            suffix = parts[idx + 1] if idx + 1 < len(parts) else ""
            chunk = part + suffix
            if measure(chunk) <= limit:
                chunks.append(chunk)
            else:
                chunks.extend(split_recursively(chunk))
        return chunks

    if ":" in sentence and sentence.count(":") == 1:
        parts = [part.strip() for part in sentence.split(":") if part.strip()]
        if len(parts) == 2:
            return split_recursively(parts[0] + ":") + split_recursively(parts[1])

    conjunction_pattern = r",\s*(and|but|so|for|or|yet|y|pero|o|et|mais|ou|aber|und|oder)\s+"
    match = re.search(conjunction_pattern, sentence, re.IGNORECASE)
    if match:
        return split_recursively(sentence[: match.start() + 1].strip()) + split_recursively(
            sentence[match.end() :].strip()
        )

    if "," in sentence:
        parts = sentence.split(",")
        result = []
        current_chunk = ""
        for i, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue
            test_part = part + ("," if i < len(parts) - 1 else "")
            if not current_chunk:
                current_chunk = test_part
            elif measure(current_chunk + " " + test_part) <= limit:
                current_chunk += " " + test_part
            else:
                result.append(current_chunk.strip())
                current_chunk = test_part
        if current_chunk:
            result.append(current_chunk.strip())
        if len(result) > 1:
            return result

    return _hard_split(sentence)


def split_into_chunks(text: str, max_words: int = 0, newline_hard: bool = True) -> list:
    chunks = []
    if newline_hard:
        paragraphs = text.strip().split("\n")
    else:
        paragraphs = re.split(r"\n\s*\n+", text.strip())
        paragraphs = [re.sub(r"\s*\n\s*", " ", p).strip() for p in paragraphs]

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        sentence_pattern = r"([^.!?。！？।؟;；]+[.!?。！？।؟;；]+[”’』」）】》]*)"
        sentences = re.findall(sentence_pattern, para)
        remaining = re.sub(sentence_pattern, "", para).strip()
        if remaining:
            sentences.append(remaining)
        if not sentences:
            sentences = [para]

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            is_cjk = bool(re.search(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]", sentence))
            chunk_length = len(sentence) if is_cjk else len(sentence.split())
            adjusted_limit = max_words * 2 if is_cjk else max_words
            if max_words == 0 or chunk_length <= adjusted_limit:
                chunks.append(sentence)
            else:
                chunks.extend(split_long_sentence(sentence, adjusted_limit, is_cjk))
    return chunks


ALLOWED_FORMATS = {"wav", "ogg", "flac"}


def _json_error(error: str, status: int = 500):
    return jsonify({"error": error, "error_zh": error}), status


def _selected_backend() -> str:
    if os.environ.get("USE_GGUF_BACKEND") == "1":
        return "gguf"
    if os.environ.get("USE_PYTORCH_BACKEND") == "1":
        return "pytorch"

    cache = load_probe_cache(get_probe_cache_path())
    if cache:
        return cache.selected_backend
    return "pytorch"


def _probe_cache_key() -> dict:
    cache = load_probe_cache(get_probe_cache_path())
    if cache:
        return dict(cache.cache_key)
    return {}


def _system_info_payload() -> dict:
    global _SYSTEM_INFO_CACHE

    with _SYSTEM_INFO_LOCK:
        if _SYSTEM_INFO_CACHE is not None:
            return dict(_SYSTEM_INFO_CACHE)

    backend = _selected_backend()
    cache_key = _probe_cache_key()
    device_identity = cache_key.get("gpu_device_identity") or "unknown"
    vendor = (cache_key.get("gpu_vendor") or "unknown").lower()

    # Always resolve hardware once so we can pass it to detect_gguf_accelerator
    # without re-running the PowerShell GPU probe inside it.
    hardware = None
    try:
        hardware = detect_hardware_profile()
        if device_identity == "unknown" or vendor == "unknown":
            device_identity = hardware.gpu_device_identity or device_identity
            vendor = hardware.normalized_vendor or vendor
        has_cuda = hardware.has_cuda
        has_mps = hardware.has_mps
    except Exception:
        has_cuda = vendor == "nvidia"
        has_mps = vendor == "apple"

    # Detect the actual ggml accelerator backend that the GGUF runtime will
    # pick at model load. Required so the chip / detail labels reflect reality
    # when v0.1.1 ships CUDA DLLs alongside Vulkan.
    gguf_accelerator = detect_gguf_accelerator(hardware) if backend == "gguf" else None

    if backend == "gguf":
        if gguf_accelerator == "cuda":
            label_en = "NVIDIA CUDA acceleration"
            label_zh = "NVIDIA CUDA 加速"
            detail_en = "GGUF + CUDA"
            detail_zh = "GGUF + CUDA"
            acceleration_type = "gguf_cuda"
            chip_level = "ok"
            is_cpu_mode = False
        elif gguf_accelerator == "cpu":
            label_en = "GGUF CPU mode (user-forced)"
            label_zh = "GGUF CPU 模式（用户手动指定）"
            detail_en = "GGUF + CPU (GGUF_LLM_USE_GPU=0)"
            detail_zh = "GGUF + CPU（已设 GGUF_LLM_USE_GPU=0）"
            acceleration_type = "gguf_cpu"
            chip_level = "warning"
            is_cpu_mode = True
        else:
            # vulkan (or unknown — treat as vulkan-class since the GGUF backend
            # is loaded with use_gpu=True by default)
            if vendor == "amd":
                label_en = "AMD GPU acceleration"
                label_zh = "AMD 显卡加速"
            elif vendor == "intel":
                label_en = "Intel GPU acceleration"
                label_zh = "Intel 显卡加速"
            elif vendor == "nvidia":
                label_en = "NVIDIA GPU acceleration (Vulkan fallback)"
                label_zh = "NVIDIA 显卡加速（Vulkan 回退）"
            else:
                label_en = "GGUF GPU acceleration"
                label_zh = "GGUF 显卡加速"
            detail_en = "GGUF + Vulkan + DirectML"
            detail_zh = "GGUF + Vulkan + DirectML"
            acceleration_type = "gguf_vulkan_dml"
            chip_level = "ok"
            is_cpu_mode = False
    elif has_cuda:
        label_en = "NVIDIA CUDA acceleration"
        label_zh = "NVIDIA CUDA 加速"
        detail_en = "PyTorch CUDA"
        detail_zh = "PyTorch CUDA"
        acceleration_type = "cuda"
        chip_level = "ok"
        is_cpu_mode = False
    elif has_mps or vendor == "apple":
        label_en = "Apple Silicon acceleration"
        label_zh = "Apple Silicon 加速"
        detail_en = "PyTorch Metal/MPS"
        detail_zh = "PyTorch Metal/MPS"
        acceleration_type = "mps"
        chip_level = "ok"
        is_cpu_mode = False
    else:
        label_en = "CPU mode"
        label_zh = "CPU 模式"
        detail_en = "PyTorch CPU, slower for long text"
        detail_zh = "PyTorch CPU，长文本较慢"
        acceleration_type = "cpu"
        chip_level = "warning"
        is_cpu_mode = True

    payload = {
        "success": True,
        "app_version": VERSION,
        "backend": backend,
        "gguf_accelerator": gguf_accelerator,
        "model_default": MODEL_DEFAULT,
        "gpu_device_identity": device_identity,
        "gpu_vendor": vendor,
        "friendly_label_en": label_en,
        "friendly_label_zh": label_zh,
        "detail_en": detail_en,
        "detail_zh": detail_zh,
        "acceleration_type": acceleration_type,
        "chip_level": chip_level,
        "is_cpu_mode": is_cpu_mode,
        "cache_key": cache_key,
    }
    with _SYSTEM_INFO_LOCK:
        _SYSTEM_INFO_CACHE = dict(payload)
    return payload


def _kernel_stream_chunk_count(text: str) -> int:
    if not text.strip():
        return 0

    if _selected_backend() == "pytorch":
        try:
            from bashi_tts_kernel.bashi_tts_core import BashiTTSEngine  # noqa: WPS433

            return len(BashiTTSEngine._split_stream_text(object(), text, max_chars=20))
        except Exception:
            pass

    return max(1, len(split_into_chunks(text, max_words=15, newline_hard=True)))


def _read_audio_duration_seconds(filename: str) -> float | None:
    try:
        import soundfile as sf

        info = sf.info(str(OUTPUT_DIR / filename))
        if info.samplerate:
            return float(info.frames) / float(info.samplerate)
    except Exception:
        return None
    return None


def _delete_generated_audio(filename: str | None) -> None:
    if not filename:
        return
    try:
        audio_path = OUTPUT_DIR / filename
        if audio_path.exists():
            audio_path.unlink()
    except OSError:
        pass


def _warmup_status_payload() -> dict:
    with _WARMUP_LOCK:
        state = _WARMUP_STATE["state"]
        elapsed_seconds = _WARMUP_STATE["elapsed_seconds"]
        started_at = _WARMUP_STATE["started_at"]
        if state == "warming" and started_at is not None:
            elapsed_seconds = max(0.0, time.monotonic() - started_at)
        return {
            "success": True,
            "state": state,
            "elapsed_seconds": elapsed_seconds,
            "wait_timeout_seconds": WARMUP_WAIT_TIMEOUT,
            "error": _WARMUP_STATE["error"],
        }


def _ascii_log_text(value: object) -> str:
    """Keep dynamic warmup diagnostics machine-readable in app.log."""
    return str(value).encode("ascii", errors="backslashreplace").decode("ascii")


def _finish_warmup(state: str, error: str | None) -> None:
    with _WARMUP_LOCK:
        started_at = _WARMUP_STATE["started_at"]
        elapsed_seconds = (
            max(0.0, time.monotonic() - started_at)
            if started_at is not None
            else 0.0
        )
        _WARMUP_STATE.update(
            state=state,
            elapsed_seconds=elapsed_seconds,
            error=error,
        )
    if state == "ready":
        logger.info(
            "[Warmup Timing] state=ready elapsed_seconds=%.3f",
            elapsed_seconds,
        )
    else:
        logger.warning(
            "[Warmup Timing] state=failed elapsed_seconds=%.3f error=%s",
            elapsed_seconds,
            _ascii_log_text(error or "unknown"),
        )


def _warmup_worker() -> None:
    filename = None
    try:
        filename = service.synthesize_text(WARMUP_TEXT, None)
        _delete_generated_audio(filename)
        _finish_warmup("ready", None)
    except Exception as exc:
        _finish_warmup("failed", str(exc))
    finally:
        service.mark_warmup_finished()


def _clear_warmup_future(future) -> None:
    global _WARMUP_FUTURE
    with _WARMUP_LOCK:
        if _WARMUP_FUTURE is future:
            _WARMUP_FUTURE = None


def _begin_warmup() -> dict:
    global _WARMUP_FUTURE

    with _WARMUP_LOCK:
        if _WARMUP_STATE["state"] == "ready":
            return _warmup_status_payload()
        if _WARMUP_FUTURE is not None and not _WARMUP_FUTURE.done():
            return _warmup_status_payload()

        # Set this in the request thread before submit. Otherwise a synthesis
        # request can land after the task is queued but before its worker starts
        # and incorrectly receive an immediate busy response.
        service.mark_warmup_started()
        _WARMUP_STATE.update(
            state="warming",
            started_at=time.monotonic(),
            elapsed_seconds=0.0,
            error=None,
        )
        try:
            future = _WARMUP_EXECUTOR.submit(_warmup_worker)
        except Exception as exc:
            service.mark_warmup_finished()
            _finish_warmup("failed", str(exc))
            return _warmup_status_payload()

        _WARMUP_FUTURE = future
        future.add_done_callback(_clear_warmup_future)
        return _warmup_status_payload()


def run_warmup_synchronously() -> dict:
    """Start the UI warmup path and wait briefly without making startup fatal."""
    _begin_warmup()
    with _WARMUP_LOCK:
        pending = _WARMUP_FUTURE

    if pending is not None and not pending.done():
        try:
            pending.result(timeout=WARMUP_STARTUP_TIMEOUT_SECONDS)
        except TimeoutError:
            # The worker remains authoritative and keeps _warmup_active set.
            # app.py starts the server; UI requests then wait on this same job.
            pass

    return _warmup_status_payload()


def _format_seconds(seconds: float | None) -> dict | None:
    if seconds is None:
        return None
    seconds = max(0, float(seconds))
    rounded = int(round(seconds))
    hours, rem = divmod(rounded, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        en = f"{hours}h {minutes}m {secs}s"
        zh = f"{hours}小时{minutes}分{secs}秒"
    elif minutes:
        en = f"{minutes}m {secs}s"
        zh = f"{minutes}分{secs}秒"
    else:
        en = f"{secs}s"
        zh = f"{secs}秒"
    return {"seconds": seconds, "display_en": en, "display_zh": zh}


def _positive_number(value) -> float | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(value)


def _build_estimate_payload(
    midpoint: float,
    source: str,
    low_factor: float = 0.70,
    high_factor: float = 1.30,
) -> dict:
    return {
        "low": _format_seconds(midpoint * low_factor),
        "mid": _format_seconds(midpoint),
        "high": _format_seconds(midpoint * high_factor),
        "source": source,
        "is_rough_estimate": True,
    }


def _estimate_from_benchmark(
    char_count: int,
    benchmark: dict | None,
    chunk_count: int | None = None,
    synthesis_mode: str = "auto",
) -> dict | None:
    if not benchmark or char_count <= 0:
        return None

    synthesis_mode = synthesis_mode if synthesis_mode in VALID_SYNTHESIS_MODES else "auto"
    elapsed = _positive_number(benchmark.get("inference_seconds"))
    bench_chars = _positive_number(benchmark.get("char_count"))

    if synthesis_mode == "single" and elapsed:
        growth = 1.0
        if bench_chars:
            growth = max(1.0, float(char_count) / bench_chars)
        midpoint = elapsed * (growth ** 0.15)
        return _build_estimate_payload(
            midpoint,
            source="quick_benchmark_single_shot",
            low_factor=0.65,
            high_factor=1.55,
        )

    if synthesis_mode in {"long", "sentence", "auto"} and chunk_count:
        per_chunk = _positive_number(benchmark.get("per_chunk_seconds"))
        if per_chunk is None and elapsed:
            bench_chunks = _positive_number(benchmark.get("chunk_count"))
            if bench_chunks:
                per_chunk = elapsed / bench_chunks
        if per_chunk:
            midpoint = per_chunk * max(1, int(chunk_count))
            return _build_estimate_payload(
                midpoint,
                source="quick_benchmark_chunks",
                low_factor=0.70,
                high_factor=1.45,
            )

    per_char = _positive_number(benchmark.get("per_char_seconds"))
    if per_char is None and elapsed and bench_chars:
        per_char = elapsed / bench_chars
    if per_char is None:
        return None

    midpoint = float(per_char) * max(0, char_count)
    return _build_estimate_payload(midpoint, source="quick_benchmark_chars")


def _benchmark_worker(voice: str | None, instruct: str) -> dict:
    warmup_start = time.perf_counter()
    warmup_filename = service.synthesize_text(BENCHMARK_WARMUP_TEXT, voice, instruct=instruct)
    warmup_elapsed = time.perf_counter() - warmup_start
    _delete_generated_audio(warmup_filename)

    start = time.perf_counter()
    filename = service.synthesize_text(BENCHMARK_TEXT, voice, instruct=instruct)
    elapsed = time.perf_counter() - start
    char_count = len(BENCHMARK_TEXT)
    chunk_count = _kernel_stream_chunk_count(BENCHMARK_TEXT)
    duration = _read_audio_duration_seconds(filename)
    return {
        "success": True,
        "backend": _selected_backend(),
        "model_default": MODEL_DEFAULT,
        "benchmark_text": BENCHMARK_TEXT,
        "benchmark_language": "zh",
        "warmup_text": BENCHMARK_WARMUP_TEXT,
        "warmup_seconds": warmup_elapsed,
        "warmup_excluded": True,
        "voice": voice,
        "char_count": char_count,
        "chunk_count": chunk_count,
        "filename": filename,
        "audio_url": f"/static/audio/{filename}",
        "audio_duration_seconds": duration,
        "inference_seconds": elapsed,
        "per_char_seconds": elapsed / char_count if char_count else None,
        "per_chunk_seconds": elapsed / chunk_count if chunk_count else None,
        "rtf": elapsed / duration if duration else None,
        "is_rough_estimate": True,
    }


def _clear_benchmark_future(future):
    global _BENCHMARK_FUTURE
    with _BENCHMARK_LOCK:
        if _BENCHMARK_FUTURE is future:
            _BENCHMARK_FUTURE = None


@tts_bp.route("/api/warmup", methods=["POST"])
def start_warmup():
    return jsonify(_begin_warmup())


@tts_bp.route("/api/warmup/status")
def get_warmup_status():
    return jsonify(_warmup_status_payload())


@tts_bp.route("/api/voices")
def get_voices():
    return jsonify(service.get_voice_catalog())


@tts_bp.route("/api/system-info")
def get_system_info():
    return jsonify(_system_info_payload())


def _cuda_upgrade_status_payload() -> dict:
    """Build the /api/cuda-upgrade/status response. Filesystem-fresh, never cached."""
    system_info = _system_info_payload()
    backend = system_info.get("backend")
    vendor = (system_info.get("gpu_vendor") or "").lower()
    gguf_accelerator = system_info.get("gguf_accelerator")

    try:
        platform_subdir = detect_cuda_platform_subdir()
        platform_supported = True
        unsupported_reason = None
    except CudaRuntimeError as exc:
        platform_subdir = None
        platform_supported = False
        unsupported_reason = str(exc)

    installed = is_cuda_runtime_installed()
    summary = cuda_installed_summary() if installed else None

    # Hardware-side eligibility — we still let non-NVIDIA users download if
    # they ask, but applicability drives whether the UI surfaces the chip
    # button. The button only shows when GGUF is the active backend, the GPU
    # is NVIDIA, no CUDA DLL is installed yet, and the platform has a bundle.
    if not platform_supported:
        applicable = False
        reason = unsupported_reason
    elif installed:
        applicable = False
        reason = "CUDA runtime already installed"
    elif backend != "gguf":
        applicable = False
        reason = "Active backend is not GGUF; CUDA upgrade only applies to GGUF runtime"
    elif vendor != "nvidia":
        applicable = False
        reason = "GPU vendor is not NVIDIA; CUDA acceleration would not help"
    elif gguf_accelerator == "cuda":
        applicable = False
        reason = "GGUF runtime already reports CUDA acceleration"
    else:
        applicable = True
        reason = None

    return {
        "success": True,
        "applicable": applicable,
        "installed": installed,
        "platform_supported": platform_supported,
        "platform_subdir": platform_subdir,
        "reason": reason,
        "installed_summary": summary,
        "requires_restart": _CUDA_UPGRADE_PENDING_RESTART,
        "gpu_vendor": vendor,
        "current_accelerator": gguf_accelerator,
    }


@tts_bp.route("/api/cuda-upgrade/status")
def cuda_upgrade_status():
    return jsonify(_cuda_upgrade_status_payload())


@tts_bp.route("/api/cuda-upgrade/download", methods=["POST"])
def cuda_upgrade_download():
    # Single-flight: refuse concurrent downloads. The lock is non-blocking so
    # a second request gets an immediate 409 JSON rather than tying up a worker.
    if not _CUDA_INSTALL_LOCK.acquire(blocking=False):
        return _json_error("CUDA runtime download already in progress.", 409)

    try:
        platform_subdir = detect_cuda_platform_subdir()
    except CudaRuntimeError as exc:
        _CUDA_INSTALL_LOCK.release()
        return _json_error(str(exc), 400)

    def generate():
        global _CUDA_UPGRADE_PENDING_RESTART
        try:
            for event in download_cuda_runtime_streaming(platform_subdir=platform_subdir):
                if event.get("status") == "done":
                    _CUDA_UPGRADE_PENDING_RESTART = True
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("status") in {"done", "error"}:
                    break
        except Exception as exc:  # pragma: no cover - runtime safety
            yield f"data: {json.dumps({'status': 'error', 'error': str(exc)})}\n\n"
        finally:
            _CUDA_INSTALL_LOCK.release()

    return Response(stream_with_context(generate()), content_type="text/event-stream")


@tts_bp.route("/api/benchmark", methods=["POST"])
def run_benchmark():
    global _BENCHMARK_FUTURE

    data = request.json or {}
    voice = data.get("voice")
    instruct = (data.get("instruct") or "").strip()

    with _BENCHMARK_LOCK:
        if _BENCHMARK_FUTURE is not None and not _BENCHMARK_FUTURE.done():
            return _json_error("测速正在进行，请稍候。", 409)
        future = _BENCHMARK_EXECUTOR.submit(_benchmark_worker, voice, instruct)
        _BENCHMARK_FUTURE = future
        future.add_done_callback(_clear_benchmark_future)

    try:
        return jsonify(future.result(timeout=BENCHMARK_TIMEOUT_SECONDS))
    except TimeoutError:
        return _json_error("测速超时，请稍后再试。", 408)
    except LocalTTSBusyError as exc:
        return _json_error(str(exc), 409)
    except LocalTTSError as exc:
        return _json_error(str(exc), 500)
    except Exception as exc:  # pragma: no cover - runtime safety
        return _json_error(f"测速失败: {exc}", 500)


@tts_bp.route("/api/estimate", methods=["POST"])
def estimate_synthesis_time():
    data = request.json or {}
    text = data.get("text", "") or ""
    benchmark = data.get("benchmark")
    include_references = bool(data.get("include_references"))
    synthesis_mode = (data.get("synthesis_mode") or "auto").strip().lower()
    if synthesis_mode not in VALID_SYNTHESIS_MODES:
        synthesis_mode = "auto"
    char_count = len(text.strip())
    chunk_count = _kernel_stream_chunk_count(text)
    group_count = service.count_long_groups(text) if synthesis_mode == "long" else None
    estimate = _estimate_from_benchmark(
        char_count,
        benchmark,
        chunk_count=chunk_count,
        synthesis_mode=synthesis_mode,
    )

    references = []
    if include_references:
        for count in REFERENCE_CHAR_COUNTS:
            references.append(
                {
                    "char_count": count,
                    "estimate": _estimate_from_benchmark(
                        count,
                        benchmark,
                        synthesis_mode="reference",
                    ),
                }
            )

    system_info = _system_info_payload()
    return jsonify(
        {
            "success": True,
            "char_count": char_count,
            "chunk_count": chunk_count,
            "group_count": group_count,
            "estimate": estimate,
            "references": references,
            "has_benchmark": estimate is not None,
            "is_rough_estimate": True,
            "synthesis_mode": synthesis_mode,
            "backend": system_info["backend"],
            "model_default": system_info["model_default"],
            "is_cpu_mode": system_info["is_cpu_mode"],
        }
    )


@tts_bp.route("/api/synthesize", methods=["POST"])
def synthesize():
    data = request.json or {}
    text = data.get("text", "").strip()
    voice = data.get("voice")
    instruct = (data.get("instruct") or "").strip()

    if not text:
        return _json_error("请输入文本", 400)
    if len(text) > 50000:
        return _json_error("文本过长，最多50000个字符。", 400)

    try:
        filename = service.synthesize_text(text, voice, instruct=instruct)
    except LocalTTSBusyError as exc:
        return _json_error(str(exc), 409)
    except LocalTTSError as exc:
        return _json_error(str(exc), 500)
    except Exception as exc:  # pragma: no cover - runtime safety
        return _json_error(f"合成失败: {exc}", 500)

    return jsonify({"success": True, "audio_url": f"/static/audio/{filename}", "filename": filename})


@tts_bp.route("/api/synthesize-long", methods=["POST"])
def synthesize_long():
    data = request.json or {}
    text = data.get("text", "").strip()
    voice = data.get("voice")
    instruct = (data.get("instruct") or "").strip()

    if not text:
        return _json_error("请输入文本", 400)
    if len(text) > 50000:
        return _json_error("文本过长，最多50000个字符。", 400)

    try:
        event_stream = service.synthesize_long_stream(text, voice, instruct=instruct)
    except LocalTTSBusyError as exc:
        return _json_error(str(exc), 409)

    def generate():
        try:
            for event in event_stream:
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("status") in {"done", "error"}:
                    break
        finally:
            event_stream.close()

    return Response(stream_with_context(generate()), content_type="text/event-stream")


@tts_bp.route("/api/synthesize-sentences", methods=["POST"])
def synthesize_sentences():
    data = request.json or {}
    text = data.get("text", "").strip()
    voice = data.get("voice")
    instruct = (data.get("instruct") or "").strip()
    max_words = data.get("max_words", 15)
    newline_hard = data.get("newline_hard", True)

    if not text:
        return _json_error("请输入文本", 400)
    if len(text) > 5000:
        return _json_error("跟读模式文本过长，最多5000个字符。", 400)

    chunks = split_into_chunks(text, max_words=max_words, newline_hard=newline_hard)
    if not chunks:
        return _json_error("未找到文本块", 400)

    # Acquire the engine generator synchronously so a busy/lock contention
    # turns into a plain 409 JSON response instead of an opened SSE stream.
    try:
        event_stream = service.synthesize_sentences_stream(chunks, voice, instruct=instruct)
    except LocalTTSBusyError as exc:
        return _json_error(str(exc), 409)

    def generate():
        try:
            for event in event_stream:
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("status") in {"done", "error"}:
                    break
        finally:
            # Explicit close guarantees the engine generator's finally block
            # fires before the HTTP response is torn down, releasing _busy_lock
            # even if the client disconnects mid-stream.
            event_stream.close()

    return Response(stream_with_context(generate()), content_type="text/event-stream")


@tts_bp.route("/api/convert", methods=["POST"])
def convert_audio():
    data = request.get_json() or {}
    if "filename" not in data or "format" not in data:
        return jsonify({"error": "Missing filename or format"}), 400

    source_filename = data["filename"]
    target_format = data["format"].lower().strip()
    if target_format not in ALLOWED_FORMATS:
        return jsonify({"error": f"Unsupported format: {target_format}"}), 400

    safe_source_filename = secure_filename(source_filename)
    if not safe_source_filename or safe_source_filename != source_filename:
        return jsonify({"error": "Invalid filename"}), 400

    source_path = (OUTPUT_DIR / safe_source_filename).resolve()
    output_root = OUTPUT_DIR.resolve()
    if output_root not in source_path.parents:
        return jsonify({"error": "Invalid filename"}), 400
    if not source_path.exists():
        return jsonify({"error": "Source file not found"}), 404

    target_filename = source_path.stem + f".{target_format}"
    target_path = (OUTPUT_DIR / target_filename).resolve()
    if output_root not in target_path.parents:
        return jsonify({"error": "Invalid filename"}), 400

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    try:
        subprocess.run(
            [ffmpeg_exe, "-y", "-i", str(source_path.absolute()), str(target_path.absolute())],
            check=True,
            capture_output=True,
        )
        return jsonify({"success": True, "filename": target_filename})
    except subprocess.CalledProcessError:
        return jsonify({"error": "Conversion failed"}), 500


@tts_bp.route("/api/download/<filename>")
def download_audio(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)
