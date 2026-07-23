import gc
import os
import queue
import re
import sys
import threading
import uuid
from collections.abc import Iterator
from pathlib import Path

import numpy as np

from audio_encoding import write_mp3
from local_tts_service_base import LocalTTSBusyError, LocalTTSError, LocalTTSServiceBase


APP_ROOT = Path(__file__).resolve().parent
REPO_ROOT = APP_ROOT.parent
DEFAULT_GGUF_DIR = (REPO_ROOT / "vulkan_backend_spike" / "Qwen3-TTS-GGUF").resolve()

GGUF_DIR = Path(os.environ.get("GGUF_TTS_DIR", DEFAULT_GGUF_DIR)).resolve()
GGUF_MODEL_DIR = Path(
    os.environ.get("GGUF_TTS_MODEL_DIR", GGUF_DIR / "model-custom")
).resolve()
GGUF_ONNX_PROVIDER = os.environ.get("GGUF_ONNX_PROVIDER", "DML")
GGUF_LLM_USE_GPU = os.environ.get("GGUF_LLM_USE_GPU", "1") != "0"
GGUF_VERBOSE = os.environ.get("GGUF_VERBOSE", "1") != "0"
GGUF_DECODER_READY_TIMEOUT = float(os.environ.get("GGUF_DECODER_READY_TIMEOUT", "60"))

OUTPUT_DIR = APP_ROOT / "static" / "audio"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

try:
    from bashi_tts_kernel.zh_normalizer_lite import normalize_chinese_text
except ImportError:  # pragma: no cover - startup misconfiguration fallback
    def normalize_chinese_text(text, options=None):
        return text


def _tail_gguf_runtime_log(max_lines: int = 12) -> str:
    log_path = GGUF_DIR / "log" / "latest.log"
    if not log_path.exists():
        return ""
    try:
        lines = [
            line.strip()
            for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()
        ]
    except Exception:
        return ""
    return " | ".join(lines[-max_lines:])


def _patch_decoder_ready_timeout(timeout_seconds: float) -> None:
    try:
        from qwen3_tts_gguf.inference.proxy import DecoderProxy  # noqa: WPS433
    except Exception:
        return

    current = DecoderProxy.wait_until_ready
    original = getattr(current, "_bashi_original_wait_until_ready", current)

    def wait_until_ready_with_bashi_timeout(self, timeout=10):
        effective_timeout = max(float(timeout or 0), float(timeout_seconds))
        return original(self, timeout=effective_timeout)

    wait_until_ready_with_bashi_timeout._bashi_original_wait_until_ready = original
    DecoderProxy.wait_until_ready = wait_until_ready_with_bashi_timeout


SAMPLE_RATE = 24000
LONG_CHUNK_TRIM_PEAK_RATIO = 0.02
LONG_CHUNK_TRIM_MIN_ABS = 0.002
LONG_CHUNK_TRIM_PADDING_MS = 180
LONG_CHUNK_JOIN_GAP_MS = 350
GGUF_LONG_MIN_CHARS = 30
GGUF_LONG_MAX_CHARS = 70
GGUF_LONG_MIN_CHUNKS = 3
TTS_QUOTE_TRANSLATION = str.maketrans({
    "“": "",
    "”": "",
    "‘": "",
    "’": "",
    "「": "",
    "」": "",
    "『": "",
    "』": "",
})
REFERENCE_ONLY_RE = re.compile(
    r"^[【\[\(（]?\s*[\u4e00-\u9fff]{0,4}\s*[\dA-Za-z]+[:：]\d+(?:[-–—]\d+)?\s*[】\]\)）]?$"
)


