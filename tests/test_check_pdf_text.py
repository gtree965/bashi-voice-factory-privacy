"""Publication checks must inspect decoded text, including compressed streams."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_pdf_text


@unittest.skipUnless(importlib.util.find_spec("pypdf"), "build dependency pypdf is required")
class PdfTextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.terms = self.root / "terms.txt"
        self.terms.write_text("qzx\n", encoding="utf-8")

    def pdf(self, text=None):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        writer = PdfWriter()
        page = writer.add_blank_page(595, 842)
        if text is not None:
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                     NameObject("/Subtype"): NameObject("/Type1"),
                                     NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
            stream = DecodedStreamObject()
            stream.set_data(b"BT /F1 12 Tf 20 800 Td (" + text.encode("ascii") + b") Tj ET")
            page[NameObject("/Contents")] = writer._add_object(stream)
            page.compress_content_streams()
        path = self.root / "guide.pdf"
        with path.open("wb") as output:
            writer.write(output)
        return path

    def test_ordinary_compressed_text_passes(self):
        problems, pages = check_pdf_text.check(self.pdf("ordinary manual"), self.terms)
        self.assertEqual(problems, [])
        self.assertIn("ordinary manual", pages[0])

    def test_short_term_is_found_after_decompression(self):
        pdf = self.pdf("prefix QZX suffix")
        self.assertNotIn(b"QZX", pdf.read_bytes())
        problems, _ = check_pdf_text.check(pdf, self.terms)
        self.assertTrue(any("local publication term" in p for p in problems))
        self.assertFalse(any("qzx" in p.casefold() for p in problems))

    def test_empty_page_is_not_a_clean_scan(self):
        problems, _ = check_pdf_text.check(self.pdf(), self.terms)
        self.assertTrue(any("no readable text" in p for p in problems))

    def test_missing_term_list_fails_closed(self):
        with self.assertRaises(check_pdf_text.GuardError):
            check_pdf_text.check(self.pdf("ordinary manual"), self.root / "missing.txt")

    def test_report_retains_page_counts_and_manual_review_requirement(self):
        import json
        report, text = self.root / "report.json", self.root / "text.txt"
        code = check_pdf_text.main([str(self.pdf("ordinary manual")), "--terms-file", str(self.terms),
                                   "--report", str(report), "--text-out", str(text)])
        self.assertEqual(code, 0)
        data = json.loads(report.read_text())
        self.assertEqual(len(data["page_characters"]), 1)
        self.assertTrue(data["render_review_still_required"])
        self.assertIn("ordinary manual", text.read_text())
