import unittest
from unittest.mock import patch

from flask import Flask

import tts_routes
from local_tts_engine import LocalTTSBusyError


class FakeTTSService:
    def __init__(self, *, busy=False, group_count=None):
        self.busy = busy
        self.group_count = group_count
        self.calls = []
        self.group_count_calls = []

    def synthesize_text(self, text, voice, instruct="", progress_callback=None):
        self.calls.append((text, voice, instruct))
        if self.busy:
            raise LocalTTSBusyError("engine busy")
        return "fake.mp3"

    def count_long_groups(self, text):
        self.group_count_calls.append(text)
        return self.group_count


class Phase5ETARouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(tts_routes.tts_bp)
        self.client = self.app.test_client()
        self.original_service = tts_routes.service
        tts_routes.service = FakeTTSService()
        tts_routes._SYSTEM_INFO_CACHE = None
        tts_routes._BENCHMARK_FUTURE = None

    def tearDown(self):
        tts_routes.service = self.original_service
        tts_routes._SYSTEM_INFO_CACHE = None
        tts_routes._BENCHMARK_FUTURE = None

    def test_system_info_returns_backend_chip_payload(self):
        with patch.dict("os.environ", {"USE_GGUF_BACKEND": "1"}, clear=False):
            with patch("tts_routes._probe_cache_key", return_value={
                "gpu_vendor": "amd",
                "gpu_device_identity": "Radeon RX 590",
            }):
                response = self.client.get("/api/system-info")

        self.assertEqual(200, response.status_code)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual("gguf", data["backend"])
        self.assertEqual("AMD 显卡加速", data["friendly_label_zh"])
        self.assertFalse(data["is_cpu_mode"])

    def test_benchmark_runs_service_path_and_returns_rough_metrics(self):
        with patch("tts_routes._kernel_stream_chunk_count", return_value=2):
            with patch("tts_routes._read_audio_duration_seconds", return_value=3.0):
                response = self.client.post(
                    "/api/benchmark",
                    json={"voice": "serena", "instruct": "用开心的语气说"},
                )

        self.assertEqual(200, response.status_code)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual("serena", data["voice"])
        self.assertEqual(2, data["chunk_count"])
        self.assertGreater(data["per_char_seconds"], 0)
        self.assertTrue(data["warmup_excluded"])
        self.assertGreater(data["warmup_seconds"], 0)
        self.assertTrue(data["is_rough_estimate"])
        self.assertEqual(
            [
                (tts_routes.BENCHMARK_WARMUP_TEXT, "serena", "用开心的语气说"),
                (tts_routes.BENCHMARK_TEXT, "serena", "用开心的语气说"),
            ],
            tts_routes.service.calls,
        )

    def test_benchmark_reports_busy_as_conflict(self):
        tts_routes.service = FakeTTSService(busy=True)

        response = self.client.post("/api/benchmark", json={"voice": "serena"})

        self.assertEqual(409, response.status_code)

    def test_estimate_returns_reference_rows_from_benchmark(self):
        with patch("tts_routes._kernel_stream_chunk_count", return_value=4):
            with patch("tts_routes._system_info_payload", return_value={
                "backend": "gguf",
                "model_default": "Qwen3-TTS-12Hz-1.7B-CustomVoice",
                "is_cpu_mode": False,
            }):
                response = self.client.post(
                    "/api/estimate",
                    json={
                        "text": "你好，欢迎使用巴适声工厂。",
                        "benchmark": {"per_char_seconds": 0.5},
                        "include_references": True,
                    },
                )

        self.assertEqual(200, response.status_code)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data["has_benchmark"])
        self.assertEqual(4, data["chunk_count"])
        self.assertEqual([1000, 5000], [row["char_count"] for row in data["references"]])
        self.assertTrue(data["estimate"]["is_rough_estimate"])

    def test_long_estimate_adds_group_count_without_changing_chunk_count(self):
        text = "你好，欢迎使用巴适声工厂。"
        tts_routes.service = FakeTTSService(group_count=2)
        with patch("tts_routes._kernel_stream_chunk_count", return_value=5):
            with patch("tts_routes._system_info_payload", return_value={
                "backend": "gguf",
                "model_default": "Qwen3-TTS-12Hz-1.7B-CustomVoice",
                "is_cpu_mode": False,
            }):
                response = self.client.post(
                    "/api/estimate",
                    json={
                        "text": text,
                        "benchmark": {"per_chunk_seconds": 1.0},
                        "synthesis_mode": "long",
                    },
                )

        self.assertEqual(200, response.status_code)
        data = response.get_json()
        self.assertEqual(5, data["chunk_count"])
        self.assertEqual(2, data["group_count"])
        self.assertEqual(5.0, data["estimate"]["mid"]["seconds"])
        self.assertEqual([text], tts_routes.service.group_count_calls)

    def test_long_estimate_allows_backend_without_group_count(self):
        tts_routes.service = FakeTTSService(group_count=None)
        with patch("tts_routes._kernel_stream_chunk_count", return_value=4):
            with patch("tts_routes._system_info_payload", return_value={
                "backend": "pytorch",
                "model_default": "Qwen3-TTS-12Hz-1.7B-CustomVoice",
                "is_cpu_mode": True,
            }):
                response = self.client.post(
                    "/api/estimate",
                    json={"text": "Long text", "synthesis_mode": "long"},
                )

        self.assertEqual(200, response.status_code)
        data = response.get_json()
        self.assertEqual(4, data["chunk_count"])
        self.assertIsNone(data["group_count"])

    def test_non_long_estimate_does_not_request_group_count(self):
        tts_routes.service = FakeTTSService(group_count=3)
        with patch("tts_routes._kernel_stream_chunk_count", return_value=1):
            with patch("tts_routes._system_info_payload", return_value={
                "backend": "gguf",
                "model_default": "Qwen3-TTS-12Hz-1.7B-CustomVoice",
                "is_cpu_mode": False,
            }):
                response = self.client.post(
                    "/api/estimate",
                    json={"text": "Short text", "synthesis_mode": "single"},
                )

        self.assertEqual(200, response.status_code)
        self.assertIsNone(response.get_json()["group_count"])
        self.assertEqual([], tts_routes.service.group_count_calls)


if __name__ == "__main__":
    unittest.main()
