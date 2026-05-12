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

from backend_probe import (
    MODEL_DEFAULT,
    detect_hardware_profile,
    get_probe_cache_path,
    load_probe_cache,
)
from local_tts_engine import OUTPUT_DIR, LocalTTSBusyError, LocalTTSError, service


tts_bp = Blueprint("tts", __name__)
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
BENCHMARK_TIMEOUT_SECONDS = 180
REFERENCE_CHAR_COUNTS = (1000, 5000)
VALID_SYNTHESIS_MODES = {"auto", "single", "long", "sentence", "reference"}
_BENCHMARK_EXECUTOR = ThreadPoolExecutor(max_workers=1)
_BENCHMARK_LOCK = threading.RLock()
_BENCHMARK_FUTURE = None
_SYSTEM_INFO_LOCK = threading.RLock()
_SYSTEM_INFO_CACHE = None


def split_long_sentence(sentence: str, limit: int, is_cjk: bool = False) -> list:
    def measure(text: str):
        return len(text) if is_cjk else len(text.split())

    def split_recursively(part: str):
        if measure(part) <= limit:
            return [part]
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

    if is_cjk:
        return [sentence[i : i + limit] for i in range(0, len(sentence), limit)]

    words = sentence.split()
    return [" ".join(words[i : i + limit]) for i in range(0, len(words), limit)]


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

    if device_identity == "unknown" or vendor == "unknown":
        try:
            hardware = detect_hardware_profile()
            device_identity = hardware.gpu_device_identity or device_identity
            vendor = hardware.normalized_vendor or vendor
            has_cuda = hardware.has_cuda
            has_mps = hardware.has_mps
        except Exception:
            has_cuda = False
            has_mps = False
    else:
        has_cuda = vendor == "nvidia"
        has_mps = vendor == "apple"

    if backend == "gguf":
        if vendor == "amd":
            label_en = "AMD GPU acceleration"
            label_zh = "AMD 显卡加速"
        elif vendor == "intel":
            label_en = "Intel GPU acceleration"
            label_zh = "Intel 显卡加速"
        else:
            label_en = "GGUF GPU acceleration"
            label_zh = "GGUF 显卡加速"
        detail_en = "Vulkan + DirectML"
        detail_zh = "Vulkan + DirectML"
        acceleration_type = "vulkan_dml"
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


@tts_bp.route("/api/voices")
def get_voices():
    return jsonify(service.get_voice_catalog())


@tts_bp.route("/api/system-info")
def get_system_info():
    return jsonify(_system_info_payload())


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

    source_path = OUTPUT_DIR / source_filename
    if not source_path.exists():
        return jsonify({"error": "Source file not found"}), 404

    target_filename = source_path.stem + f".{target_format}"
    target_path = OUTPUT_DIR / target_filename

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
