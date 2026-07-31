import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from flask import Flask

import tts_routes


class FakeTTSService:
    def __init__(self):
        self.calls = []

    def synthesize_text(self, text, voice, instruct="", progress_callback=None):
        self.calls.append(("text", text, voice, instruct))
        return "fake.mp3"

    def synthesize_long_stream(self, text, voice, instruct=""):
        self.calls.append(("long", text, voice, instruct))
        yield {"status": "done", "filename_mp3": "fake-long.mp3"}

    def synthesize_sentences_stream(self, sentences, voice, instruct=""):
        self.calls.append(("sentences", sentences, voice, instruct))
        yield {"status": "done", "total": len(sentences)}


class TTSRouteInstructTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(tts_routes.tts_bp)
        self.client = self.app.test_client()
        self.fake_service = FakeTTSService()
        self.original_service = tts_routes.service
        tts_routes.service = self.fake_service

    def tearDown(self):
        tts_routes.service = self.original_service

    def test_synthesize_passes_optional_instruct(self):
        response = self.client.post(
            "/api/synthesize",
            json={"text": "你好。", "voice": "serena", "instruct": "用开心的语气说"},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            [("text", "你好。", "serena", "用开心的语气说")],
            self.fake_service.calls,
        )

    def test_synthesize_long_passes_optional_instruct(self):
        response = self.client.post(
            "/api/synthesize-long",
            json={"text": "第一句。第二句。", "voice": "serena", "instruct": "用极慢的语速说"},
        )

        self.assertEqual(200, response.status_code)
        response.get_data(as_text=True)
        self.assertEqual(
            [("long", "第一句。第二句。", "serena", "用极慢的语速说")],
            self.fake_service.calls,
        )

    def test_synthesize_sentences_passes_optional_instruct(self):
        response = self.client.post(
            "/api/synthesize-sentences",
            json={"text": "第一句。第二句。", "voice": "serena", "instruct": "用愤怒的语气说"},
        )

        self.assertEqual(200, response.status_code)
        response.get_data(as_text=True)
        self.assertEqual("sentences", self.fake_service.calls[0][0])
        self.assertEqual("serena", self.fake_service.calls[0][2])
        self.assertEqual("用愤怒的语气说", self.fake_service.calls[0][3])

    def test_null_instruct_defaults_to_neutral(self):
        response = self.client.post(
            "/api/synthesize",
            json={"text": "你好。", "voice": "serena", "instruct": None},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual([("text", "你好。", "serena", "")], self.fake_service.calls)

    def test_convert_audio_rejects_path_traversal_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
                patch.object(tts_routes, "OUTPUT_DIR", Path(tmpdir)):
            response = self.client.post(
                "/api/convert",
                json={"filename": "../outside.mp3", "format": "wav"},
            )

        self.assertEqual(400, response.status_code)
        self.assertEqual("Invalid filename", response.get_json()["error"])

    def test_convert_audio_rejects_filename_rewritten_by_secure_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
                patch.object(tts_routes, "OUTPUT_DIR", Path(tmpdir)):
            response = self.client.post(
                "/api/convert",
                json={"filename": "bad name.mp3", "format": "wav"},
            )

        self.assertEqual(400, response.status_code)
        self.assertEqual("Invalid filename", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
