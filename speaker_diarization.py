import os
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import numpy as np


SEGMENTATION_MODEL_RELATIVE = Path(
    "speaker-diarization",
    "sherpa-onnx-pyannote-segmentation-3-0",
    "model.int8.onnx",
)
EMBEDDING_MODEL_FILENAME = "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
EMBEDDING_MODEL_RELATIVE = Path("speaker-diarization", EMBEDDING_MODEL_FILENAME)

SPEAKER_PRESETS = {
    "accurate": {
        "min_duration_on": 0.3,
        "min_duration_off": 0.5,
    },
    "balanced": {
        "min_duration_on": 0.4,
        "min_duration_off": 0.8,
    },
    "fast": {
        "min_duration_on": 0.5,
        "min_duration_off": 1.2,
    },
}


@dataclass(frozen=True)
class SpeakerTurn:
    start: float
    end: float
    speaker: int


def speaker_label(speaker: int, ui_lang: str = "en") -> str:
    number = int(speaker) + 1
    if ui_lang == "zh":
        return f"说话人 {number}"
    return f"Speaker {number}"


def resolve_speaker_threads(value: int | None = None) -> int:
    """Resolve Speaker ID ONNX thread count.

    Environment override is intentionally simple for field testing:
    BASHI_SPEAKER_THREADS=1/2/4/8...
    """
    if value is not None and value > 0:
        return max(1, min(int(value), 32))

    env_value = os.environ.get("BASHI_SPEAKER_THREADS")
    if env_value:
        try:
            parsed = int(env_value)
            if parsed > 0:
                return max(1, min(parsed, 32))
        except ValueError:
            pass

    cpu_count = os.cpu_count() or 4
    return min(8, max(2, cpu_count // 2))


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def resolve_speaker_embedding_model(models_dir: Path) -> Path:
    env_value = os.environ.get("BASHI_SPEAKER_EMBEDDING")
    if not env_value or not env_value.strip():
        return Path(models_dir) / EMBEDDING_MODEL_RELATIVE

    candidate = Path(env_value.strip())
    if candidate.is_absolute():
        return candidate
    if candidate.parent == Path("."):
        return Path(models_dir) / "speaker-diarization" / candidate
    return Path(models_dir) / candidate


def resolve_speaker_cluster_threshold(default: float = 0.5) -> float:
    return _env_float("BASHI_SPEAKER_CLUSTER_THRESHOLD", default)


def resolve_speaker_preset(preset: str | None) -> tuple[str, float, float]:
    preset_id = (preset or os.environ.get("BASHI_SPEAKER_PRESET") or "balanced").strip().lower()
    if preset_id not in SPEAKER_PRESETS:
        preset_id = "balanced"

    defaults = SPEAKER_PRESETS[preset_id]
    min_duration_on = _env_float("BASHI_SPEAKER_MIN_DURATION_ON", defaults["min_duration_on"])
    min_duration_off = _env_float("BASHI_SPEAKER_MIN_DURATION_OFF", defaults["min_duration_off"])
    return preset_id, min_duration_on, min_duration_off


def _read_mono_wave(path: Path) -> tuple[np.ndarray, int]:
    """Read a mono float32 waveform using only the stdlib + numpy."""
    with wave.open(str(path), "rb") as wf:
        sample_rate = wf.getframerate()
        num_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        num_frames = wf.getnframes()
        raw = wf.readframes(num_frames)

    if sample_width == 2:
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        samples = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported sample width for speaker ID: {sample_width}")

    if num_channels > 1:
        samples = samples.reshape(-1, num_channels)[:, 0]

    return samples, sample_rate


def _overlap_seconds(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _nearest_turn(midpoint: float, turns: Iterable[SpeakerTurn]) -> SpeakerTurn | None:
    best_turn = None
    best_distance = float("inf")
    for turn in turns:
        if turn.start <= midpoint <= turn.end:
            return turn
        distance = min(abs(midpoint - turn.start), abs(midpoint - turn.end))
        if distance < best_distance:
            best_turn = turn
            best_distance = distance
    return best_turn


def assign_speakers_to_segments(
    segments: list[dict],
    turns: list[SpeakerTurn],
    *,
    min_overlap_seconds: float = 0.05,
    max_nearest_seconds: float = 0.75,
) -> list[dict]:
    """Copy ASR segments and attach the dominant speaker cluster.

    The ASR engines and the diarizer produce independent boundaries.  The most
    stable mapping is therefore "speaker turn with the largest time overlap",
    with a small nearest-turn fallback for proportional ASR splits that land a
    few milliseconds outside the diarization boundary.
    """
    if not segments or not turns:
        return [dict(seg) for seg in segments]

    labeled = []
    for seg in segments:
        new_seg = dict(seg)
        seg_start = float(new_seg.get("start", 0.0))
        seg_end = float(new_seg.get("end", seg_start))
        best_turn = None
        best_overlap = 0.0

        for turn in turns:
            overlap = _overlap_seconds(seg_start, seg_end, turn.start, turn.end)
            if overlap > best_overlap:
                best_turn = turn
                best_overlap = overlap

        if best_turn is None or best_overlap < min_overlap_seconds:
            midpoint = seg_start + max(0.0, seg_end - seg_start) / 2
            nearest = _nearest_turn(midpoint, turns)
            if nearest is not None:
                distance = 0.0
                if midpoint < nearest.start:
                    distance = nearest.start - midpoint
                elif midpoint > nearest.end:
                    distance = midpoint - nearest.end
                if distance <= max_nearest_seconds:
                    best_turn = nearest

        if best_turn is not None:
            new_seg["speaker"] = int(best_turn.speaker)
            new_seg["speaker_label"] = speaker_label(best_turn.speaker)
        labeled.append(new_seg)

    return labeled


def summarize_speaker_turns(turns: list[SpeakerTurn]) -> list[dict]:
    summary: dict[int, dict] = {}
    for turn in turns:
        speaker = int(turn.speaker)
        duration = max(0.0, float(turn.end) - float(turn.start))
        if speaker not in summary:
            summary[speaker] = {
                "speaker": speaker,
                "speaker_label": speaker_label(speaker),
                "turn_count": 0,
                "total_seconds": 0.0,
            }
        summary[speaker]["turn_count"] += 1
        summary[speaker]["total_seconds"] += duration

    rows = []
    for speaker in sorted(summary):
        row = dict(summary[speaker])
        row["total_seconds"] = round(row["total_seconds"], 3)
        rows.append(row)
    return rows


class SpeakerDiarizer:
    """sherpa-onnx offline speaker diarization wrapper."""

    def __init__(
        self,
        models_dir: Path,
        *,
        num_threads: int | None = None,
        preset: str | None = None,
        cluster_threshold: float = 0.5,
        min_duration_on: float | None = None,
        min_duration_off: float | None = None,
    ):
        self.models_dir = Path(models_dir)
        self.num_threads = resolve_speaker_threads(num_threads)
        self.preset, preset_min_on, preset_min_off = resolve_speaker_preset(preset)
        self.cluster_threshold = resolve_speaker_cluster_threshold(cluster_threshold)
        self.min_duration_on = min_duration_on if min_duration_on is not None else preset_min_on
        self.min_duration_off = min_duration_off if min_duration_off is not None else preset_min_off
        self.embedding_model_path = resolve_speaker_embedding_model(self.models_dir)
        self.last_metrics: dict = {}

    @property
    def segmentation_model(self) -> Path:
        return self.models_dir / SEGMENTATION_MODEL_RELATIVE

    @property
    def embedding_model(self) -> Path:
        return self.embedding_model_path

    def is_available(self) -> bool:
        try:
            return self.segmentation_model.exists() and self.embedding_model.exists()
        except OSError:
            return False

    def diarize(
        self,
        audio_path: Path,
        *,
        num_speakers: int = -1,
        progress_callback: Callable[[int, int], int] | None = None,
    ) -> list[SpeakerTurn]:
        if not self.is_available():
            raise FileNotFoundError(
                "Speaker ID model is not installed. Download it from the STT panel first."
            )

        try:
            import sherpa_onnx
        except ImportError as exc:
            raise ImportError("sherpa-onnx is required for Speaker ID.") from exc

        config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=str(self.segmentation_model),
                ),
                num_threads=self.num_threads,
                provider="cpu",
            ),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(self.embedding_model),
                num_threads=self.num_threads,
                provider="cpu",
            ),
            clustering=sherpa_onnx.FastClusteringConfig(
                num_clusters=num_speakers if num_speakers > 0 else -1,
                threshold=self.cluster_threshold,
            ),
            min_duration_on=self.min_duration_on,
            min_duration_off=self.min_duration_off,
        )
        if not config.validate():
            raise RuntimeError("Speaker ID model files failed sherpa-onnx validation.")

        diarizer = sherpa_onnx.OfflineSpeakerDiarization(config)
        samples, sample_rate = _read_mono_wave(Path(audio_path))
        if sample_rate != diarizer.sample_rate:
            raise ValueError(
                f"Speaker ID expected {diarizer.sample_rate}Hz audio, got {sample_rate}Hz."
            )

        audio_duration = len(samples) / sample_rate if sample_rate else 0.0
        process_start = time.monotonic()
        first_callback_time = None
        last_callback_time = None
        progress_callback_count = 0
        callback_total = None

        self.last_metrics = {
            "preset": self.preset,
            "num_threads": self.num_threads,
            "num_speakers": num_speakers,
            "cluster_threshold": self.cluster_threshold,
            "min_duration_on": self.min_duration_on,
            "min_duration_off": self.min_duration_off,
            "embedding_model": str(self.embedding_model),
            "audio_duration_seconds": round(audio_duration, 3),
        }

        def timing_callback(num_processed_chunk: int, num_total_chunks: int) -> int:
            nonlocal first_callback_time, last_callback_time, progress_callback_count, callback_total
            now = time.monotonic()
            if first_callback_time is None:
                first_callback_time = now
            last_callback_time = now
            progress_callback_count += 1
            callback_total = num_total_chunks
            if progress_callback:
                return progress_callback(num_processed_chunk, num_total_chunks)
            return 0

        if progress_callback:
            result = diarizer.process(samples, callback=timing_callback).sort_by_start_time()
        else:
            # Still pass our callback so timing can estimate the embedding loop.
            result = diarizer.process(samples, callback=timing_callback).sort_by_start_time()

        process_end = time.monotonic()
        turns = [
            SpeakerTurn(
                start=round(float(turn.start), 3),
                end=round(float(turn.end), 3),
                speaker=int(turn.speaker),
            )
            for turn in result
            if float(turn.end) > float(turn.start)
        ]

        pre_callback_seconds = (
            first_callback_time - process_start
            if first_callback_time is not None
            else None
        )
        callback_seconds = (
            last_callback_time - first_callback_time
            if first_callback_time is not None and last_callback_time is not None
            else None
        )
        post_callback_seconds = (
            process_end - last_callback_time
            if last_callback_time is not None
            else None
        )
        total_seconds = process_end - process_start
        speaker_stats = summarize_speaker_turns(turns)
        self.last_metrics.update({
            "total_seconds": round(total_seconds, 3),
            "pre_callback_seconds": round(pre_callback_seconds, 3) if pre_callback_seconds is not None else None,
            "callback_seconds": round(callback_seconds, 3) if callback_seconds is not None else None,
            "post_callback_seconds": round(post_callback_seconds, 3) if post_callback_seconds is not None else None,
            "progress_callback_count": progress_callback_count,
            "callback_total_chunks": callback_total,
            "speaker_turn_count": len(turns),
            "speaker_count_detected": len(speaker_stats),
            "speaker_stats": speaker_stats,
            "rtf": round(total_seconds / audio_duration, 4) if audio_duration else None,
        })

        return turns