class LocalTTSService(LocalTTSServiceBase):
    def _ensure_loaded(self):
        with self._state_lock:
            if self._state == "ready" and self._engine is not None:
                return self._engine
            if self._state == "loading":
                raise LocalTTSError("GGUF TTS engine is still loading")
            if self._state == "failed":
                raise LocalTTSError(f"GGUF TTS engine failed to initialize: {self._load_error}")

            self._state = "loading"
            try:
                if str(GGUF_DIR) not in sys.path:
                    sys.path.insert(0, str(GGUF_DIR))

                from qwen3_tts_gguf.inference import TTSEngine  # noqa: WPS433

                _patch_decoder_ready_timeout(GGUF_DECODER_READY_TIMEOUT)
                self._engine = TTSEngine(
                    model_dir=str(GGUF_MODEL_DIR),
                    onnx_provider=GGUF_ONNX_PROVIDER,
                    llm_use_gpu=GGUF_LLM_USE_GPU,
                    verbose=GGUF_VERBOSE,
                )
                if not self._engine or not self._engine.ready:
                    detail = (
                        "GGUF TTS engine did not reach ready state "
                        f"after waiting up to {GGUF_DECODER_READY_TIMEOUT:.0f}s for decoder workers"
                    )
                    log_tail = _tail_gguf_runtime_log()
                    if log_tail:
                        detail = f"{detail}; GGUF runtime log tail: {log_tail}"
                    raise LocalTTSError(detail)

                self._state = "ready"
                self._load_error = None
            except Exception as exc:  # pragma: no cover - defensive runtime path
                self._state = "failed"
                self._load_error = str(exc)
                raise
            return self._engine

    def shutdown(self):
        with self._state_lock:
            engine = self._engine
            self._engine = None
            self._state = "unloaded"
            self._load_error = None

        if engine is None:
            return

        try:
            engine.shutdown()
        finally:
            del engine

        gc.collect()

    def resolve_language(self, speaker: dict) -> str:
        language_map = {
            "zh": "chinese",
            "en": "english",
            "ja": "japanese",
            "ko": "korean",
        }
        native_language = speaker.get("native_language", "zh")
        return language_map.get(native_language, "chinese")

    def _build_config(self):
        from qwen3_tts_gguf.inference import TTSConfig  # noqa: WPS433

        return TTSConfig(
            streaming=False,
            seed=42,
            # Keep predictor sampling deterministic but visibly tied to the
            # primary seed so future fixture regeneration stays explainable.
            sub_seed=43,
            temperature=0.7,
            sub_temperature=0.7,
            top_p=0.85,
            sub_top_p=0.85,
            max_steps=450,
        )

    def _generate_wav_no_lock(
        self,
        text: str,
        voice_id: str | None,
        instruct: str = "",
    ) -> tuple[np.ndarray, int]:
        text = normalize_chinese_text(text)
        if not text.strip():
            raise LocalTTSError("No text remained after normalization")

        engine = self._ensure_loaded()
        speaker = self.resolve_speaker(voice_id)
        language = self.resolve_language(speaker)
        stream = engine.create_stream()
        if stream is None:
            raise LocalTTSError("GGUF TTS engine could not create a stream")
        try:
            result = stream.custom(
                text=text,
                speaker=speaker["model_name"].lower(),
                language=language,
                instruct=instruct,
                config=self._build_config(),
            )
            if result is None or result.audio is None or len(result.audio) == 0:
                raise LocalTTSError("No audio was produced by GGUF TTS")

            audio = self._normalize_generated_audio(result.audio.astype(np.float32))
            return audio, SAMPLE_RATE
        finally:
            stream.shutdown()

    def _generate_mp3_no_lock(
        self,
        text: str,
        voice_id: str | None,
        instruct: str = "",
    ) -> str:
        audio, sr = self._generate_wav_no_lock(text, voice_id, instruct=instruct)
        return write_mp3(audio, sr, uuid.uuid4().hex, OUTPUT_DIR)

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
            return self._generate_mp3_no_lock(text, voice_id, instruct=instruct)
        finally:
            self._busy_lock.release()

    def synthesize_sentences_stream(
        self, sentences: list[str], voice_id: str | None, instruct: str = ""
    ) -> Iterator[dict]:
        normalized_sentences = self._normalize_and_split_chunks(sentences)
        filtered = [s.strip() for s in normalized_sentences if s and s.strip()]

        if not filtered:
            def _empty() -> Iterator[dict]:
                yield {"status": "done", "total": 0}

            return _empty()

        if not self._busy_lock.acquire(blocking=False):
            raise LocalTTSBusyError("Local TTS engine is busy with another request")

        try:
            event_queue: queue.Queue = queue.Queue()
            cancel_event = threading.Event()
            worker = threading.Thread(
                target=self._sentence_worker,
                args=(event_queue, cancel_event, filtered, voice_id, instruct),
                daemon=True,
            )
            worker.start()
        except BaseException:
            self._busy_lock.release()
            raise

        return self._iter_from_queue(event_queue, cancel_event)

    def synthesize_long_stream(
        self, text: str, voice_id: str | None, instruct: str = ""
    ) -> Iterator[dict]:
        text = normalize_chinese_text(text)
        chunks = self._coalesce_long_chunks(self._split_long_text(text))
        if not chunks:
            def _empty() -> Iterator[dict]:
                yield {"status": "error", "error": "No text chunks were produced"}

            return _empty()

        if not self._busy_lock.acquire(blocking=False):
            raise LocalTTSBusyError("Local TTS engine is busy with another request")

        try:
            event_queue: queue.Queue = queue.Queue()
            cancel_event = threading.Event()
            worker = threading.Thread(
                target=self._long_worker,
                args=(event_queue, cancel_event, chunks, voice_id, instruct),
                daemon=True,
            )
            worker.start()
        except BaseException:
            self._busy_lock.release()
            raise

        return self._iter_from_queue(event_queue, cancel_event)

    def _split_long_text(self, text: str) -> list[str]:
        # Reuse the route-layer splitter for now so GGUF long mode and
        # sentence mode stay aligned. This lazy import avoids module-load
        # circular imports: by call time, tts_routes has already finished
        # importing local_tts_engine.
        from tts_routes import split_into_chunks  # noqa: WPS433

        return [chunk.strip() for chunk in split_into_chunks(text, max_words=15, newline_hard=True) if chunk.strip()]

    def _normalize_and_split_chunks(self, chunks: list[str]) -> list[str]:
        # Route layer splits before selecting the concrete backend. Re-joining
        # here lets GGUF apply the same full-context normalizer that the
        # PyTorch kernel already applies internally, without double-normalizing
        # the PyTorch path at the route layer.
        return self._split_long_text(normalize_chinese_text("".join(chunks)))

    def _coalesce_long_chunks(self, chunks: list[str]) -> list[str]:
        # GGUF CustomVoice is more stable on natural phrase groups than on very
        # short isolated Chinese sentences. Coalescing only affects long-mode
        # final MP3 generation; sentence-following mode keeps per-sentence clips.
        groups: list[str] = []
        current: list[str] = []
        current_size = 0

        for chunk in chunks:
            prepared = self._prepare_long_chunk_text(chunk)
            if not prepared:
                continue

            size = self._measure_long_chunk(prepared)
            if current and current_size + size > GGUF_LONG_MAX_CHARS:
                groups.append(self._join_long_chunks(current))
                current = []
                current_size = 0

            current.append(prepared)
            current_size += size

            if (
                len(current) >= GGUF_LONG_MIN_CHUNKS
                and current_size >= GGUF_LONG_MIN_CHARS
            ):
                groups.append(self._join_long_chunks(current))
                current = []
                current_size = 0

        if current:
            groups.append(self._join_long_chunks(current))

        return groups

    def _measure_long_chunk(self, text: str) -> int:
        if re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text):
            return len(text)
        return len(text.split())

    def _join_long_chunks(self, chunks: list[str]) -> str:
        joined = "".join(chunks).strip()
        if re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", joined):
            return joined
        return " ".join(chunks).strip()

    def _prepare_long_chunk_text(self, text: str) -> str:
        """Make a long-mode chunk more natural for GGUF TTS input."""
        normalized = re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()
        if not normalized:
            return ""
        if REFERENCE_ONLY_RE.fullmatch(normalized):
            return ""
        return normalized.translate(TTS_QUOTE_TRANSLATION).strip()

    def _trim_long_chunk_audio(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        """Trim GGUF's per-chunk silence before long-mode concatenation."""
        if audio.size == 0:
            return audio

        mono = audio.mean(axis=1) if audio.ndim > 1 else audio
        peak = float(np.max(np.abs(mono)))
        if peak <= LONG_CHUNK_TRIM_MIN_ABS:
            return audio

        threshold = max(LONG_CHUNK_TRIM_MIN_ABS, peak * LONG_CHUNK_TRIM_PEAK_RATIO)
        frame_size = max(1, int(sample_rate * 0.02))
        active_frames = []
        for start in range(0, len(mono), frame_size):
            frame = mono[start : start + frame_size]
            active_frames.append(float(np.max(np.abs(frame))) >= threshold)

        active_indices = np.flatnonzero(active_frames)
        if active_indices.size == 0:
            return audio

        padding = int(sample_rate * LONG_CHUNK_TRIM_PADDING_MS / 1000)
        start_sample = max(0, int(active_indices[0]) * frame_size - padding)
        end_sample = min(
            len(audio),
            (int(active_indices[-1]) + 1) * frame_size + padding,
        )
        if end_sample <= start_sample:
            return audio
        return audio[start_sample:end_sample]

    def _long_join_gap(self, sample_rate: int, template: np.ndarray) -> np.ndarray:
        gap_samples = int(sample_rate * LONG_CHUNK_JOIN_GAP_MS / 1000)
        if template.ndim > 1:
            return np.zeros((gap_samples, template.shape[1]), dtype=np.float32)
        return np.zeros(gap_samples, dtype=np.float32)

    def _sentence_worker(
        self,
        event_queue: "queue.Queue[dict | None]",
        cancel_event: threading.Event,
        sentences: list[str],
        voice_id: str | None,
        instruct: str,
    ) -> None:
        total = len(sentences)
        try:
            for index, sentence in enumerate(sentences):
                if cancel_event.is_set():
                    return

                event_queue.put(
                    {
                        "status": "generating",
                        "index": index,
                        "total": total,
                        "text": sentence,
                    }
                )
                filename = self._generate_mp3_no_lock(
                    sentence,
                    voice_id,
                    instruct=instruct,
                )
                if cancel_event.is_set():
                    return

                event_queue.put(
                    {
                        "status": "sentence_done",
                        "index": index,
                        "total": total,
                        "text": sentence,
                        "audio_url": f"/static/audio/{filename}",
                        "filename": filename,
                    }
                )

            if not cancel_event.is_set():
                event_queue.put({"status": "done", "total": total})
        except Exception as exc:
            event_queue.put(
                {
                    "status": "error",
                    "index": index if "index" in locals() else 0,
                    "total": total,
                    "error": str(exc),
                }
            )
        finally:
            event_queue.put(None)
            self._busy_lock.release()

    def _long_worker(
        self,
        event_queue: "queue.Queue[dict | None]",
        cancel_event: threading.Event,
        chunks: list[str],
        voice_id: str | None,
        instruct: str,
    ) -> None:
        total = len(chunks)
        audio_chunks: list[np.ndarray] = []
        sample_rate = SAMPLE_RATE
        try:
            for index, chunk_text in enumerate(chunks):
                if cancel_event.is_set():
                    return

                tts_text = self._prepare_long_chunk_text(chunk_text)
                if not tts_text:
                    completed = index + 1
                    event_queue.put(
                        {
                            "status": "generating",
                            "chunk": completed,
                            "total": total,
                            "preview": chunk_text[:24],
                            "percent": int((completed / total) * 100),
                        }
                    )
                    continue

                audio_chunk, sample_rate = self._generate_wav_no_lock(
                    tts_text,
                    voice_id,
                    instruct=instruct,
                )
                audio_chunk = self._trim_long_chunk_audio(audio_chunk, sample_rate)
                audio_chunks.append(audio_chunk)
                if index < total - 1:
                    audio_chunks.append(self._long_join_gap(sample_rate, audio_chunk))
                if cancel_event.is_set():
                    return

                completed = index + 1
                event_queue.put(
                    {
                        "status": "generating",
                        "chunk": completed,
                        "total": total,
                        "preview": chunk_text[:24],
                        "percent": int((completed / total) * 100),
                    }
                )

            if cancel_event.is_set():
                return
            if not audio_chunks:
                event_queue.put({"status": "error", "error": "No audio chunks were produced"})
                return

            event_queue.put({"status": "merging"})
            audio = self._normalize_generated_audio(np.concatenate(audio_chunks).astype(np.float32))
            filename = write_mp3(audio, sample_rate, uuid.uuid4().hex, OUTPUT_DIR)
            if cancel_event.is_set():
                return

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
            event_queue.put(None)
            self._busy_lock.release()

    def _iter_from_queue(
        self,
        event_queue: "queue.Queue[dict | None]",
        cancel_event: threading.Event,
    ) -> Iterator[dict]:
        try:
            while True:
                event = event_queue.get()
                if event is None:
                    break
                yield event
                if event.get("status") in {"done", "error"}:
                    break
        finally:
            cancel_event.set()


service = LocalTTSService()
