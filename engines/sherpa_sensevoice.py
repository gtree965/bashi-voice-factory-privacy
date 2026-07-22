import re
from typing import List

try:
    import sherpa_onnx
except ImportError:
    sherpa_onnx = None

from stt_engine import Segment, SttEngine
from zh_confusion import apply_zh_confusions


class SherpaSenseVoiceEngine(SttEngine):
    """STT engine using sherpa-onnx with SenseVoice model + Silero VAD.

    Uses VAD to split audio into speech segments, then transcribes each
    segment with SenseVoice. This eliminates chunk-boundary overlap and
    stuttering issues while providing accurate timestamps from VAD.
    """

    VAD_THRESHOLD = 0.5
    CHAR_LIMIT = 20
    ENGINE_LABEL = "SenseVoice"

    def load_model(self):
        """Load SenseVoice model."""
        if sherpa_onnx is None:
            raise ImportError(
                "sherpa-onnx not installed. "
                "Run: pip install sherpa-onnx"
            )

        model_path = self.model_dir / "model.int8.onnx"
        tokens_path = self.model_dir / "tokens.txt"

        if not model_path.exists():
            raise FileNotFoundError(
                f"Model not found: {model_path}\n"
                "Please download the model first via Model Manager."
            )

        self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model_path),
            tokens=str(tokens_path),
            num_threads=self.num_threads,
            use_itn=True,
            debug=False,
        )

        self._model = True  # Mark as loaded

    @staticmethod
    def _is_punctuation_only(text: str) -> bool:
        """Check if text consists only of punctuation/whitespace."""
        cleaned = re.sub(r'[\s\.,!?;:，。！？；：、\-—–\'"""\'\'()\[\]（）【】「」《》\u200b]', '', text)
        return len(cleaned) == 0

    @staticmethod
    def _split_text_into_segments(text: str, start_sec: float, end_sec: float,
                                   language: str, base_index: int,
                                   char_limit: int = 20) -> list:
        """Split long text into subtitle-sized segments with proportional timestamps."""
        if not text:
            return []

        duration = end_sec - start_sec
        total_chars = len(text)
        if total_chars == 0:
            return []

        end_punctuations = {'。', '！', '？', '；', '.', '!', '?', ';'}
        soft_punctuations = {'，', '、', '：', ',', ':', '—', '–'}

        lines = []
        current = []
        current_start_char = 0

        for i, ch in enumerate(text):
            current.append(ch)
            current_text = ''.join(current)
            is_last = (i == len(text) - 1)

            should_break = False
            if is_last:
                should_break = True
            elif ch in end_punctuations:
                should_break = True
            elif ch in soft_punctuations and len(current) >= (char_limit * 0.5):
                should_break = True
            elif len(current) >= char_limit:
                should_break = True

            if should_break and current_text.strip():
                seg_start = start_sec + (current_start_char / total_chars) * duration
                seg_end = start_sec + ((i + 1) / total_chars) * duration

                if seg_end - seg_start < 0.2:
                    seg_end = seg_start + 0.3

                lines.append(Segment(
                    index=base_index + len(lines),
                    start=round(seg_start, 3),
                    end=round(seg_end, 3),
                    text=current_text.strip(),
                    language=language,
                ))
                current = []
                current_start_char = i + 1

        return lines

    def _postprocess_text(self, text: str) -> str:
        text = apply_zh_confusions(text)
        return "" if (not text or self._is_punctuation_only(text)) else text

    def supported_languages(self) -> List[str]:
        return ["auto", "zh", "en", "ja", "ko", "yue"]
