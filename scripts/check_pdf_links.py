"""Release gate for the bundled PDF user guide.

Releases v0.1.1-v0.1.3 shipped a manual whose internal LICENSE / VERSION links
had been resolved against the build machine, producing dead links such as
``file:///C:/Users/<user>/...`` or ``http://markdownpanel-virtualhost/LICENSE``.
The two forms come from different PDF generators but share one cause: relative
links in the source HTML. Checking only for ``file:`` therefore misses the
problem, so every link must be an explicit public HTTPS address.

An HTTPS prefix alone is not enough either: ``https://example.com/C:/Users/...``
and a link to a retired download host are both well-formed HTTPS. Link targets
are therefore decoded and then held to the same content policy as the raw bytes.
PDF hexadecimal strings decode to text that never appears literally in the file,
so a raw scan alone cannot see them.

Exit status 0 means the file is safe to ship. Any other status blocks packaging.
The check fails closed: if the parser is unavailable the answer is "no", never
"probably fine".
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ALLOWED_MAILTO = "mailto:ncorecpu@gmail.com"

# Content that must never reach a reader, wherever it appears: build-machine
# paths, temporary directories, retired download entries, AI tool names and
# session UUIDs. It is applied in three places because each catches what the
# others miss - raw bytes, decoded link targets, and document metadata.
#
# "copilot" carries a negative lookahead: "Snapdragon X Copilot+ PC" is a
# hardware product the manual legitimately names, and must not fail the build.
#
# Body text is deliberately NOT scanned with this pattern. The manual discusses
# hardware brands in prose, and the leak vector is links and metadata, not prose.
# A separator is a backslash or a forward slash. Built with chr(92) on purpose:
# a literal "\\" inside a character class does not survive every editing path,
# and when it collapses to "\/" the class silently means "slash only" -- which is how
# backslash-separated Windows paths slipped past an earlier version of this gate.
_SEP = "[" + chr(92) + chr(92) + "/]"

FORBIDDEN = re.compile(
    "file:"
    "|[A-Za-z]:" + _SEP + "{1,2}Users" + _SEP
    + "|/home/[a-z]|/Users/[A-Za-z]"
    + "|OneDrive|scratchpad"
    + "|" + _SEP + "Temp" + _SEP
    + "|[A-Za-z]:" + _SEP + "{1,2}tmp" + _SEP
    + "|" + _SEP + "tmp" + _SEP
    + r"|markdownpanel-virtualhost|files\.fm"
    + r"|claude|codex|anthropic|chatgpt|openai|gemini|copilot(?!\+)"
    + r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def uri_is_allowed(uri: str) -> bool:
    """A link may ship only if it is public HTTPS, or the author's own mailto."""
    if uri == ALLOWED_MAILTO:
        return True
    return uri.startswith("https://") and not FORBIDDEN.search(uri)


def forbidden_sequences(data: bytes | str) -> list[str]:
    """Distinct forbidden sequences found in the given bytes or text, sorted."""
    text = data.decode("latin-1") if isinstance(data, bytes) else data
    return sorted({m.group(0) for m in FORBIDDEN.finditer(text)})


def _read(pdf_path: Path):
    try:
        from pypdf import PdfReader
    except ImportError:  # fail closed
        raise SystemExit(
            "pypdf is not installed, so the PDF user guide cannot be verified.\n"
            "Install the build dependencies first:\n"
            r"    .venv\Scripts\python.exe -m pip install -r requirements-build.txt"
        )
    return PdfReader(str(pdf_path))


def link_targets(reader) -> list[str]:
    """Every decoded /URI action target in the document."""
    found: list[str] = []
    for page in reader.pages:
        for annot in page.get("/Annots") or []:
            action = annot.get_object().get("/A")
            if not action:
                continue
            uri = action.get_object().get("/URI")
            if uri:
                found.append(str(uri))
    return found


def metadata_values(reader) -> dict[str, str]:
    """Document information values, which travel with the file but are unseen."""
    return {str(k): str(v) for k, v in (reader.metadata or {}).items()}


def check(pdf_path: Path) -> list[str]:
    problems: list[str] = []
    reader = _read(pdf_path)

    for uri in link_targets(reader):
        if not uri_is_allowed(uri):
            problems.append(f"link target not allowed: {uri}")

    for key, value in metadata_values(reader).items():
        for hit in forbidden_sequences(value):
            problems.append(f"forbidden content in metadata {key}: {hit!r}")

    for hit in forbidden_sequences(pdf_path.read_bytes()):
        problems.append(f"forbidden byte sequence in file: {hit!r}")

    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} <user-guide.pdf>", file=sys.stderr)
        return 2

    pdf_path = Path(argv[1])
    if not pdf_path.is_file():
        print(f"PDF user guide not found: {pdf_path}", file=sys.stderr)
        return 2

    problems = check(pdf_path)
    if problems:
        print(f"PDF user guide failed the release gate: {pdf_path}", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(f"PDF user guide passed: {pdf_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
