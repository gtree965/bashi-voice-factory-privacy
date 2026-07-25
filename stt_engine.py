from dataclasses import dataclass
from pathlib import Path
from typing import Generator, List

import numpy as np

from logging_setup import get_logger


logger = get_logger(__name__)

try:
    import sherpa_onnx
except ImportError:
    sherpa_onnx = None


@dataclass
class Segment:
    """A single transcribed segment with timestamps."""
    index: int
    start: float   # seconds
    end: float     # seconds
    text: str
    language: str = ""
    speaker: int | None = None


@dataclass
class TranscriptionResult:
    """Complete transcription output."""
    segments: List[Segment]
    full_text: str
    language_detected: str
    duration_seconds: float
    processing_seconds: float


class SttEngine:
    """Shared VAD/decode template with engine-specific model hooks."""

    VAD_THRESHOLD: float = 0.5
    CHAR_LIMIT: int = 20
    ENGINE_LABEL: str = "STT"

    def __init__(self, model_dir: Path, num_threads: int = 4):
        self.model_dir = model_dir
        self.num_threads = num_threads
        self._model = None
        self._recognizer = None

    def load_model(self):
        """Load the ASR model into memory. Call once."""
        raise NotImplementedError

    def is_loaded(self) -> bool:
        return self._model is not None

    def transcribe_stream(
        self,
        audio_path: Path,
        language: str = "auto"
    ) -> Generator[Segment, None, None]:
        """Transcribe audio file, yielding segments as they complete.

        Args:
            audio_path: Path to 16kHz mono WAV file
            language: Language code or "auto"

        Yields:
            Segment objects as they are recognized
        """
        if not self.is_loaded():
            self.load_model()

        vad_model_path = self._resolve_vad_model_path()
        samples, sample_rate = self._load_wav_16k_mono(audio_path)
        speech_segments = self._run_vad(samples, sample_rate, vad_model_path)

        logger.info(
            f"[{self.ENGINE_LABEL}] VAD detected "
            f"{len(speech_segments)} speech segments"
        )

        segment_index = 0
        prev_end_time = 0.0

        for seg_start, seg_end, seg_samples in speech_segments:
            if len(seg_samples) < sample_rate * 0.2:
                continue

            text = self._decode_segment(seg_samples, sample_rate)
            if not text:
                continue

            sub_segments = self._split_text_into_segments(
                text,
                seg_start,
                seg_end,
                language,
                segment_index,
                char_limit=self.CHAR_LIMIT,
            )

            for sub_seg in sub_segments:
                if sub_seg.start < prev_end_time:
                    sub_seg.start = prev_end_time
                if sub_seg.end <= sub_seg.start:
                    sub_seg.end = sub_seg.start + 0.3
                sub_seg.index = segment_index
                prev_end_time = sub_seg.end
                yield sub_seg
                segment_index += 1

    def _resolve_vad_model_path(self) -> Path:
        vad_model_path = self.model_dir.parent / "silero_vad.onnx"
        if not vad_model_path.exists():
            candidate = Path("models") / "silero_vad.onnx"
            if candidate.exists():
                vad_model_path = candidate

        if not vad_model_path.exists():
            raise FileNotFoundError(
                f"VAD model not found at {vad_model_path}. "
                "Please ensure silero_vad.onnx is in the models directory."
            )
        return vad_model_path

    def _load_wav_16k_mono(self, audio_path: Path) -> tuple[np.ndarray, int]:
        import wave

        with wave.open(str(audio_path), "rb") as wf:
            sample_rate = wf.getframerate()
            num_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            num_frames = wf.getnframes()

            if sample_rate != 16000:
                raise ValueError(f"Expected 16kHz audio, got {sample_rate}Hz")

            raw = wf.readframes(num_frames)
            if sample_width == 2:
                samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            elif sample_width == 4:
                samples = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
            else:
                raise ValueError(f"Unsupported sample width: {sample_width}")

            if num_channels > 1:
                samples = samples[::num_channels]

        return samples, sample_rate

    def _run_vad(
        self,
        samples: np.ndarray,
        sample_rate: int,
        vad_model_path: Path,
    ) -> list[tuple[float, float, np.ndarray]]:
        if sherpa_onnx is None:
            raise ImportError(
                "sherpa-onnx not installed. Run: pip install sherpa-onnx"
            )

        vad_config = sherpa_onnx.VadModelConfig()
        vad_config.silero_vad.model = str(vad_model_path)
        vad_config.silero_vad.min_silence_duration = 0.3
        vad_config.silero_vad.min_speech_duration = 0.25
        vad_config.silero_vad.threshold = self.VAD_THRESHOLD
        vad_config.silero_vad.max_speech_duration = 30.0
        vad_config.sample_rate = sample_rate

        window_size = vad_config.silero_vad.window_size
        vad = sherpa_onnx.VoiceActivityDetector(
            vad_config,
            buffer_size_in_seconds=600,
        )

        offset = 0
        while offset < len(samples):
            end = min(offset + window_size, len(samples))
            chunk = samples[offset:end]
            if len(chunk) < window_size:
                chunk = np.concatenate(
                    [
                        chunk,
                        np.zeros(window_size - len(chunk), dtype=np.float32),
                    ]
                )
            vad.accept_waveform(chunk)
            offset += window_size

        vad.flush()

        speech_segments = []
        while not vad.empty():
            seg = vad.front
            start_sec = seg.start / sample_rate
            seg_samples = np.array(seg.samples, dtype=np.float32)
            end_sec = start_sec + len(seg_samples) / sample_rate
            speech_segments.append((start_sec, end_sec, seg_samples))
            vad.pop()

        return speech_segments

    def _decode_segment(self, seg_samples: np.ndarray, sample_rate: int) -> str:
        stream = self._recognizer.create_stream()
        stream.accept_waveform(sample_rate, seg_samples)
        self._recognizer.decode_stream(stream)
        return self._postprocess_text(stream.result.text.strip())

    def _postprocess_text(self, text: str) -> str:
        """Process already-stripped recognizer text; return "" to skip it."""
        return text

    @staticmethod
    def _split_text_into_segments(
        text: str,
        start_sec: float,
        end_sec: float,
        language: str,
        base_index: int,
        char_limit: int,
    ) -> list[Segment]:
        raise NotImplementedError

    def supported_languages(self) -> List[str]:
        """Return list of supported language codes."""
        raise NotImplementedError

    def cleanup(self):
        """Release model from memory."""
        self._recognizer = None
        self._model = None
