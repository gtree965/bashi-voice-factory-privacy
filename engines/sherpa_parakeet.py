from typing import List

try:
    import sherpa_onnx
except ImportError:
    sherpa_onnx = None

from stt_engine import Segment, SttEngine


class SherpaParakeetEngine(SttEngine):
    """STT engine using sherpa-onnx with NeMo Parakeet TDT 0.6B model + Silero VAD.

    Parakeet is NVIDIA's state-of-the-art English ASR model (FastConformer +
    Token-and-Duration Transducer). It outputs punctuation, capitalization,
    and achieves ~1.7% WER on LibriSpeech clean English.

    Uses Silero VAD to split audio into speech segments to avoid OOM on long
    audio, then transcribes each segment with Parakeet.
    """

    VAD_THRESHOLD = 0.3
    CHAR_LIMIT = 80
    ENGINE_LABEL = "Parakeet"

    def load_model(self):
        """Load Parakeet TDT transducer model (encoder + decoder + joiner)."""
        if sherpa_onnx is None:
            raise ImportError(
                "sherpa-onnx not installed. "
                "Run: pip install sherpa-onnx"
            )

        encoder_path = self.model_dir / "encoder.int8.onnx"
        decoder_path = self.model_dir / "decoder.int8.onnx"
        joiner_path = self.model_dir / "joiner.int8.onnx"
        tokens_path = self.model_dir / "tokens.txt"

        if not encoder_path.exists():
            raise FileNotFoundError(
                f"Model not found: {encoder_path}\n"
                "Please download the model first via Model Manager."
            )

        self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(encoder_path),
            decoder=str(decoder_path),
            joiner=str(joiner_path),
            tokens=str(tokens_path),
            num_threads=self.num_threads,
            sample_rate=16000,
            feature_dim=80,
            decoding_method="modified_beam_search",
            max_active_paths=4,
            model_type="nemo_transducer",
            debug=False,
        )

        self._model = True  # Mark as loaded

    @staticmethod
    def _split_text_into_segments(text: str, start_sec: float, end_sec: float,
                                   language: str, base_index: int,
                                   char_limit: int = 80) -> list:
        """Split long text into subtitle-sized segments with proportional timestamps.

        For English, we split on sentence boundaries and word boundaries
        with a higher character limit than CJK models.
        """
        if not text:
            return []

        duration = end_sec - start_sec
        total_chars = len(text)
        if total_chars == 0:
            return []

        # For English, split at sentence-ending punctuation or word boundaries
        end_punctuations = {'.', '!', '?', ';'}
        soft_punctuations = {',', ':', '—', '–'}

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
            elif ch in end_punctuations and i + 1 < len(text) and text[i + 1] == ' ':
                should_break = True
            elif ch in soft_punctuations and len(current) >= (char_limit * 0.5):
                should_break = True
            elif ch == ' ' and len(current) >= char_limit:
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

    def supported_languages(self) -> List[str]:
        return ["en"]
