"""Offline integrity checks must reject modified or missing archive artifacts."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import archive_medical_pr_mapping_20261102 as archive


class MedicalPRArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.destination = patch.object(archive, "DEST", self.root)
        self.destination.start()
        self.addCleanup(self.destination.stop)
        tree = {
            "id": "archive-fixture", "created_at": "2026-11-03T00:00:00+08:00",
            "updated_at": "2026-11-03T00:00:00+08:00", "status": "partial",
            "tool": "offline", "theme": "fixture", "delivery": "tree.md",
            "nodes": [{"id": "need", "parent": None, "kind": "需求",
                       "text": "Verify integrity", "status": "completed"}],
        }
        (self.root / "tree.json").write_text(json.dumps(tree), encoding="utf-8")
        (self.root / "tree.md").write_text(archive.render_markdown(tree), encoding="utf-8")
        self.artifact = self.root / "source.py"
        original = b"print('fixture')\r\n"
        self.artifact.write_bytes(original)
        (self.root / "SOURCE-MANIFEST.json").write_text(json.dumps({"files": [{
            "path": "source.py", "sha256": hashlib.sha256(original).hexdigest()
        }]}), encoding="utf-8")

    def run_verify(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = archive.main(["--verify"])
        return code, json.loads(output.getvalue())

    def test_valid_archive_succeeds_without_rewriting_it(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        code, report = self.run_verify()
        self.assertEqual(code, 0)
        self.assertEqual(report["archive_status"], "completed")
        self.assertEqual(report["coverage_status"], "partial")
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_byte_changes_fail_even_when_only_line_endings_change(self):
        self.artifact.write_bytes(self.artifact.read_bytes().replace(b"\r\n", b"\n"))
        code, report = self.run_verify()
        self.assertEqual(code, 2)
        self.assertFalse(report["checks"]["manifest_hashes_match"])
        self.assertEqual(report["archive_status"], "failed")

    def test_missing_artifact_fails(self):
        self.artifact.unlink()
        code, report = self.run_verify()
        self.assertEqual(code, 2)
        self.assertFalse(report["checks"]["manifest_hashes_match"])

    def test_broken_internal_link_fails(self):
        (self.root / "DETAILS.md").write_text("[missing](missing.txt)", encoding="utf-8")
        code, report = self.run_verify()
        self.assertEqual(code, 2)
        self.assertEqual(report["checks"]["missing_links"], ["DETAILS.md: missing.txt"])


if __name__ == "__main__":
    unittest.main()
