import json
import threading
from pathlib import Path

import numpy as np

from audio_encoding import peak_normalize_audio
from local_voice_catalog import build_voice_catalog


APP_ROOT = Path(__file__).resolve().parent
SPEAKERS_PATH = APP_ROOT / "bashi_tts_kernel" / "speakers.json"


class LocalTTSError(RuntimeError):
    pass


class LocalTTSBusyError(LocalTTSError):
    pass


class LocalTTSServiceBase:
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

    def warmup(self):
        self._ensure_loaded()

    def resolve_speaker(self, requested_id: str | None) -> dict:
        speaker_id = requested_id or self._speakers["default_speaker"]
        canonical_id = self._speakers["alias_to_id"].get(speaker_id.lower())
        if canonical_id is None:
            raise LocalTTSError(f"Unknown local speaker: {speaker_id}")
        return self._speakers["by_id"][canonical_id]

    def _normalize_generated_audio(self, audio: np.ndarray) -> np.ndarray:
        return peak_normalize_audio(audio)

    def _ensure_loaded(self):
        raise NotImplementedError

    def shutdown(self):
        raise NotImplementedError

    def resolve_language(self, speaker: dict) -> str:
        raise NotImplementedError

    def _generate_wav_no_lock(self, *args, **kwargs):
        raise NotImplementedError

    def _generate_mp3_no_lock(self, *args, **kwargs):
        raise NotImplementedError

    def synthesize_text(self, *args, **kwargs):
        raise NotImplementedError

    def synthesize_sentences_stream(self, *args, **kwargs):
        raise NotImplementedError

    def synthesize_long_stream(self, *args, **kwargs):
        raise NotImplementedError
