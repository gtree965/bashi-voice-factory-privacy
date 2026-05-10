import subprocess
from pathlib import Path

import numpy as np


DEFAULT_TARGET_PEAK_DBFS = -1.0


def peak_normalize_audio(
    audio: np.ndarray,
    target_peak_dbfs: float = DEFAULT_TARGET_PEAK_DBFS,
) -> np.ndarray:
    audio_array = np.asarray(audio, dtype=np.float32)
    if audio_array.size == 0:
        return audio_array

    peak = float(np.max(np.abs(audio_array)))
    if peak <= 0.0:
        return audio_array

    target_peak = 10 ** (target_peak_dbfs / 20.0)
    normalized = audio_array * (target_peak / peak)
    return np.clip(normalized, -target_peak, target_peak).astype(np.float32, copy=False)


def write_mp3(
    audio: np.ndarray,
    sr: int,
    stem: str,
    output_dir: Path,
    *,
    normalize_peak: bool = True,
    target_peak_dbfs: float = DEFAULT_TARGET_PEAK_DBFS,
) -> str:
    import imageio_ffmpeg
    import soundfile as sf

    output_dir.mkdir(parents=True, exist_ok=True)
    temp_wav = output_dir / f"{stem}.wav"
    target_mp3 = output_dir / f"{stem}.mp3"
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    audio_to_write = (
        peak_normalize_audio(audio, target_peak_dbfs)
        if normalize_peak
        else np.asarray(audio, dtype=np.float32)
    )
    sf.write(temp_wav, audio_to_write, sr)
    subprocess.run(
        [
            ffmpeg_exe,
            "-y",
            "-i",
            str(temp_wav),
            "-codec:a",
            "libmp3lame",
            "-qscale:a",
            "2",
            str(target_mp3),
        ],
        check=True,
        capture_output=True,
    )
    temp_wav.unlink(missing_ok=True)
    return target_mp3.name
