import unittest
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask

import stt_routes
from model_manager import MODEL_REGISTRY
from stt_engine import Segment
from speaker_diarization import (
    SpeakerDiarizer,
    SpeakerTurn,
    assign_speakers_to_segments,
    resolve_speaker_cluster_threshold,
    resolve_speaker_embedding_model,
    resolve_speaker_preset,
    resolve_speaker_threads,
    speaker_label,
    summarize_speaker_turns,
)


class SpeakerAssignmentTests(unittest.TestCase):
    def test_assigns_dominant_overlap(self):
        segments = [
            {"index": 0, "start": 0.0, "end": 2.0, "text": "hello"},
            {"index": 1, "start": 2.1, "end": 4.0, "text": "world"},
        ]
        turns = [
            SpeakerTurn(start=0.0, end=2.2, speaker=0),
            SpeakerTurn(start=2.2, end=4.0, speaker=1),
        ]

        labeled = assign_speakers_to_segments(segments, turns)

        self.assertEqual(labeled[0]["speaker"], 0)
        self.assertEqual(labeled[0]["speaker_label"], "Speaker 1")
        self.assertEqual(labeled[1]["speaker"], 1)
        self.assertEqual(labeled[1]["speaker_label"], "Speaker 2")

    def test_speaker_label_is_localized(self):
        self.assertEqual(speaker_label(0, "en"), "Speaker 1")
        self.assertEqual(speaker_label(1, "zh"), "说话人 2")

    def test_auto_threads_uses_half_logical_cores_capped_at_eight(self):
        with patch("speaker_diarization.os.cpu_count", return_value=16):
            self.assertEqual(resolve_speaker_threads(), 8)

    def test_thread_env_override_wins(self):
        with patch.dict("speaker_diarization.os.environ", {"BASHI_SPEAKER_THREADS": "4"}):
            self.assertEqual(resolve_speaker_threads(), 4)

    def test_balanced_preset_is_default(self):
        preset, min_on, min_off = resolve_speaker_preset(None)

        self.assertEqual(preset, "balanced")
        self.assertEqual(min_on, 0.4)
        self.assertEqual(min_off, 0.8)

    def test_explicit_preset_resolves_fast(self):
        preset, min_on, min_off = resolve_speaker_preset("fast")

        self.assertEqual(preset, "fast")
        self.assertEqual(min_on, 0.5)
        self.assertEqual(min_off, 1.2)

    def test_embedding_env_accepts_filename_relative_to_speaker_dir(self):
        with patch.dict(
            "speaker_diarization.os.environ",
            {"BASHI_SPEAKER_EMBEDDING": "custom.onnx"},
        ):
            path = resolve_speaker_embedding_model(Path("models"))

        self.assertEqual(path, Path("models") / "speaker-diarization" / "custom.onnx")

    def test_cluster_threshold_env_override(self):
        with patch.dict(
            "speaker_diarization.os.environ",
            {"BASHI_SPEAKER_CLUSTER_THRESHOLD": "0.8"},
        ):
            self.assertEqual(resolve_speaker_cluster_threshold(0.5), 0.8)

    def test_summarizes_turns_by_speaker(self):
        turns = [
            SpeakerTurn(start=0.0, end=2.0, speaker=0),
            SpeakerTurn(start=3.0, end=4.5, speaker=0),
            SpeakerTurn(start=5.0, end=5.5, speaker=2),
        ]

        summary = summarize_speaker_turns(turns)

        self.assertEqual(
            summary,
            [
                {
                    "speaker": 0,
                    "speaker_label": "Speaker 1",
                    "turn_count": 2,
                    "total_seconds": 3.5,
                },
                {
                    "speaker": 2,
                    "speaker_label": "Speaker 3",
                    "turn_count": 1,
                    "total_seconds": 0.5,
                },
            ],
        )


class SttSpeakerExportTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.job_id = "speaker-test-job"

    def tearDown(self):
        stt_routes.stt_jobs.pop(self.job_id, None)

    def _export_text(self, query):
        with self.app.test_request_context(query):
            response = stt_routes.export_result(self.job_id)
            return response.get_data(as_text=True)

    def test_txt_export_stays_raw_without_speaker_id(self):
        stt_routes.stt_jobs[self.job_id] = {
            "filename": "meeting.wav",
            "status": "done",
            "speaker_id_enabled": False,
            "segments": [
                {"index": 0, "start": 0.0, "end": 1.0, "text": "hello", "speaker": 0},
            ],
        }

        content = self._export_text("/?format=txt&lang=en")

        self.assertEqual(content, "hello")

    def test_txt_export_adds_speaker_labels_when_enabled(self):
        stt_routes.stt_jobs[self.job_id] = {
            "filename": "meeting.wav",
            "status": "done",
            "speaker_id_enabled": True,
            "segments": [
                {"index": 0, "start": 0.0, "end": 1.0, "text": "hello", "speaker": 0},
                {"index": 1, "start": 1.1, "end": 2.0, "text": "world", "speaker": 1},
            ],
        }

        content = self._export_text("/?format=txt&lang=en")

        self.assertEqual(content, "Speaker 1: hello\nSpeaker 2: world")

    def test_srt_export_does_not_merge_across_speakers(self):
        stt_routes.stt_jobs[self.job_id] = {
            "filename": "meeting.wav",
            "status": "done",
            "speaker_id_enabled": True,
            "segments": [
                {"index": 0, "start": 0.0, "end": 0.6, "text": "hi", "speaker": 0},
                {"index": 1, "start": 0.7, "end": 1.1, "text": "yes", "speaker": 1},
            ],
        }

        content = self._export_text("/?format=srt&lang=en")

        self.assertIn("Speaker 1: hi", content)
        self.assertIn("Speaker 2: yes", content)
        self.assertIn("\n2\n", content)


class SttUploadSafetyTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(stt_routes.stt_bp)
        stt_routes._job_active = False

    def tearDown(self):
        stt_routes._job_active = False

    def test_upload_rejects_files_above_configured_limit(self):
        with patch.object(stt_routes, "MAX_UPLOAD_BYTES", 1):
            response = self.app.test_client().post(
                "/api/stt/transcribe",
                data={"file": (io.BytesIO(b"too large"), "clip.wav")},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 413)
        self.assertIn("File too large", response.get_json()["error"])


