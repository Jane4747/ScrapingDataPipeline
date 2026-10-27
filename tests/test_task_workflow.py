import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pipeline.cli import main
from pipeline.task_spec import load_task, validate_task_id
from pipeline.task_runner import start_task, resume_task, get_status, task_lock


class TaskWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.collection = self.root / "original"
        self.collection.mkdir()
        (self.collection / "body.txt").write_text("该医院已经部署智能医疗机器人并投入临床使用。", encoding="utf-8")
        (self.collection / "raw.html").write_text("<p>该医院已经部署智能医疗机器人并投入临床使用。</p>", encoding="utf-8")
        self.pages = [{"source_id": "hospital", "source_name": "医院", "status": "ok", "title": "应用案例",
                       "url": "https://example.com/case", "requested_url": "https://example.com/case",
                       "text_file": "body.txt", "raw_file": "raw.html", "published_at": "2025-01-01",
                       "fetched_at": "2026-10-22T00:00:00Z"}]
        self.save_pages()
        self.config = self.root / "sources.json"
        self.config.write_text(json.dumps({"version": 1, "topic": "医疗装备", "sources": [
            {"id": "hospital", "name": "医院", "allowed_domains": ["example.com"], "seeds": ["https://example.com/"]}]}), encoding="utf-8")
        self.spec = {"schema_version": 1, "task_id": "offline-example", "title": "资料复核", "question": "核对医院机器人部署线索",
                     "source_config": "sources.json", "allow_network": False,
                     "collection": {"mode": "existing", "input_dir": "original"}, "delivery": ["json", "markdown", "csv"]}
        self.path = self.root / "task-spec.json"
        self.output = self.root / "outputs"

    def save_pages(self):
        (self.collection / "pages.json").write_text(json.dumps(self.pages, ensure_ascii=False), encoding="utf-8")

    def save_spec(self):
        self.path.write_text(json.dumps(self.spec, ensure_ascii=False), encoding="utf-8")
        return self.path

    def run_task(self):
        self.save_spec()
        with patch("requests.Session.get", side_effect=AssertionError("offline task must not network")):
            return start_task(self.path, self.output)

    def test_offline_end_to_end_preserves_original_and_separates_evidence_from_projects(self):
        original = (self.collection / "pages.json").read_bytes()
        result = self.run_task()
        self.assertEqual(result["status"], "completed", result.get("error"))
        self.assertEqual((self.collection / "pages.json").read_bytes(), original)
        collection = Path(result["stages"]["collection"]["output_dir"])
        imported = json.loads((collection / "pages.json").read_text(encoding="utf-8"))
        self.assertTrue((collection / imported[0]["text_file"]).exists())
        evidence = Path(result["stages"]["evidence"]["output_dir"])
        self.assertTrue(json.loads((evidence / "deployment_evidence.json").read_text(encoding="utf-8")))
        review = Path(result["stages"]["review"]["output_dir"])
        self.assertEqual(json.loads((review / "projects.json").read_text(encoding="utf-8")), [])
        self.assertTrue((Path(result["stages"]["delivery"]["output_dir"]) / "report.md").exists())
        self.assertTrue(result["warnings"])

    def test_dry_run_does_not_write_or_network(self):
        self.save_spec()
        with patch("requests.Session.get", side_effect=AssertionError("no network")):
            state = start_task(self.path, self.output, dry_run=True)
        self.assertEqual(state["status"], "validated")
        self.assertFalse(self.output.exists())

    def test_network_permission_and_unknown_fields_are_validated(self):
        self.spec["collection"] = {"mode": "crawl"}
        with self.assertRaisesRegex(ValueError, "allow_network"):
            load_task(self.save_spec())
        self.spec["allow_network"] = True
        self.spec["budegt"] = {"max_pages": 2}
        with self.assertRaisesRegex(ValueError, "budegt"):
            load_task(self.save_spec())

    def test_dates_and_stage_dependencies(self):
        self.spec["time_range"] = {"since": "2026-10-22", "until": "2025-01-01"}
        with self.assertRaises(ValueError):
            load_task(self.save_spec())
        self.spec.pop("time_range")
        self.spec["stages"] = ["delivery"]
        with self.assertRaisesRegex(ValueError, "review"):
            load_task(self.save_spec())

    def test_malformed_enum_types_return_structured_errors(self):
        import copy
        original = copy.deepcopy(self.spec)
        for section, field in (("time_range", "basis"), ("collection", "mode"), ("discovery", "provider")):
            for invalid in ([], {}, True, None):
                with self.subTest(section=section, invalid=invalid):
                    self.spec = copy.deepcopy(original)
                    self.spec.setdefault(section, {})[field] = invalid
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        code = main(["task", "--spec", str(self.save_spec()), "--dry-run", "--json"])
                    self.assertEqual(code, 2)
                    self.assertEqual(json.loads(output.getvalue())["error_type"], "ValueError")

    def test_task_ids_cannot_escape_or_use_windows_devices(self):
        for name in ("../bad", "CON", "nul.json", "trailing.", "a/b", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_task_id(name)

    def test_existing_output_and_lock_are_preserved(self):
        self.save_spec()
        folder = self.output / self.spec["task_id"]
        with task_lock(folder):
            with self.assertRaisesRegex(ValueError, "锁定"):
                start_task(self.path, self.output)
            self.assertTrue((folder / "task.lock").exists())
        protected = folder / "user.txt"
        protected.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "已有内容"):
            start_task(self.path, self.output)
        self.assertEqual(protected.read_text(encoding="utf-8"), "keep")

    def test_resume_is_idempotent_and_input_changes_are_rejected(self):
        result = self.run_task()
        old_paths = {k: v["output_dir"] for k, v in result["stages"].items()}
        resumed = resume_task(self.spec["task_id"], self.output)
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(old_paths, {k: v["output_dir"] for k, v in resumed["stages"].items()})
        snapshot = self.output / self.spec["task_id"] / "inputs" / "sources.json"
        snapshot.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "快照已变化"):
            resume_task(self.spec["task_id"], self.output)

    def test_status_exposes_pending_changes_instead_of_old_completed_report(self):
        self.run_task()
        path = self.output / self.spec["task_id"] / "task.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["pending_stages"] = ["review"]
        path.write_text(json.dumps(document), encoding="utf-8")
        state = get_status(self.spec["task_id"], self.output)
        self.assertEqual(state["status"], "needs_input")
        self.assertEqual(state["stages"]["review"]["status"], "stale")
        self.assertEqual(state["stages"]["delivery"]["status"], "stale")
        self.assertEqual(state["stages"]["collection"]["status"], "completed")

    def test_import_preserves_original_page_budget_stop_reason(self):
        (self.collection / "manifest.json").write_text(json.dumps({"sources": [
            {"source_id": "hospital", "status": "partial", "remaining_candidates": 7, "stop_reason": "page_budget"}]}), encoding="utf-8")
        state = self.run_task()
        self.assertEqual(state["status"], "partial")
        self.assertEqual(state["stages"]["delivery"]["summary"]["coverage"]["page_budget_limited_sources"], 1)

    def test_failed_stage_is_durable_and_retry_uses_new_attempt(self):
        self.save_spec()
        with patch("pipeline.research.deployments.build_index", side_effect=ValueError("injected parse failure")):
            first = start_task(self.path, self.output)
        self.assertEqual(first["status"], "failed")
        self.assertEqual(get_status(self.spec["task_id"], self.output)["stages"]["evidence"]["status"], "failed")
        second = resume_task(self.spec["task_id"], self.output)
        self.assertEqual(second["status"], "completed", second.get("error"))
        self.assertNotEqual(first["stages"]["evidence"]["output_dir"], second["stages"]["evidence"]["output_dir"])

    def test_partial_collection_is_not_silently_promoted(self):
        self.pages.append({"source_id": "hospital", "source_name": "医院", "status": "blocked", "url": "https://example.com/blocked", "requested_url": "https://example.com/blocked", "error": "robots"})
        self.save_pages()
        state = self.run_task()
        self.assertEqual(state["status"], "partial")
        self.assertEqual(state["stages"]["collection"]["summary"]["failed_pages"], 1)

    def test_event_dates_are_not_filtered_using_publication_dates(self):
        self.spec["time_range"] = {"basis": "event", "since": "2026-01-01", "until": "2026-12-31"}
        state = self.run_task()
        self.assertEqual(state["stages"]["evidence"]["summary"]["processed_pages"], 1)
        self.assertTrue(any("事件日期" in w for w in state["warnings"]))

    def test_json_cli_has_one_object_and_errors_are_structured(self):
        self.save_spec()
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = main(["task", "--spec", str(self.path), "--output-root", str(self.output), "--json"])
        self.assertEqual(code, 0, stream.getvalue())
        self.assertEqual(json.loads(stream.getvalue())["status"], "completed")
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = main(["task", "--json"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stream.getvalue())["status"], "failed")

    def test_import_path_escape_and_live_source_lock_fail(self):
        self.pages[0]["text_file"] = "../outside.txt"
        (self.root / "outside.txt").write_text("private", encoding="utf-8")
        self.save_pages()
        result = self.run_task()
        self.assertEqual(result["status"], "failed")
        self.assertIn("超出", result["error"])
        self.spec["task_id"] = "locked-source"
        (self.collection / "run.lock").write_text("running", encoding="utf-8")
        result = self.run_task()
        self.assertEqual(result["status"], "failed")
        self.assertIn("run.lock", result["error"])

    def test_plan_only_task_never_searches_or_crawls(self):
        self.spec["stages"] = ["discovery"]
        self.spec["collection"] = {"mode": "crawl"}
        result = self.run_task()
        self.assertEqual(result["status"], "completed", result.get("error"))
        self.assertEqual(result["stages"]["discovery"]["summary"]["api_requests"], 0)
        self.assertEqual(set(result["stages"]), {"discovery"})

    def test_review_submission_preserves_collection_and_previous_deliveries(self):
        first = self.run_task()
        evidence_file = Path(first["stages"]["evidence"]["output_dir"]) / "deployment_evidence.json"
        evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
        decision_file = self.root / "decisions.json"
        decision_file.write_text(json.dumps({"projects": [{"project_id": "project-1", "name": "医院机器人应用",
            "evidence_ids": [evidence[0]["evidence_id"]], "review_status": "source_claim", "event_date": "2025-01-01"}]}), encoding="utf-8")
        second = resume_task(self.spec["task_id"], self.output, review_file=decision_file)
        self.assertEqual(second["status"], "completed", second.get("error"))
        for stage in ("collection", "evidence"):
            self.assertEqual(first["stages"][stage]["output_dir"], second["stages"][stage]["output_dir"])
        for stage in ("review", "delivery"):
            self.assertNotEqual(first["stages"][stage]["output_dir"], second["stages"][stage]["output_dir"])
        self.assertTrue((Path(first["stages"]["delivery"]["output_dir"]) / "report.json").exists())
        projects = json.loads((Path(second["stages"]["review"]["output_dir"]) / "projects.json").read_text(encoding="utf-8"))
        self.assertEqual(len(projects), 1)

    def test_crawl_resume_grows_budget_without_repeating_successful_pages(self):
        from pipeline.research.fetch import Fetcher
        calls = []
        def fetch(_self, url, domains):
            calls.append(url)
            return {"url": url, "requested_url": url, "status": "ok", "title": "医疗机器人应用",
                    "text": "该医院已经部署智能医疗机器人并投入临床使用。", "raw": b"<p>saved</p>",
                    "content_type": "text/html", "published_at": "2025-01-01", "http_status": 200,
                    "links": [{"url": "https://example.com/product/robot", "text": "医疗机器人产品"}] if url.endswith("/") else []}
        self.spec.update(collection={"mode": "crawl"}, allow_network=True, stages=["collection", "evidence", "review", "delivery"],
                         budget={"max_pages": 1, "max_depth": 1, "delay": 0})
        with patch.object(Fetcher, "fetch", fetch), patch("requests.Session.get", side_effect=AssertionError("no real network")):
            first = self.run_task()
            self.assertEqual(first["status"], "partial", first.get("error"))
            second = resume_task(self.spec["task_id"], self.output, max_pages=2)
        self.assertEqual(second["status"], "completed", second.get("error"))
        self.assertEqual(calls, ["https://example.com/", "https://example.com/product/robot"])
        self.assertEqual(first["stages"]["collection"]["output_dir"], second["stages"]["collection"]["output_dir"])
        self.assertNotEqual(first["stages"]["evidence"]["output_dir"], second["stages"]["evidence"]["output_dir"])

    def test_interrupted_paid_search_never_automatically_replays(self):
        self.spec.update(collection={"mode": "crawl"}, allow_network=True, stages=["discovery"], discovery={"provider": "brave"})
        self.save_spec()
        with patch("pipeline.research.discovery.run", side_effect=RuntimeError("interrupted")) as discover:
            first = start_task(self.path, self.output)
            self.assertEqual(first["status"], "failed")
            second = resume_task(self.spec["task_id"], self.output)
            self.assertEqual(discover.call_count, 1)
        self.assertEqual(second["status"], "needs_input")


if __name__ == "__main__":
    unittest.main()
