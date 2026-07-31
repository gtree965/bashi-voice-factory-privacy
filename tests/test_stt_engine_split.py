import unittest

from engines.sherpa_parakeet import SherpaParakeetEngine
from engines.sherpa_sensevoice import SherpaSenseVoiceEngine
from stt_engine import Segment


class SttEngineSplitGoldenTests(unittest.TestCase):
    def test_sensevoice_cjk_split_is_byte_stable(self):
        text = "人工智能正在改变世界，这是一个很长的测试句子，需要验证字幕切分是否保持稳定。最后一句！"

        actual = SherpaSenseVoiceEngine._split_text_into_segments(
            text,
            start_sec=1.25,
            end_sec=11.25,
            language="zh",
            base_index=7,
            char_limit=20,
        )

        self.assertEqual(
            actual,
            [
                Segment(7, 1.25, 3.808, "人工智能正在改变世界，", "zh"),
                Segment(8, 3.808, 6.599, "这是一个很长的测试句子，", "zh"),
                Segment(9, 6.599, 10.087, "需要验证字幕切分是否保持稳定。", "zh"),
                Segment(10, 10.087, 11.25, "最后一句！", "zh"),
            ],
        )

    def test_parakeet_english_split_is_byte_stable(self):
        text = (
            "This is the first sentence. This is a deliberately long second "
            "sentence, with enough words to cross the eighty character limit "
            "safely. Final words!"
        )

        actual = SherpaParakeetEngine._split_text_into_segments(
            text,
            start_sec=2.5,
            end_sec=22.5,
            language="en",
            base_index=3,
            char_limit=80,
        )

        self.assertEqual(
            actual,
            [
                Segment(3, 2.5, 6.173, "This is the first sentence.", "en"),
                Segment(
                    4,
                    6.173,
                    12.296,
                    "This is a deliberately long second sentence,",
                    "en",
                ),
                Segment(
                    5,
                    12.296,
                    20.731,
                    "with enough words to cross the eighty character limit safely.",
                    "en",
                ),
                Segment(6, 20.731, 22.5, "Final words!", "en"),
            ],
        )

    def test_sensevoice_punctuation_filter_is_pinned(self):
        cases = {
            "": True,
            "  ...？！—【】": True,
            "你好！": False,
            "A?": False,
        }

        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(
                    SherpaSenseVoiceEngine._is_punctuation_only(text),
                    expected,
                )


if __name__ == "__main__":
    unittest.main()
