import gc
import json
import os
import queue
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import numpy as np

from audio_encoding import peak_normalize_audio, write_mp3
from local_voice_catalog import build_voice_catalog


APP_ROOT = Path(__file__).resolve().parent
KERNEL_DIR = APP_ROOT / "bashi_tts_kernel"
DEFAULT_MODEL_DIR = KERNEL_DIR / "models" / "Qwen3-TTS-12Hz-1.7B-CustomVoice"
MODEL_DIR = Path(os.environ.get("LOCAL_TTS_PYTORCH_MODEL_DIR", DEFAULT_MODEL_DIR)).resolve()
SPEAKERS_PATH = KERNEL_DIR / "speakers.json"
OUTPUT_DIR = APP_ROOT / "static" / "audio"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

from bashi_tts_kernel.bashi_tts_core import BashiTTSEngine  # noqa: E402


class LocalTTSError(RuntimeError):
    pass


class LocalTTSBusyError(LocalTTSError):
    pass


class LocalTTSService:
    def __init__(self):
        self._engine = None
        self._state = "unloaded"
        self._state_lock = threading.RLock()
        self._busy_lock = threading.Lock()
        self._load_error = None
        self._speakers = self._load_speakers()

    def _load_speakers(self) -> dict:
        if not SPEAKERS_PATH.exists():
            raise LocalTTSError(f"Missing speakers registry: {SPEAKERS_PATH}")

        with SPEAKERS_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        speakers = data.get("speakers", [])
        if not speakers:
            raise LocalTTSError("speakers.json does not contain any speakers")

        by_id = {}
        alias_to_id = {}
        for speaker in speakers:
            speaker_id = speaker["id"]
            by_id[speaker_id] = speaker
            alias_to_id[speaker_id.lower()] = speaker_id
            for alias in speaker.get("aliases", []):
                alias_to_id[alias.lower()] = speaker_id

        return {
            "default_speaker": data.get("default_speaker", speakers[0]["id"]),
            "by_id": by_id,
            "alias_to_id": alias_to_id,
        }

    def get_voice_catalog(self) -> dict:
        return build_voice_catalog(self._speakers)

    def _ensure_loaded(self):
        with self._state_lock:
            if self._state == "ready" and self._engine is not None:
                return self._engine
            if self._state == "loading":
                raise LocalTTSError("Local TTS engine is still loading")
            if self._state == "failed":
                raise LocalTTSError(f"Local TTS engine failed to initialize: {self._load_error}")

            self._state = "loading"
            try:
                self._engine = BashiTTSEngine(model_dir=str(MODEL_DIR))
                self._state = "ready"
                self._load_error = None
            except Exception as exc:  # pragma: no cover - defensive runtime path
                self._state = "failed"
                self._load_error = str(exc)
                raise
            return self._engine

    def warmup(self):
        self._ensure_loaded()

    def shutdown(self):
        with self._state_lock:
            engine = self._engine
            self._engine = None
            self._state = "unloaded"
            self._load_error = None

        if engine is None:
            return

        try:
            if hasattr(engine, "model"):
                engine.model = None
        finally:
            del engine

        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

        gc.collect()

    def resolve_speaker(self, requested_id: str | None) -> dict:
        speaker_id = requested_id or self._speakers["default_speaker"]
        canonical_id = self._speakers["alias_to_id"].get(speaker_id.lower())
        if canonical_id is None:
            raise LocalTTSError(f"Unknown local speaker: {speaker_id}")
        return self._speakers["by_id"][canonical_id]

    def resolve_language(self, speaker: dict) -> str:
        # The current kernel expects the model-facing language names used in the
        # upstream Qwen README, not a free-form "auto" token.
        language_map = {
            "zh": "Chinese",
            "en": "English",
            "ja": "Japanese",
            "ko": "Korean",
        }
        native_language = speaker.get("native_language", "zh")
        return language_map.get(native_language, "Chinese")

    def _write_mp3(self, audio: np.ndarray, sr: int, stem: str) -> str:
        return write_mp3(audio, sr, stem, OUTPUT_DIR)

    def _normalize_generated_audio(self, audio: np.ndarray) -> np.ndarray:
        return peak_normalize_audio(audio)

    def _generate_wav_no_lock(
        self,
        text: str,
        voice_id: str,
        instruct: str = "",
        progress_callback=None,
    ) -> tuple[np.ndarray, int]:
        engine = self._ensure_loaded()
        speaker = self.resolve_speaker(voice_id)
        language = self.resolve_language(speaker)
        chunks = []
        sample_rate = 24000

        for sample_rate, chunk in engine.generate_stream(
            text=text,
            speaker=speaker["model_name"],
            language=language,
            instruct=instruct,
            progress_callback=progress_callback,
        ):
            if chunk is not None and len(chunk) > 0:
                chunks.append(chunk)

        if not chunks:
            raise LocalTTSError("No audio chunks were produced")

        audio = self._normalize_generated_audio(np.concatenate(chunks).astype(np.float32))
        return audio, sample_rate

    def _generate_mp3_no_lock(
        self,
        text: str,
        voice_id: str,
        instruct: str = "",
        progress_callback=None,
    ) -> str:
        audio, sample_rate = self._generate_wav_no_lock(
            text,
            voice_id,
            instruct=instruct,
            progress_callback=progress_callback,
        )
        stem = uuid.uuid4().hex
        return self._write_mp3(audio, sample_rate, stem)

    def synthesize_text(
        self,
        text: str,
        voice_id: str,
        instruct: str = "",
        progress_callback=None,
    ) -> str:
        if not self._busy_lock.acquire(blocking=False):
            raise LocalTTSBusyError("Local TTS engine is busy with another request")
        try:
            return self._generate_mp3_no_lock(
                text,
                voice_id,
                instruct=instruct,
                progress_callback=progress_callback,
            )
        finally:
            self._busy_lock.release()

    def synthesize_sentences_stream(
        self, sentences: list[str], voice_id: str | None, instruct: str = ""
    ) -> Iterator[dict]:
        # Pre-filter so `total` in yielded events matches what is actually emitted.
        filtered = [s.strip() for s in sentences if s and s.strip()]

        if not filtered:
            def _empty() -> Iterator[dict]:
                yield {"status": "done", "total": 0}

            return _empty()

        # Synchronous busy check: raise before returning the generator so the
        # caller can translate it into a 409 without opening an SSE stream.
        if not self._busy_lock.acquire(blocking=False):
            raise LocalTTSBusyError("Local TTS engine is busy with another request")

        try:
            return self._iter_sentence_events(filtered, voice_id, instruct)
        except BaseException:
            self._busy_lock.release()
            raise

    def _iter_sentence_events(
        self, sentences: list[str], voice_id: str | None, instruct: str = ""
    ) -> Iterator[dict]:
        total = len(sentences)
        try:
            for index, sentence in enumerate(sentences):
                yield {
                    "status": "generating",
                    "index": index,
                    "total": total,
                    "text": sentence,
                }
                try:
                    filename = self._generate_mp3_no_lock(
                        sentence,
                        voice_id,
                        instruct=instruct,
                    )
                except Exception as exc:
                    yield {
                        "status": "error",
                        "index": index,
                        "total": total,
                        "error": str(exc),
                    }
                    return
                yield {
                    "status": "sentence_done",
                    "index": index,
                    "total": total,
                    "text": sentence,
                    "audio_url": f"/static/audio/{filename}",
                    "filename": filename,
                }
            yield {"status": "done", "total": total}
        finally:
            self._busy_lock.release()

    def synthesize_long_stream(
        self, text: str, voice_id: str | None, instruct: str = ""
    ) -> Iterator[dict]:
        # Threading model for long synthesis:
        #
        # - The calling thread (Flask request handler) acquires _busy_lock
        #   synchronously so concurrent requests get a 409 JSON response
        #   instead of opening a stalled SSE stream.
        # - A daemon worker thread runs the kernel, applies the 500ms
        #   throttle inside progress_callback, and puts events on a Queue.
        # - The main generator polls the queue (in the request thread) and
        #   yields events to SSE. This decouples SSE frame cadence from
        #   kernel audio-chunk cadence — without this split, progress
        #   events only flow when the kernel yields its next audio chunk,
        #   which can be 30+ seconds apart on long content.
        # - The worker's finally is the sole owner of lock release. Cross-
        #   thread release is intentional and requires threading.Lock (not
        #   RLock). The "kernel is free" moment only happens when the
        #   worker completes, regardless of whether the client is still
        #   connected.
        # - If the client disconnects, Flask closes our generator but the
        #   worker keeps running to kernel completion. The resulting MP3
        #   lands in static/audio/ with no one to fetch it. This is an
        #   intentional Phase 2 tradeoff; true cancellation is deferred.
        if not self._busy_lock.acquire(blocking=False):
            raise LocalTTSBusyError("Local TTS engine is busy with another request")

        try:
            event_queue: queue.Queue = queue.Queue()
            worker = threading.Thread(
                target=self._long_worker,
                args=(text, voice_id, instruct, event_queue),
                daemon=True,
            )
            worker.start()
        except BaseException:
            # If the worker never starts, its finally won't run, so we own
            # lock release on this path.
            self._busy_lock.release()
            raise

        return self._iter_long_from_queue(event_queue)

    def _long_worker(
        self,
        text: str,
        voice_id: str | None,
        instruct: str,
        event_queue: "queue.Queue[dict | None]",
    ) -> None:
        try:
            engine = self._ensure_loaded()
            speaker = self.resolve_speaker(voice_id)
            language = self.resolve_language(speaker)

            audio_chunks: list[np.ndarray] = []
            sample_rate = 24000
            # 500ms wall-clock throttle: caps the SSE emit rate for future-
            # proofing against denser callbacks, plus guarantees a first-real
            # frame and a final-tick frame so the UI always sees an early
            # signal and a terminal 100% tick.
            #
            # Note: the kernel's progress_callback only fires once per ~20-char
            # chunk (bashi_tts_kernel/bashi_tts_core.py, loop over
            # chunks_text). On CPU each chunk is tens of seconds of inference,
            # so today the throttle rarely engages and the observed frame
            # cadence is dominated by kernel chunk time, not this throttle.
            # The throttle exists so that if kernel progress ever gets denser
            # (GPU, sub-chunk hooks, etc.), we don't flood SSE without code
            # changes here.
            throttle_seconds = 0.5
            emitted_once = [False]
            last_emit = [0.0]

            def progress_callback(current: int, total: int, chunk_text: str):
                if total <= 0:
                    return
                now = time.monotonic()
                is_final = current >= total
                if not emitted_once[0] or is_final or (now - last_emit[0]) >= throttle_seconds:
                    event_queue.put(
                        {
                            "status": "generating",
                            "chunk": current,
                            "total": total,
                            "preview": chunk_text[:24],
                            "percent": int((current / total) * 100),
                        }
                    )
                    emitted_once[0] = True
                    last_emit[0] = now

            for sample_rate, audio_chunk in engine.generate_stream(
                text=text,
                speaker=speaker["model_name"],
                language=language,
                instruct=instruct,
                progress_callback=progress_callback,
            ):
                if audio_chunk is not None and len(audio_chunk) > 0:
                    audio_chunks.append(audio_chunk)

            if not audio_chunks:
                event_queue.put({"status": "error", "error": "No audio chunks were produced"})
                return

            event_queue.put({"status": "merging"})
            audio = self._normalize_generated_audio(np.concatenate(audio_chunks).astype(np.float32))
            stem = uuid.uuid4().hex
            filename = self._write_mp3(audio, sample_rate, stem)
            event_queue.put(
                {
                    "status": "done",
                    "audio_url_mp3": f"/static/audio/{filename}",
                    "filename_mp3": filename,
                }
            )
        except Exception as exc:
            event_queue.put({"status": "error", "error": str(exc)})
        finally:
            # Sentinel first: tells the main generator to stop polling
            # immediately. Put it before the lock release so even an
            # unexpected failure in release() can't strand the consumer.
            event_queue.put(None)
            self._busy_lock.release()

    def _iter_long_from_queue(
        self, event_queue: "queue.Queue[dict | None]"
    ) -> Iterator[dict]:
        # Blocking get() is safe: the worker's finally is guaranteed to put
        # the sentinel None, so we can't hang waiting for an event that
        # will never come (absent external process kill).
        while True:
            event = event_queue.get()
            if event is None:
                break
            yield event
            if event.get("status") in {"done", "error"}:
                break


service = LocalTTSService()
