import unittest

from local_tts_engine_gguf import service as gguf_service
from tts_routes import split_into_chunks, split_long_sentence


# Neutral classical-prose fixture (no religious content) used to exercise the
# chunking pipeline: full-width-space stripping, full-width semicolon as a
# sentence boundary, closing-quote attachment, classical chapter:verse
# normalization, and long-chunk coalescing. Sentence lengths are chosen so the
# 12 sentences coalesce into 4 stable groups (triples sum 34/38/43/20 chars
# against GGUF_LONG_MIN_CHARS=30).
CLASSICAL_SAMPLE = (
    "太初之时，天地浑然未分。清气上升，浊气下沉；　于是上下始判，乾坤乃定。"
    "山岳隆起，江河顺势而流。草木萌发于野，鸟兽栖息于林。四时更替，寒暑往来不息。"
    "昼则日照，夜则月明。古人云：“天行有常，地载万物。”　世人观之，遂明岁序之理，知天地之广大。"
    "春去秋来。寒来暑往。万象更新，生生不息。【 古书1:1-8】"
)

CLEAN_CLASSICAL_SAMPLE = (
    "太初之时，天地浑然未分。"
    "清气上升，浊气下沉；"
    "于是上下始判，乾坤乃定。"
    "山岳隆起，江河顺势而流。"
    "草木萌发于野，鸟兽栖息于林。"
    "四时更替，寒暑往来不息。"
    "昼则日照，夜则月明。"
    "古人云：天行有常，地载万物。"
    "世人观之，遂明岁序之理，知天地之广大。"
    "春去秋来。"
    "寒来暑往。"
    "万象更新，生生不息。"
)

LONG_SEMICOLON_SAMPLE = (
    "这是一段用于验证长文本递归终止的内容，它包含足够多的中文字符，并且以全角分号结束；"
    * 16
)


class TextChunkingTests(unittest.TestCase):
    def test_overlong_cjk_sentence_ending_in_fullwidth_semicolon_is_hard_split(self) -> None:
        sentence = "甲" * 39 + "；"

        chunks = split_long_sentence(sentence, limit=30, is_cjk=True)

        self.assertEqual(["甲" * 30, "甲" * 9 + "；"], chunks)
        self.assertTrue(all(len(chunk) <= 30 for chunk in chunks))

    def test_overlong_cjk_sentence_ending_in_ascii_semicolon_is_hard_split(self) -> None:
        sentence = "甲" * 39 + ";"

        chunks = split_long_sentence(sentence, limit=30, is_cjk=True)

        self.assertEqual(["甲" * 30, "甲" * 9 + ";"], chunks)
        self.assertTrue(all(len(chunk) <= 30 for chunk in chunks))

    def test_overlong_cjk_sentence_ending_in_full_stop_keeps_existing_split(self) -> None:
        sentence = "甲" * 39 + "。"

        chunks = split_long_sentence(sentence, limit=30, is_cjk=True)

        self.assertEqual(["甲" * 30, "甲" * 9 + "。"], chunks)
        self.assertTrue(all(len(chunk) <= 30 for chunk in chunks))

    def test_overlong_cjk_sentence_with_internal_semicolon_keeps_existing_split(self) -> None:
        sentence = "甲" * 20 + "；" + "乙" * 18 + "。"

        chunks = split_long_sentence(sentence, limit=30, is_cjk=True)

        self.assertEqual(["甲" * 20 + "；", "乙" * 18 + "。"], chunks)
        self.assertTrue(all(len(chunk) <= 30 for chunk in chunks))

    def test_600_character_text_with_semicolon_clauses_terminates(self) -> None:
        self.assertGreater(len(LONG_SEMICOLON_SAMPLE), 600)

        chunks = split_into_chunks(
            LONG_SEMICOLON_SAMPLE,
            max_words=15,
            newline_hard=True,
        )

        self.assertGreater(len(chunks), 1)
        self.assertEqual(LONG_SEMICOLON_SAMPLE, "".join(chunks))
        self.assertTrue(all(len(chunk) <= 30 for chunk in chunks))

    def test_fullwidth_semicolon_is_a_sentence_boundary(self) -> None:
        chunks = split_into_chunks(CLASSICAL_SAMPLE, max_words=15, newline_hard=True)

        self.assertIn("清气上升，浊气下沉；", chunks)
        self.assertIn("于是上下始判，乾坤乃定。", chunks)

    def test_closing_quote_stays_with_previous_sentence(self) -> None:
        chunks = split_into_chunks(CLASSICAL_SAMPLE, max_words=15, newline_hard=True)

        self.assertIn("古人云：“天行有常，地载万物。”", chunks)
        self.assertNotIn("”　世人观之，遂明岁序之理，知天地之广大。", chunks)

    def test_gguf_long_chunk_tts_text_is_sanitized(self) -> None:
        self.assertEqual(
            "远山名为翠。",
            gguf_service._prepare_long_chunk_text("　远山名为“翠”。"),
        )
        self.assertEqual("", gguf_service._prepare_long_chunk_text("【 古书1:1-8】"))

    def test_gguf_adapter_normalizes_before_chunking(self) -> None:
        chunks = gguf_service._normalize_and_split_chunks(split_into_chunks(
            CLASSICAL_SAMPLE,
            max_words=15,
            newline_hard=True,
        ))

        self.assertIn("【 古书第一章第一节至第八节】", chunks)
        self.assertNotIn("【 古书1:1-8】", chunks)

    def test_gguf_long_chunks_are_coalesced_for_custom_voice_stability(self) -> None:
        split_chunks = gguf_service._split_long_text(CLEAN_CLASSICAL_SAMPLE)
        groups = gguf_service._coalesce_long_chunks(split_chunks)

        self.assertEqual(12, len(split_chunks))
        self.assertEqual(4, len(groups))
        self.assertIn("清气上升，浊气下沉；于是上下始判，乾坤乃定。", groups[0])
        self.assertNotIn("清气上升，浊气下沉；", groups)
        self.assertIn("世人观之，遂明岁序之理，知天地之广大。", groups[2])
        self.assertIn("万象更新，生生不息。", groups[3])


if __name__ == "__main__":
    unittest.main()
