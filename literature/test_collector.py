import copy
from datetime import date
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

from pypdf import PdfWriter

module = importlib.util.spec_from_file_location("collector", Path(__file__).with_name("collector.py"))
collector = importlib.util.module_from_spec(module)
module.loader.exec_module(collector)

SPEC = {"schema_version": 1, "task_id": "test-rsi", "year": 2026, "cutoff": "2026-10-25",
        "allow_network": True, "output_dir": "out", "candidates": [{"arxiv_id": "2602.12063"}]}
HTML = b'''<html><meta name="citation_title" content="A test paper"><meta name="citation_date" content="2026/02/12">
<meta name="citation_author" content="A Author"><div class="submission-history">[v1] Thu, 12 Feb 2026 12:00:00 UTC
[v2] Mon, 26 Oct 2026 12:00:00 UTC</div><blockquote class="abstract">Abstract: Test.</blockquote></html>'''


class FakeFetcher:
    calls = []

    def __init__(self, **kwargs):
        pass

    def fetch(self, url, allowed):
        self.calls.append(url)
        if "/abs/" in url:
            return {"status": "ok", "error": "", "raw": HTML}
        writer = PdfWriter()
        writer.add_blank_page(200, 200)
        stream = io.BytesIO()
        writer.write(stream)
        return {"status": "ok", "error": "", "raw": stream.getvalue(), "text": "[第 1 页]\nTest"}

    def close(self):
        pass


class CollectorTests(unittest.TestCase):
    def test_year_is_not_inferred_from_identifier(self):
        parsed = collector.parse_abs(HTML, "2501.00001", date(2026, 10, 25))
        self.assertEqual(parsed["first_submitted"], "2026-02-12")

    def test_future_revision_is_not_selected(self):
        parsed = collector.parse_abs(HTML, "2602.12063", date(2026, 10, 25))
        self.assertEqual(parsed["selected_version"], 1)

    def test_missing_date_and_history_rejected(self):
        with self.assertRaises(ValueError):
            collector.parse_abs(b"<html>2026</html>", "2602.12063", date(2026, 10, 25))

    def test_identifier_validation_and_deduplication(self):
        spec = copy.deepcopy(SPEC)
        spec["candidates"] *= 2
        self.assertEqual(len(collector.validate_spec(spec)["candidates"]), 1)
        spec["candidates"] = [{"arxiv_id": "../../bad"}]
        with self.assertRaises(ValueError):
            collector.validate_spec(spec)

    def test_html_cannot_be_saved_as_pdf(self):
        with self.assertRaises(ValueError):
            collector.validate_pdf(b"<html>Rate limited</html>")

    def test_dry_run_has_no_files_or_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spec.json"
            path.write_text(json.dumps(SPEC), encoding="utf8")
            FakeFetcher.calls = []
            self.assertEqual(collector.collect(path, True, fetcher_factory=FakeFetcher)["status"], "validated")
            self.assertFalse((path.parent / "out").exists())
            self.assertEqual(FakeFetcher.calls, [])

    def test_resume_checks_hash_and_preserves_pinned_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spec.json"
            path.write_text(json.dumps(SPEC), encoding="utf8")
            FakeFetcher.calls = []
            result = collector.collect(path, fetcher_factory=FakeFetcher)
            self.assertEqual(result["downloaded_count"], 1)
            FakeFetcher.calls = []
            collector.collect(path, resume=True, fetcher_factory=FakeFetcher)
            self.assertEqual(FakeFetcher.calls, [])
            pdf = next((Path(result["output_dir"]) / "pdfs").glob("*.pdf"))
            pdf.write_bytes(b"corrupted")
            result = collector.collect(path, resume=True, fetcher_factory=FakeFetcher)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(pdf.read_bytes(), b"corrupted")

    def test_scope_rejection_and_changed_spec(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spec.json"
            spec = copy.deepcopy(SPEC)
            spec["year"] = 2025
            spec["cutoff"] = "2025-12-31"
            path.write_text(json.dumps(spec), encoding="utf8")
            result = collector.collect(path, fetcher_factory=FakeFetcher)
            self.assertEqual(result["downloaded_count"], 0)
            self.assertEqual(result["excluded_count"], 1)
            spec["year"] = 2026
            spec["cutoff"] = "2026-10-25"
            path.write_text(json.dumps(spec), encoding="utf8")
            with self.assertRaisesRegex(ValueError, "Spec changed"):
                collector.collect(path, resume=True, fetcher_factory=FakeFetcher)


if __name__ == "__main__":
    unittest.main()
