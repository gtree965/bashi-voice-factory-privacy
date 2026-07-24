import re

from speaker_diarization import speaker_label


_FULL_WIDTH_SPACE = "\u3000"
_PROTECTED_PATTERNS = re.compile(
    r"(https?://\S+|www\.\S+|"
    r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+(?:/[A-Za-z0-9_./%-]*)?|"
    r"(?<!\d)\d{1,2}:\d{2}(?::\d{2})?(?!\d)|"
    r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|"
    r"\b\d+\.\d+\b)"
)
_MULTI_SPACE_RE = re.compile(r" +")
_MULTI_FWS_RE = re.compile(rf"{_FULL_WIDTH_SPACE}+")
_SPACE_AROUND_FWS_RE = re.compile(rf" *{_FULL_WIDTH_SPACE} *")


def format_timestamp(seconds: float, separator: str = ",") -> str:
    """Format seconds into HH:MM:SS,mmm or HH:MM:SS.mmm."""
    ms = int((seconds % 1) * 1000)
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{ms:03d}"


def _is_cjk(text: str) -> bool:
    """Check if text is predominantly CJK (Chinese/Japanese/Korean)."""
    for char in text:
        if (
            "\u4e00" <= char <= "\u9fff"
            or "\u3040" <= char <= "\u30ff"
            or "\uac00" <= char <= "\ud7af"
        ):
            return True
    return False


def _smooth_join(buf_text: str, seg_text: str) -> str:
    """Join two subtitle texts, smoothing punctuation at the boundary."""
    if not buf_text or not seg_text:
        return (buf_text or "") + (seg_text or "")

    buf_stripped = buf_text.rstrip()
    cjk = _is_cjk(buf_stripped) or _is_cjk(seg_text)
    if cjk:
        return buf_stripped + seg_text

    first_alpha = next((char for char in seg_text if char.isalpha()), "")
    if buf_stripped and buf_stripped[-1] in ".!?":
        starts_lower = first_alpha.islower()
        ends_question = buf_stripped[-1] == "?"
        if starts_lower or ends_question:
            buf_clean = buf_stripped[:-1].rstrip()
            seg_clean = (
                seg_text[0].lower() + seg_text[1:]
                if seg_text[0].isupper()
                else seg_text
            )
            return buf_clean + " " + seg_clean

    return buf_text + " " + seg_text


def _has_speaker(segment: dict) -> bool:
    return segment.get("speaker") is not None


def _format_speaker_prefix(segment: dict, ui_lang: str = "en") -> str:
    if not _has_speaker(segment):
        return ""
    return f"{speaker_label(int(segment['speaker']), ui_lang)}: "


def _format_segment_text(
    segment: dict,
    text: str | None = None,
    ui_lang: str = "en",
) -> str:
    body = segment.get("text", "") if text is None else text
    return _format_speaker_prefix(segment, ui_lang) + body


def merge_short_segments(segments: list, max_duration: float = 7.0) -> list:
    """Merge short subtitle fragments into reader-friendly cards."""
    if not segments:
        return segments

    first_text = next((segment["text"] for segment in segments if segment.get("text")), "")
    cjk = _is_cjk(first_text)
    char_limit = 40 if cjk else 80
    buf_short_limit = 6 if cjk else 42
    seg_tiny_limit = 4 if cjk else 20
    merged = [dict(segments[0])]

    for segment in segments[1:]:
        buf = merged[-1]
        buf_chars = len(buf["text"])
        buf_duration = buf["end"] - buf["start"]
        segment_chars = len(segment["text"])
        segment_duration = segment["end"] - segment["start"]
        gap = segment["start"] - buf["end"]
        combined = _smooth_join(buf["text"], segment["text"])
        combined_duration = segment["end"] - buf["start"]

        buf_short = buf_chars < buf_short_limit or buf_duration < 1.5
        segment_tiny = segment_chars < seg_tiny_limit or segment_duration < 0.8
        fits = len(combined) <= char_limit
        close = gap < 1.5
        duration_ok = combined_duration <= max_duration
        same_speaker = (
            not _has_speaker(buf)
            or not _has_speaker(segment)
            or buf.get("speaker") == segment.get("speaker")
        )

        if same_speaker and (buf_short or segment_tiny) and fits and close and duration_ok:
            merged_segment = {
                "start": buf["start"],
                "end": segment["end"],
                "text": combined,
                "index": buf["index"],
            }
            for key in ("language", "speaker", "speaker_label"):
                if key in buf:
                    merged_segment[key] = buf[key]
                elif key in segment:
                    merged_segment[key] = segment[key]
            merged[-1] = merged_segment
        else:
            merged.append(dict(segment))

    for index, segment in enumerate(merged):
        segment["index"] = index

    return merged


def normalize_subtitle_text(text: str) -> str:
    """Normalize CJK subtitle punctuation while preserving protected text."""
    if not text:
        return text

    cjk_punctuation_chars = set("，。！？；：、《》【】「」『』〈〉〔〕“”‘’·…—–")
    punctuation_chars = cjk_punctuation_chars | set(
        ",.!?;:()[]{}<>"
        "\"`/\\|_+=*&^%$#@~-"
    )

    if not _is_cjk(text) and not any(char in cjk_punctuation_chars for char in text):
        return text

    def is_word_internal_apostrophe(value: str, index: int) -> bool:
        if value[index] != "'":
            return False
        if index == 0 or index == len(value) - 1:
            return False
        return (
            value[index - 1].isascii()
            and value[index - 1].isalnum()
            and value[index + 1].isascii()
            and value[index + 1].isalnum()
        )

    def next_visible_char(value: str, start_index: int) -> str:
        for char in value[start_index:]:
            if not char.isspace():
                return char
        return ""

    protected = {}

    def protect_match(match: re.Match) -> str:
        key = f"\uFFF0{len(protected)}\uFFF1"
        protected[key] = match.group(0)
        return key

    text = _PROTECTED_PATTERNS.sub(protect_match, text)

    output = []
    for index, char in enumerate(text):
        if char == "'" and is_word_internal_apostrophe(text, index):
            output.append(char)
            continue

        if char in punctuation_chars:
            next_char = next_visible_char(text, index + 1)
            if next_char:
                output.append(_FULL_WIDTH_SPACE)
            continue

        output.append(char)

    cleaned = "".join(output)
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned)
    cleaned = _MULTI_FWS_RE.sub(_FULL_WIDTH_SPACE, cleaned)
    cleaned = _SPACE_AROUND_FWS_RE.sub(_FULL_WIDTH_SPACE, cleaned)
    cleaned = cleaned.strip(" " + _FULL_WIDTH_SPACE)
    for key, value in protected.items():
        cleaned = cleaned.replace(key, value)
    return cleaned


def fix_timestamp_overlaps(segments: list) -> list:
    """Remove timestamp overlaps and re-index segments sequentially."""
    if not segments:
        return segments

    fixed = []
    for index, segment in enumerate(segments):
        new_segment = dict(segment)
        if index + 1 < len(segments):
            next_start = segments[index + 1]["start"]
            if new_segment["end"] > next_start:
                new_segment["end"] = next_start
        if new_segment["end"] <= new_segment["start"]:
            new_segment["end"] = new_segment["start"] + 0.01
        new_segment["index"] = index
        fixed.append(new_segment)

    return fixed
