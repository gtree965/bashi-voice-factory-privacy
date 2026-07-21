from pathlib import Path


DEFAULT_CONFUSION_PATH = Path(__file__).resolve().parent / "data" / "zh_confusion.tsv"
_CACHE: dict[Path, tuple[int | None, tuple[tuple[str, str], ...]]] = {}


def _contains_cjk(text: str) -> bool:
    return any(
        "\u4e00" <= ch <= "\u9fff"
        or "\u3040" <= ch <= "\u30ff"
        or "\uac00" <= ch <= "\ud7af"
        for ch in text
    )


def load_zh_confusions(path: Path | None = None) -> tuple[tuple[str, str], ...]:
    """Load user-editable wrong/right pairs sorted for longest-match replacement."""
    table_path = Path(path) if path is not None else DEFAULT_CONFUSION_PATH
    try:
        stat = table_path.stat()
    except OSError:
        return ()

    cached = _CACHE.get(table_path)
    if cached and cached[0] == stat.st_mtime_ns:
        return cached[1]

    pairs: list[tuple[str, str]] = []
    for raw_line in table_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" not in line:
            continue
        wrong, correct = (part.strip() for part in line.split("\t", 1))
        if wrong and correct and wrong != correct:
            pairs.append((wrong, correct))

    entries = tuple(sorted(pairs, key=lambda pair: (-len(pair[0]), pair[0])))
    _CACHE[table_path] = (stat.st_mtime_ns, entries)
    return entries


def apply_zh_confusions(text: str, path: Path | None = None) -> str:
    """Apply the static Chinese STT confusion table without model-based rewriting."""
    if not text or not _contains_cjk(text):
        return text

    corrected = text
    for wrong, correct in load_zh_confusions(path):
        corrected = corrected.replace(wrong, correct)
    return corrected
