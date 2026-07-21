import argparse
import json
import os
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from speaker_diarization import SpeakerDiarizer
from utils import extract_audio_wav


def _is_16k_mono_wav(path: Path) -> bool:
    if path.suffix.lower() != ".wav":
        return False
    try:
        with wave.open(str(path), "rb") as wf:
            return wf.getframerate() == 16000 and wf.getnchannels() == 1
    except wave.Error:
        return False


def _prepare_audio(path: Path) -> Path:
    if _is_16k_mono_wav(path):
        return path
    tmp_dir = Path(".tmp")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    prepared = tmp_dir / f"speaker_probe_{path.stem}_16k.wav"
    print(f"preparing_audio={prepared}", flush=True)
    return extract_audio_wav(path, prepared)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local Speaker ID diarization probe.")
    parser.add_argument("audio", type=Path, help="16 kHz mono WAV file to diarize")
    parser.add_argument("--models-dir", type=Path, default=Path("models"))
    parser.add_argument("--preset", default="balanced")
    parser.add_argument("--speakers", type=int, default=-1)
    parser.add_argument("--embedding", help="Embedding model path or filename")
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--out", type=Path, help="Optional JSON output path")
    args = parser.parse_args()

    if args.embedding:
        os.environ["BASHI_SPEAKER_EMBEDDING"] = args.embedding
    if args.threshold is not None:
        os.environ["BASHI_SPEAKER_CLUSTER_THRESHOLD"] = str(args.threshold)

    progress = {"last": -1}

    def progress_callback(done: int, total: int) -> int:
        if total:
            percent = int((done / total) * 100)
            if percent >= progress["last"] + 10:
                progress["last"] = percent
                print(f"progress={percent}% ({done}/{total})", flush=True)
        return 0

    started = time.monotonic()
    prepared_audio = _prepare_audio(args.audio)
    diarizer = SpeakerDiarizer(args.models_dir, preset=args.preset)
    turns = diarizer.diarize(
        prepared_audio,
        num_speakers=args.speakers,
        progress_callback=progress_callback,
    )
    elapsed = time.monotonic() - started
    payload = {
        "audio": str(args.audio),
        "prepared_audio": str(prepared_audio),
        "preset": args.preset,
        "requested_speakers": args.speakers,
        "elapsed_seconds": round(elapsed, 3),
        "turns": [
            {
                "start": turn.start,
                "end": turn.end,
                "speaker": turn.speaker,
            }
            for turn in turns
        ],
        "metrics": diarizer.last_metrics,
    }

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(payload["metrics"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
