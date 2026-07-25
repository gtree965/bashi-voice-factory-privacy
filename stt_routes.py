import copy
import os
import uuid
import json
import time
import threading
import urllib.parse
from pathlib import Path
from flask import Blueprint, request, jsonify, Response, stream_with_context, send_file
from werkzeug.utils import secure_filename

from logging_setup import get_logger
from model_manager import ModelManager
from speaker_diarization import SpeakerDiarizer, SpeakerTurn, assign_speakers_to_segments, speaker_label
from stt_engine_factory import create_stt_engine
from stt_subtitles import (
    _format_segment_text,
    _format_speaker_prefix,
    _has_speaker,
    _is_cjk,
    _smooth_join,
    fix_timestamp_overlaps,
    format_timestamp,
    merge_short_segments,
    normalize_subtitle_text,
)
from utils import extract_audio_wav

logger = get_logger(__name__)
stt_bp = Blueprint("stt", __name__, url_prefix="/api/stt")

# Ensure directories exist
UPLOAD_DIR = Path("static/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR = Path("models")
MODELS_DIR.mkdir(parents=True, exist_ok=True)
METRICS_DIR = Path(".stt_metrics")
METRICS_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_BYTES = int(os.environ.get("BASHI_STT_MAX_UPLOAD_MB", "2048")) * 1024 * 1024

model_manager = ModelManager(MODELS_DIR)

# Global state
stt_jobs = {}
stt_jobs_lock = threading.Lock()
engine_instance = None
current_engine_model_id = None
engine_lock = threading.Lock()
_engine_ref_count = 0  # tracks active transcriptions using the engine
_job_active = False    # set at request admission, cleared when worker finishes

# Job cleanup: auto-expire jobs older than 24 hours
JOB_MAX_AGE_SEC = 24 * 60 * 60

def cleanup_expired_jobs():
    """Remove jobs older than JOB_MAX_AGE_SEC from memory."""
    now = time.time()
    with stt_jobs_lock:
        expired = [jid for jid, job in stt_jobs.items()
                   if now - job.get("created_at", now) > JOB_MAX_AGE_SEC]
        for jid in expired:
            del stt_jobs[jid]
    if expired:
        logger.info("[STT] Cleaned up %s expired job(s)", len(expired))

def _cleanup_timer():
    """Run cleanup every hour in a background thread."""
    while True:
        time.sleep(3600)
        try:
            cleanup_expired_jobs()
        except Exception:
            pass

_cleanup_thread = threading.Thread(target=_cleanup_timer, daemon=True)
_cleanup_thread.start()

def acquire_engine(model_id=None):
    """Get engine for the given model and increment its ref count.

    The caller MUST call release_engine() when done to allow future
    model swaps.  Only one transcription job may run at a time because
    sherpa_onnx's OfflineRecognizer is not guaranteed thread-safe for
    concurrent decode_stream() calls on a shared instance.
    """
    global engine_instance, current_engine_model_id, _engine_ref_count
    with engine_lock:
        if _engine_ref_count > 0:
            raise RuntimeError(
                "A transcription is already in progress. "
                "Please wait for it to finish before starting another."
            )

        if engine_instance is not None and current_engine_model_id != model_id:
            # Swap models: unload current to free up RAM
            logger.info(
                "[STT] Swapping active model from %s to %s",
                current_engine_model_id,
                model_id,
            )
            try:
                engine_instance.cleanup()
            except Exception:
                pass
            engine_instance = None
            current_engine_model_id = None

        if engine_instance is None:
            # If no model requested, use default
            if not model_id:
                for m in model_manager.list_installed():
                    if m.get("is_default"):
                        model_id = m["id"]
                        break
                if not model_id:
                    # Still fallback to first installed
                    installed = model_manager.list_installed()
                    if installed:
                        model_id = installed[0]["id"]

            if not model_id:
                return None  # No models installed

            model_dir = model_manager.get_model_dir(model_id)
            if not model_dir:
                return None

            # Instantiate correct engine based on registry meta
            meta = next((m for m in model_manager.list_installed() if m["id"] == model_id), None)
            if not meta:
                return None

            try:
                engine_instance = create_stt_engine(meta, model_dir)
                engine_instance.load_model()
                current_engine_model_id = model_id
            except Exception as e:
                engine_instance = None
                current_engine_model_id = None
                logger.exception("Failed to load engine for %s: %s", model_id, e)
                return None

        _engine_ref_count += 1
        return engine_instance


def release_engine():
    """Decrement the engine ref count, allowing future model swaps."""
    global _engine_ref_count
    with engine_lock:
        _engine_ref_count = max(0, _engine_ref_count - 1)

@stt_bp.route("/models", methods=["GET"])
def list_models():
    return jsonify({
        "installed": model_manager.list_installed(),
        "available": model_manager.list_available(),
        "speaker_diarization": model_manager.get_speaker_diarization_status(),
    })

@stt_bp.route("/download-model", methods=["POST"])
def download_model():
    data = request.json or {}
    model_id = data.get("model_id")
    use_mirror = data.get("use_mirror", True)
    
    if not model_id:
        return jsonify({"error": "model_id required"}), 400

    def generate():
        try:
            for event in model_manager.download_model(model_id, use_mirror=use_mirror):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"

    return Response(stream_with_context(generate()), content_type='text/event-stream')


@stt_bp.route("/download-speaker-model", methods=["POST"])
def download_speaker_model():
    data = request.json or {}
    use_mirror = data.get("use_mirror", True)

    def generate():
        try:
            for event in model_manager.download_speaker_diarization_model(use_mirror=use_mirror):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"

    return Response(stream_with_context(generate()), content_type='text/event-stream')


def _parse_bool(value) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_speaker_count(value) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return -1
    if count < 1:
        return -1
    return min(count, 12)


def _speaker_turn_to_dict(turn: SpeakerTurn) -> dict:
    return {
        "start": turn.start,
        "end": turn.end,
        "speaker": turn.speaker,
        "speaker_label": speaker_label(turn.speaker),
    }


def _parse_speaker_preset(value) -> str | None:
    if value is None:
        return None
    preset = str(value).strip().lower()
    if preset not in {"accurate", "balanced", "fast"}:
        return None
    return preset


def _dict_or_empty(value) -> dict:
    return value if isinstance(value, dict) else {}


def _write_job_metrics(job_id: str) -> None:
    """Persist timing metrics outside launch_log.txt.

    run_portable.ps1 redirects app stderr to launch_log.txt for the whole app
    lifetime.  On Windows that file can be locked by the parent cmd process, so
    appending diagnostics there is best-effort only.  This JSON file is the
    durable source for post-run Speaker ID analysis.
    """
    try:
        with stt_jobs_lock:
            job = stt_jobs.get(job_id)
            if not job:
                return
            job = dict(job)
        payload = {
            "job_id": job_id,
            "filename": job.get("filename"),
            "model_id": job.get("model_id"),
            "status": job.get("status"),
            "segment_count": len(job.get("segments") or []),
            "speaker_id_enabled": job.get("speaker_id_enabled"),
            "speaker_count": job.get("speaker_count"),
            "speaker_preset": job.get("speaker_preset"),
            "speaker_turn_count": len(job.get("speaker_turns") or []),
            "speaker_error": job.get("speaker_error"),
            "timing": _dict_or_empty(job.get("timing")),
            "speaker_metrics": _dict_or_empty(job.get("speaker_metrics")),
            "created_at": job.get("created_at"),
            "written_at": time.time(),
        }
        dest = METRICS_DIR / f"{job_id}.json"
        tmp = METRICS_DIR / f"{job_id}.json.tmp"
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(dest)
    except Exception as e:
        logger.warning("[STT metrics] job=%s failed to write metrics: %s", job_id, e)


def _process_transcription(
    job_id: str,
    file_path: Path,
    filename: str,
    language: str,
    model_id: str,
    speaker_id_enabled: bool = False,
    speaker_count: int = -1,
    speaker_preset: str | None = None,
):
    """Background thread to process audio extraction and transcription."""
    with stt_jobs_lock:
        stt_jobs[job_id]["status"] = "extracting_audio"
        stt_jobs[job_id].setdefault("timing", {})
        stt_jobs[job_id].setdefault("speaker_metrics", {})
    wav_path = UPLOAD_DIR / f"{job_id}.wav"
    job_started_at = time.monotonic()
    
    try:
        # Step 1: Extract Audio
        step_started_at = time.monotonic()
        extract_audio_wav(file_path, wav_path)
        audio_extract_seconds = round(time.monotonic() - step_started_at, 3)
        with stt_jobs_lock:
            stt_jobs[job_id]["timing"]["audio_extract_seconds"] = audio_extract_seconds
        
        # Step 2: Ensure Engine is ready (also increments ref count)
        with stt_jobs_lock:
            stt_jobs[job_id]["status"] = "loading_model"
        step_started_at = time.monotonic()
        engine = acquire_engine(model_id)
        if not engine:
            raise RuntimeError("Engine could not be loaded. Please ensure models are installed.")
        model_load_seconds = round(time.monotonic() - step_started_at, 3)
        with stt_jobs_lock:
            stt_jobs[job_id]["timing"]["model_load_seconds"] = model_load_seconds

        # Step 3: Transcribe
        try:
            with stt_jobs_lock:
                stt_jobs[job_id]["status"] = "transcribing"
            step_started_at = time.monotonic()
            for segment in engine.transcribe_stream(wav_path, language=language):
                seg_dict = {
                    "index": segment.index,
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text
                }
                with stt_jobs_lock:
                    stt_jobs[job_id]["segments"].append(seg_dict)
            asr_seconds = round(time.monotonic() - step_started_at, 3)
            with stt_jobs_lock:
                stt_jobs[job_id]["timing"]["asr_seconds"] = asr_seconds
        finally:
            release_engine()

        # Step 4: Optional speaker diarization
        if speaker_id_enabled:
            with stt_jobs_lock:
                stt_jobs[job_id]["status"] = "diarizing"
                stt_jobs[job_id]["speaker_progress"] = 0.0
            diarizer = None
            try:
                def progress_callback(num_processed_chunk: int, num_total_chunks: int) -> int:
                    if num_total_chunks:
                        speaker_progress = round(
                            (num_processed_chunk / num_total_chunks) * 100,
                            1,
                        )
                        with stt_jobs_lock:
                            stt_jobs[job_id]["speaker_progress"] = speaker_progress
                    return 0

                diarizer = SpeakerDiarizer(MODELS_DIR, preset=speaker_preset)
                turns = diarizer.diarize(
                    wav_path,
                    num_speakers=speaker_count,
                    progress_callback=progress_callback,
                )
                with stt_jobs_lock:
                    segments = copy.deepcopy(stt_jobs[job_id]["segments"])
                speaker_turns = [_speaker_turn_to_dict(turn) for turn in turns]
                assigned_segments = assign_speakers_to_segments(
                    segments,
                    turns,
                )
                speaker_metrics = diarizer.last_metrics
                with stt_jobs_lock:
                    stt_jobs[job_id]["speaker_metrics"] = speaker_metrics
                    stt_jobs[job_id]["speaker_turns"] = speaker_turns
                    stt_jobs[job_id]["segments"] = assigned_segments
                    stt_jobs[job_id]["speaker_progress"] = 100.0
                logger.info(
                    "[STT Speaker ID] "
                    f"job={job_id} preset={diarizer.last_metrics.get('preset')} "
                    f"threads={diarizer.last_metrics.get('num_threads')} "
                    f"speakers={speaker_count} turns={len(turns)} "
                    f"total={diarizer.last_metrics.get('total_seconds')}s "
                    f"pre_callback={diarizer.last_metrics.get('pre_callback_seconds')}s "
                    f"callback={diarizer.last_metrics.get('callback_seconds')}s "
                    f"post_callback={diarizer.last_metrics.get('post_callback_seconds')}s "
                    f"rtf={diarizer.last_metrics.get('rtf')}"
                )
            except Exception as e:
                # Speaker ID is an optional enhancement.  A diarization failure
                # must not discard a successful transcript, especially for long
                # meeting recordings where diarization is the riskiest step.
                speaker_error = str(e)
                speaker_metrics = None
                if diarizer is not None:
                    speaker_metrics = _dict_or_empty(getattr(diarizer, "last_metrics", {}))
                with stt_jobs_lock:
                    stt_jobs[job_id]["speaker_error"] = speaker_error
                    stt_jobs[job_id]["speaker_progress"] = None
                    if speaker_metrics is not None:
                        stt_jobs[job_id]["speaker_metrics"] = speaker_metrics
                logger.exception("[STT Speaker ID] job=%s failed: %s", job_id, e)

        # Step 5: Done
        total_job_seconds = round(time.monotonic() - job_started_at, 3)
        with stt_jobs_lock:
            stt_jobs[job_id]["timing"]["total_job_seconds"] = total_job_seconds
            stt_jobs[job_id]["status"] = "done"
            job = stt_jobs[job_id]
            segment_count = len(job["segments"])
            timing = dict(job["timing"])
        _write_job_metrics(job_id)
        logger.info(
            "[STT] "
            f"job={job_id} status=done segments={segment_count} "
            f"extract={timing.get('audio_extract_seconds')}s "
            f"load={timing.get('model_load_seconds')}s "
            f"asr={timing.get('asr_seconds')}s "
            f"total={timing.get('total_job_seconds')}s"
        )
        
    except Exception as e:
        error_message = str(e)
        with stt_jobs_lock:
            stt_jobs[job_id]["status"] = "error"
            stt_jobs[job_id]["error"] = error_message
    finally:
        # Release the job slot so the next transcription can be accepted
        global _job_active
        with engine_lock:
            _job_active = False
        # Cleanup temp uploaded file (original media) and extracted WAV
        if file_path.exists():
            file_path.unlink()
        if wav_path.exists():
            wav_path.unlink(missing_ok=True)

@stt_bp.route("/transcribe", methods=["POST"])
def transcribe():
    global _job_active

    # Reserve the slot atomically — reject before saving file to disk
    with engine_lock:
        if _job_active:
            return jsonify({"error": "A transcription is already in progress. "
                            "Please wait for it to finish."}), 429
        _job_active = True

    worker_started = False
    job_id = None
    file_path = None

    try:
        if "file" not in request.files:
            return jsonify({"error": "No file part"}), 400

        if request.content_length and request.content_length > MAX_UPLOAD_BYTES:
            max_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
            return jsonify({"error": f"File too large. Maximum upload size is {max_mb} MB."}), 413

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No selected file"}), 400

        language = request.form.get("language", "auto")
        model_id = request.form.get("model_id")
        speaker_id_enabled = _parse_bool(request.form.get("speaker_id"))
        if os.environ.get("BASHI_SPEAKER_ID_UI") != "1":
            speaker_id_enabled = False
        speaker_count = _parse_speaker_count(request.form.get("speaker_count"))
        speaker_preset = _parse_speaker_preset(request.form.get("speaker_preset"))

        if speaker_id_enabled and not model_manager.is_speaker_diarization_complete():
            return jsonify({
                "error": "Speaker ID model is not downloaded. Download it from the STT panel first."
            }), 400

        job_id = uuid.uuid4().hex
        safe_filename = secure_filename(file.filename) or f"upload_{job_id}.bin"
        file_path = UPLOAD_DIR / f"{job_id}_{safe_filename}"
        file.save(str(file_path))

        created_at = time.time()
        with stt_jobs_lock:
            stt_jobs[job_id] = {
                "job_id": job_id,
                "filename": file.filename,
                "model_id": model_id,
                "status": "pending",
                "segments": [],
                "speaker_id_enabled": speaker_id_enabled,
                "speaker_count": speaker_count,
                "speaker_preset": speaker_preset,
                "speaker_turns": [],
                "speaker_progress": None,
                "speaker_error": None,
                "speaker_metrics": {},
                "timing": {},
                "error": None,
                "created_at": created_at,
            }

        # Start background processing (_job_active is cleared in the worker's finally)
        thread = threading.Thread(
            target=_process_transcription,
            args=(
                job_id,
                file_path,
                file.filename,
                language,
                model_id,
                speaker_id_enabled,
                speaker_count,
                speaker_preset,
            ),
            daemon=True,
        )
        thread.start()
        worker_started = True

        return jsonify({"success": True, "job_id": job_id})

    finally:
        if not worker_started:
            with engine_lock:
                _job_active = False
            if job_id is not None:
                with stt_jobs_lock:
                    stt_jobs.pop(job_id, None)
            if file_path is not None and file_path.exists():
                file_path.unlink(missing_ok=True)

@stt_bp.route("/progress/<job_id>", methods=["GET"])
def get_progress_sse(job_id):
    def generate():
        last_index = 0
        while True:
            with stt_jobs_lock:
                job = stt_jobs.get(job_id)
                if job:
                    status = job["status"]
                    new_segments = job["segments"][last_index:]
                    error = job.get("error")
                    speaker_progress = job.get("speaker_progress")
                    speaker_error = job.get("speaker_error")
                    seg_total = len(job["segments"])
            if not job:
                yield f"data: {json.dumps({'status': 'error', 'error': 'job not found'})}\n\n"
                break

            # Send new segments only
            if new_segments or status in ["error", "done", "extracting_audio", "loading_model", "diarizing"]:
                event_data = {
                    "status": status,
                    "new_segments": new_segments
                }
                if error:
                    event_data["error"] = error
                if speaker_progress is not None:
                    event_data["speaker_progress"] = speaker_progress
                if speaker_error:
                    event_data["speaker_error"] = speaker_error
                    
                yield f"data: {json.dumps(event_data)}\n\n"
                last_index = seg_total
                
            if status in ["done", "error"]:
                break

            time.sleep(0.5)

    return Response(stream_with_context(generate()), content_type='text/event-stream')

@stt_bp.route("/result/<job_id>", methods=["GET"])
def get_result(job_id):
    with stt_jobs_lock:
        job = stt_jobs.get(job_id)
        if job:
            payload = copy.deepcopy(job)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(payload)

@stt_bp.route("/export/<job_id>", methods=["GET"])
def export_result(job_id):
    format_type = request.args.get("format", "txt")
    ui_lang = request.args.get("lang", "en")
    with stt_jobs_lock:
        job = stt_jobs.get(job_id)
        if job:
            job = copy.deepcopy(job)

    if not job or job["status"] != "done":
        return jsonify({"error": "Job not found or not finished"}), 404

    segments = job["segments"]
    include_speakers = bool(job.get("speaker_id_enabled"))
    # Merge short fragments for subtitle formats — both Parakeet (English,
    # many tiny VAD segments) and SenseVoice (Chinese, standalone punctuation
    # fragments like 。) benefit from merging into reader-friendly cards.
    if format_type in ("srt", "vtt"):
        segments = merge_short_segments(segments)
    segments = fix_timestamp_overlaps(segments)
    filename_base = Path(job["filename"]).stem
    suffix = "转写" if ui_lang == "zh" else "transcription"

    if format_type == "txt":
        if include_speakers:
            content = "\n".join(_format_segment_text(seg, ui_lang=ui_lang) for seg in segments)
        else:
            content = "\n".join(seg["text"] for seg in segments)
        mimetype = "text/plain"
        ext = "txt"
    elif format_type == "srt":
        lines = []
        subtitle_segments = []
        for seg in segments:
            text = normalize_subtitle_text(seg["text"])
            if text:
                subtitle_segments.append((seg, _format_segment_text(seg, text=text, ui_lang=ui_lang) if include_speakers else text))
        for i, (seg, text) in enumerate(subtitle_segments, 1):
            start = format_timestamp(seg["start"], ",")
            end = format_timestamp(seg["end"], ",")
            lines.append(f"{i}\n{start} --> {end}\n{text}\n")
        content = "\n".join(lines)
        mimetype = "application/x-subrip"
        ext = "srt"
    elif format_type == "vtt":
        lines = ["WEBVTT\n"]
        for seg in segments:
            text = normalize_subtitle_text(seg["text"])
            if not text:
                continue
            if include_speakers:
                text = _format_segment_text(seg, text=text, ui_lang=ui_lang)
            start = format_timestamp(seg["start"], ".")
            end = format_timestamp(seg["end"], ".")
            lines.append(f"{start} --> {end}\n{text}\n")
        content = "\n".join(lines)
        mimetype = "text/vtt"
        ext = "vtt"
    else:
        return jsonify({"error": "Unsupported format"}), 400

    export_filename = f"{filename_base}_{suffix}.{ext}"
    response = Response(content, mimetype=mimetype)
    response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{urllib.parse.quote(export_filename)}"
    response.headers["Content-Type"] = f"{mimetype}; charset=utf-8"
    return response
