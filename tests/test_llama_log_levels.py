import logging
import sys
import unittest
from pathlib import Path


SPIKE_ROOT = Path(__file__).resolve().parents[2] / "vulkan_backend_spike" / "Qwen3-TTS-GGUF"
sys.path.insert(0, str(SPIKE_ROOT))

from qwen3_tts_gguf.inference import llama  # noqa: E402


class LlamaLogLevelTests(unittest.TestCase):
    def setUp(self) -> None:
        llama._last_log_level = logging.INFO

    def assert_callback_level(self, ggml_level: int, logging_level: int) -> None:
        with self.assertLogs("qwen3_tts_gguf", level=logging.DEBUG) as captured:
            llama.logger_callback(ggml_level, b"probe", None)

        self.assertEqual(logging_level, captured.records[-1].levelno)
        self.assertEqual("[llama.cpp] probe", captured.records[-1].getMessage())

    def test_standard_ggml_levels_map_to_python_logging(self) -> None:
        for ggml_level, logging_level in (
            (1, logging.DEBUG),
            (2, logging.INFO),
            (3, logging.WARNING),
            (4, logging.ERROR),
        ):
            with self.subTest(ggml_level=ggml_level):
                self.assert_callback_level(ggml_level, logging_level)

    def test_continuation_reuses_previous_level(self) -> None:
        with self.assertLogs("qwen3_tts_gguf", level=logging.DEBUG) as captured:
            llama.logger_callback(4, b"error start", None)
            llama.logger_callback(5, b"error continuation", None)

        self.assertEqual([logging.ERROR, logging.ERROR], [r.levelno for r in captured.records])
        self.assertTrue(captured.records[1].getMessage().startswith("[llama.cpp] "))

    def test_unknown_levels_fall_back_to_info(self) -> None:
        for ggml_level in (0, 9):
            with self.subTest(ggml_level=ggml_level):
                self.assert_callback_level(ggml_level, logging.INFO)

    def test_empty_and_dot_messages_are_filtered(self) -> None:
        with self.assertLogs("qwen3_tts_gguf", level=logging.DEBUG) as captured:
            llama.logger_callback(2, b"kept", None)
            llama.logger_callback(2, b"", None)
            llama.logger_callback(2, b".", None)

        self.assertEqual(1, len(captured.records))
        self.assertEqual("[llama.cpp] kept", captured.records[0].getMessage())


if __name__ == "__main__":
    unittest.main()
