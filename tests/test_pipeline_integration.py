import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from pipeline.cli import main, cmd_run
from pipeline import runner


class PipelineIntegrationTest(unittest.TestCase):
    def test_research_dry_run_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "not-created"
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = main(["research", "--source", "medbot", "--dry-run", "--output-dir", str(target)])
            self.assertEqual(code, 0)
            self.assertFalse(target.exists())
            self.assertEqual(json.loads(stream.getvalue())["source_count"], 1)

    def test_unknown_source_and_bad_run_id_fail_before_network(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["research", "--source", "missing", "--dry-run"]), 2)
            self.assertEqual(main(["research", "--run-id", "../escape", "--dry-run"]), 2)

    def test_resume_subset_rejected_without_replacing_existing_exports(self):
        from pipeline.research.config import load_config
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "config.snapshot.json").write_text(json.dumps(load_config()), encoding="utf-8")
            (folder / "records.json").write_text('[{"id":"keep"}]', encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["research", "--resume", "--source", "medbot", "--output-dir", str(folder)])
            self.assertEqual(code, 2)
            self.assertEqual((folder / "records.json").read_text(encoding="utf-8"), '[{"id":"keep"}]')

    def test_existing_runner_failure_is_persisted(self):
        tree = {"id": "fixture", "tool": "crawl4ai", "nodes": []}
        args = types.SimpleNamespace(tree_id="fixture", theme="测试", delivery="json")
        saves = []
        with patch("pipeline.cli.load_tree", return_value=tree), \
             patch("pipeline.cli.save_tree", side_effect=lambda value: saves.append(value["status"])), \
             patch("pipeline.cli.run_task", side_effect=runner.RunError("expected failure")):
            with self.assertRaises(runner.RunError):
                cmd_run(args)
        self.assertEqual(saves, ["running", "failed"])

    def test_newsplease_mapping_preserves_url_and_missing_article(self):
        class Article:
            def get_serializable_dict(self):
                return {"title": "医学影像"}

        urls = ["https://example.com/one", "https://example.com/two"]
        fake_module = types.ModuleType("newsplease")
        fake_module.NewsPlease = types.SimpleNamespace(from_urls=lambda _: {urls[0]: Article()})

        def execute(code, *argv):
            output = io.StringIO()
            with patch.dict(sys.modules, {"newsplease": fake_module}), \
                 patch.object(sys, "argv", ["-c", *argv]), contextlib.redirect_stdout(output):
                exec(code, {})
            return output.getvalue().strip()

        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, "_python_stdin", side_effect=execute):
            args = types.SimpleNamespace(url=urls, delivery="json")
            result = runner._run_news_please({}, args, Path(tmp))
            rows = json.loads(Path(result["files"][0]).read_text(encoding="utf-8"))
        self.assertEqual(result["count"], 2)
        self.assertEqual(rows[0]["url"], urls[0])
        self.assertEqual(rows[1], {"url": urls[1], "error": "extract failed"})


if __name__ == "__main__":
    unittest.main()
