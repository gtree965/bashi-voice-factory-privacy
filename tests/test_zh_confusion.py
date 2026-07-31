import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import engines.sherpa_sensevoice as sensevoice
from zh_confusion import apply_zh_confusions, load_zh_confusions


class ZhConfusionTests(unittest.TestCase):
    def _write_table(self, content: str) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "zh_confusion.tsv"
        path.write_text(content, encoding="utf-8")
        return path

    def test_loads_tsv_comments_and_sorts_longest_first(self):
        path = self._write_table(
            "# disabled\tentry\n"
            "智普\t智谱\n"
            "通义千文\t通义千问\n"
            "通义\t通义\n"
        )

        self.assertEqual(
            load_zh_confusions(path),
            (("通义千文", "通义千问"), ("智普", "智谱")),
        )

    def test_applies_static_table_without_disabled_dangerous_entries(self):
        path = self._write_table(
            "智普\t智谱\n"
            "通义千文\t通义千问\n"
            "# 一考\t艺考\n"
        )

        self.assertEqual(
            apply_zh_confusions("智普发布通义千文，一考成绩另行通知。", path),
            "智谱发布通义千问，一考成绩另行通知。",
        )

    def test_skips_non_cjk_text(self):
        path = self._write_table("AI\t人工智能\n")

        self.assertEqual(apply_zh_confusions("AI benchmark", path), "AI benchmark")

    def test_sensevoice_corrects_before_subtitle_splitting(self):
        engine = sensevoice.SherpaSenseVoiceEngine(Path("models/sensevoice-small-int8"))
        result = Mock()
        result.text = "智普发布通义千文。"
        stream = Mock()
        stream.result = result

        with patch.object(engine, "is_loaded", return_value=True), \
                patch("wave.open") as wave_open, \
                patch("stt_engine.sherpa_onnx") as sherpa, \
                patch("engines.sherpa_sensevoice.apply_zh_confusions", return_value="智谱发布通义千问。") as correct:
            wave_open.return_value.__enter__.return_value.getframerate.return_value = 16000
            wave_open.return_value.__enter__.return_value.getnchannels.return_value = 1
            wave_open.return_value.__enter__.return_value.getsampwidth.return_value = 2
            wave_open.return_value.__enter__.return_value.getnframes.return_value = 16000
            wave_open.return_value.__enter__.return_value.readframes.return_value = b"\0" * 32000

            vad_config = Mock()
            vad_config.silero_vad = Mock()
            vad_config.silero_vad.window_size = 512
            sherpa.VadModelConfig.return_value = vad_config
            vad = Mock()
            vad.empty.side_effect = [False, True]
            vad.front.start = 0
            vad.front.samples = [0.0] * 16000
            sherpa.VoiceActivityDetector.return_value = vad
            engine._recognizer = Mock()
            engine._recognizer.create_stream.return_value = stream

            segments = list(engine.transcribe_stream(Path("clip.wav"), language="zh"))

        correct.assert_called_once_with("智普发布通义千文。")
        self.assertEqual([segment.text for segment in segments], ["智谱发布通义千问。"])


if __name__ == "__main__":
    unittest.main()