class SttSpeakerFailureTests(unittest.TestCase):
    def tearDown(self):
        stt_routes.stt_jobs.pop("speaker-fail-job", None)

    def test_diarization_failure_preserves_completed_transcript(self):
        job_id = "speaker-fail-job"
        stt_routes.stt_jobs[job_id] = {
            "job_id": job_id,
            "filename": "meeting.wav",
            "model_id": "sensevoice-small-int8",
            "status": "pending",
            "segments": [],
            "speaker_id_enabled": True,
            "speaker_count": -1,
            "speaker_turns": [],
            "speaker_progress": None,
            "speaker_error": None,
            "error": None,
            "created_at": 0,
        }

        engine = Mock()
        engine.transcribe_stream.return_value = [
            Segment(index=0, start=0.0, end=1.0, text="hello"),
            Segment(index=1, start=1.0, end=2.0, text="world"),
        ]

        with patch("stt_routes.extract_audio_wav"), \
                patch("stt_routes.acquire_engine", return_value=engine), \
                patch("stt_routes.release_engine"), \
                patch("stt_routes.SpeakerDiarizer") as diarizer_cls:
            diarizer_cls.return_value.diarize.side_effect = RuntimeError("speaker oom")

            stt_routes._process_transcription(
                job_id,
                Path("missing-upload.wav"),
                "meeting.wav",
                "en",
                "sensevoice-small-int8",
                speaker_id_enabled=True,
                speaker_count=-1,
            )

        job = stt_routes.stt_jobs[job_id]
        self.assertEqual(job["status"], "done")
        self.assertIsNone(job["error"])
        self.assertEqual(job["speaker_error"], "speaker oom")
        self.assertEqual([seg["text"] for seg in job["segments"]], ["hello", "world"])

    def test_job_metrics_are_persisted_outside_launch_log(self):
        job_id = "speaker-metrics-job"
        stt_routes.stt_jobs[job_id] = {
            "job_id": job_id,
            "filename": "meeting.wav",
            "model_id": "sensevoice-small-int8",
            "status": "pending",
            "segments": [],
            "speaker_id_enabled": True,
            "speaker_count": 3,
            "speaker_preset": "balanced",
            "speaker_turns": [],
            "speaker_progress": None,
            "speaker_error": None,
            "speaker_metrics": {},
            "timing": {},
            "error": None,
            "created_at": 0,
        }

        engine = Mock()
        engine.transcribe_stream.return_value = [
            Segment(index=0, start=0.0, end=1.0, text="hello"),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_dir = Path(tmpdir)
            with patch("stt_routes.METRICS_DIR", metrics_dir), \
                    patch("stt_routes.extract_audio_wav"), \
                    patch("stt_routes.acquire_engine", return_value=engine), \
                    patch("stt_routes.release_engine"), \
                    patch("stt_routes.SpeakerDiarizer") as diarizer_cls:
                diarizer_cls.return_value.diarize.side_effect = RuntimeError("speaker oom")

                stt_routes._process_transcription(
                    job_id,
                    Path("missing-upload.wav"),
                    "meeting.wav",
                    "en",
                    "sensevoice-small-int8",
                    speaker_id_enabled=True,
                    speaker_count=3,
                    speaker_preset="balanced",
                )

            payload = json.loads((metrics_dir / f"{job_id}.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["job_id"], job_id)
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["segment_count"], 1)
        self.assertEqual(payload["speaker_count"], 3)
        self.assertEqual(payload["speaker_preset"], "balanced")
        self.assertEqual(payload["speaker_error"], "speaker oom")
        self.assertIn("asr_seconds", payload["timing"])


class SubtitleNormalizationTests(unittest.TestCase):
    def test_cjk_normalization_preserves_protected_patterns(self):
        text = "请访问 https://example.com/a-b?q=1，然后在 12:34:56 开始。"

        normalized = stt_routes.normalize_subtitle_text(text)

        self.assertEqual(
            normalized,
            "请访问 https://example.com/a-b?q=1，然后在 12:34:56 开始",
        )

    def test_cjk_normalization_preserves_numbers_and_internal_apostrophes(self):
        text = "价格是 1,234.56 元，版本 v2.11.0；don't change it!"

        normalized = stt_routes.normalize_subtitle_text(text)

        self.assertEqual(
            normalized,
            "价格是 1,234.56 元\u3000版本 v2.11.0\u3000don't change it",
        )

    def test_english_normalization_is_unchanged(self):
        text = "Hello, world! Visit www.example.com/test at 09:30."

        self.assertEqual(stt_routes.normalize_subtitle_text(text), text)


class SttAsrRegistrationTests(unittest.TestCase):
    def tearDown(self):
        stt_routes.engine_instance = None
        stt_routes.current_engine_model_id = None
        stt_routes._engine_ref_count = 0

    def test_sensevoice_registry_entry_is_default_with_verified_files(self):
        meta = MODEL_REGISTRY["sensevoice-small-int8"]

        self.assertTrue(meta["is_default"])
        self.assertEqual(meta["languages"], ["zh", "en", "ja", "ko", "yue"])
        self.assertIn("Default fast multilingual ASR", meta["description"])
        self.assertEqual(
            meta["files"]["model.int8.onnx"]["sha256"],
            "c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51",
        )
        self.assertEqual(
            meta["files"]["tokens.txt"]["sha256"],
            "f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc",
        )

    def test_sensevoice_model_uses_sensevoice_engine(self):
        meta = {
            "id": "sensevoice-small-int8",
            "name": "SenseVoice Small (INT8)",
        }

        with patch.object(stt_routes.model_manager, "list_installed", return_value=[meta]), \
                patch.object(stt_routes.model_manager, "get_model_dir", return_value=Path("models/sensevoice-small-int8")), \
                patch("stt_engine_factory.SherpaSenseVoiceEngine") as sensevoice_cls:
            engine = stt_routes.acquire_engine("sensevoice-small-int8")

        self.assertIs(engine, sensevoice_cls.return_value)
        sensevoice_cls.assert_called_once_with(Path("models/sensevoice-small-int8"))
        sensevoice_cls.return_value.load_model.assert_called_once()

    def test_unknown_model_engine_does_not_fallback_to_sensevoice(self):
        meta = {
            "id": "mystery-asr-int8",
            "name": "Mystery ASR",
        }

        with patch.object(stt_routes.model_manager, "list_installed", return_value=[meta]), \
                patch.object(stt_routes.model_manager, "get_model_dir", return_value=Path("models/mystery-asr-int8")), \
                patch("stt_engine_factory.SherpaSenseVoiceEngine") as sensevoice_cls:
            engine = stt_routes.acquire_engine("mystery-asr-int8")

        self.assertIsNone(engine)
        sensevoice_cls.assert_not_called()

    def test_speaker_id_ui_is_disabled_by_default(self):
        with patch.dict("model_manager.os.environ", {}, clear=True):
            status = stt_routes.model_manager.get_speaker_diarization_status()

        self.assertFalse(status["ui_enabled"])


if __name__ == "__main__":
    unittest.main()
