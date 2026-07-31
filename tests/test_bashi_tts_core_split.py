import sys
import unittest
from pathlib import Path


KERNEL_ROOT = Path(__file__).resolve().parents[2] / "LocalBashiVoiceFactory"
if str(KERNEL_ROOT) not in sys.path:
    sys.path.insert(0, str(KERNEL_ROOT))

from bashi_tts_core import BashiTTSEngine  # noqa: E402


class BashiTTSCoreSplitTests(unittest.TestCase):
    def split(self, text: str) -> list[str]:
        return BashiTTSEngine._split_stream_text(object(), text, max_chars=20)

    def test_korean_text_produces_stream_chunks(self) -> None:
        chunks = self.split("안녕하세요! Bashi Voice Factory에 오신 것을 환영합니다.")

        self.assertGreaterEqual(len(chunks), 2)
        self.assertIn("안녕하세요!", chunks)
        self.assertIn("Bashi Voice Factory에 오신 것을 환영합니다.", chunks)

    def test_latin_text_produces_stream_chunks(self) -> None:
        chunks = self.split(
            "Hallo! Willkommen im Bashi Voice Factory. "
            "Dies ist eine Demonstration hochwertiger Sprachsynthese."
        )

        self.assertGreaterEqual(len(chunks), 3)
        self.assertEqual("Hallo!", chunks[0])

    def test_text_without_sentence_ending_is_not_dropped(self) -> None:
        self.assertEqual(
            ["Hello without sentence ending"],
            self.split("Hello without sentence ending"),
        )


if __name__ == "__main__":
    unittest.main()
