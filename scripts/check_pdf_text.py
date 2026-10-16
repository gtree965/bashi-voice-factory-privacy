"""Check extracted user-guide text with the maintainer's local publication rules."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/git-hooks"))
from pre_commit_guard import GuardError, TRACE_TEXT, contains_term, load_terms  # noqa: E402


def check(pdf_path: Path, terms_path: Path | None = None) -> tuple[list[str], list[str]]:
    from pypdf import PdfReader

    terms = load_terms(ROOT, terms_path)
    pages = [(page.extract_text() or "") for page in PdfReader(pdf_path).pages]
    problems = []
    if not pages:
        problems.append("No pages were extracted.")
    for number, text in enumerate(pages, 1):
        if not text.strip():
            problems.append(f"Page {number}: no readable text; review the rendered page.")
        if "\ufffd" in text or any(unicodedata.category(c) == "Co" for c in text):
            problems.append(f"Page {number}: undecoded characters; review the rendered page.")
        normalized = unicodedata.normalize("NFKC", text)
        if contains_term(normalized, terms):
            problems.append(f"Page {number}: local publication term (value withheld).")
        if TRACE_TEXT.search(normalized):
            problems.append(f"Page {number}: publication residue (value withheld).")
    return problems, pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--terms-file", type=Path)
    parser.add_argument("--text-out", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        problems, pages = check(args.pdf, args.terms_file)
    except (GuardError, OSError, ImportError, ValueError) as exc:
        print(f"PDF text check could not complete: {type(exc).__name__}.", file=sys.stderr)
        return 1
    if args.text_out:
        args.text_out.write_text("\n\n".join(f"--- page {i} ---\n{text}" for i, text in enumerate(pages, 1)), encoding="utf-8")
    if args.report:
        import hashlib
        import pypdf
        args.report.write_text(json.dumps({
            "pdf_sha256": hashlib.sha256(args.pdf.read_bytes()).hexdigest(),
            "extractor": "pypdf", "extractor_version": pypdf.__version__,
            "page_characters": [len(text) for text in pages], "problems": problems,
            "render_review_still_required": True,
        }, indent=2) + "\n", encoding="ascii")
    if problems:
        print("PDF text check failed:\n- " + "\n- ".join(problems), file=sys.stderr)
        return 1
    print(f"PDF text check passed: {len(pages)} pages. Review the rendered pages before release.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
