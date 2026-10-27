"""Crash-boundary regressions using real offline task stages and saved output."""

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from pipeline import task_runner
from pipeline.research.fetch import Fetcher
import test_task_workflow as fixtures


class TaskRecoveryTest(unittest.TestCase):
    def setUp(self):
        # Reuse the source/config fixture without importing another TestCase
        # into this module's namespace (which would duplicate test discovery).
        self.fixture = fixtures.TaskWorkflowTest("test_dry_run_does_not_write_or_network")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.calls = []
        self.addCleanup(patch.stopall)
        patch("requests.Session.get", side_effect=AssertionError("recovery tests must not network")).start()

    def _crawl_fixture(self):
        item = self.fixture
        item.spec.update(collection={"mode": "crawl"}, allow_network=True,
                         stages=["collection", "evidence", "review", "delivery"],
                         budget={"max_pages": 1, "max_depth": 1, "delay": 0})
        calls = self.calls

        def fetch(_self, url, domains):
            calls.append(url)
            return {
                "url": url, "requested_url": url, "status": "ok", "title": "医疗机器人应用",
                "text": "该医院已经部署智能医疗机器人并投入临床使用。", "raw": b"<p>saved</p>",
                "content_type": "text/html", "published_at": "2025-01-01", "http_status": 200,
                "links": [{"url": "https://example.com/product/robot", "text": "医疗机器人产品"}]
                if url.endswith("/") else [],
            }

        patch.object(Fetcher, "fetch", fetch).start()
        first = item.run_task()
        self.assertEqual(first["status"], "partial", first.get("error"))
        return first

    def _folder(self):
        return self.fixture.output / self.fixture.spec["task_id"]

    def _read(self, filename):
        return json.loads((self._folder() / filename).read_text(encoding="utf-8"))

    def _resume(self, **kwargs):
        return task_runner.resume_task(self.fixture.spec["task_id"], self.fixture.output, **kwargs)

    def _interrupt_after_write(self, predicate):
        write = task_runner.write_json

        def interrupted(path, value):
            write(path, value)
            if predicate(Path(path), value):
                # KeyboardInterrupt bypasses normal Exception handling, as an
                # abrupt process interruption would; the persisted files remain.
                raise KeyboardInterrupt("simulated interruption after durable write")

        return patch.object(task_runner, "write_json", side_effect=interrupted)

    def _preserved_report(self, state):
        path = Path(state["stages"]["delivery"]["output_dir"]) / "report.json"
        return path, path.read_bytes()

    def _assert_grown_task(self, first, second, saved_report):
        self.assertEqual(second["status"], "completed", second.get("error"))
        self.assertEqual(second["stages"]["collection"]["summary"]["successful_pages"], 2)
        self.assertEqual(second["stages"]["evidence"]["summary"]["processed_pages"], 2)
        for stage in ("evidence", "review", "delivery"):
            self.assertNotEqual(first["stages"][stage]["output_dir"], second["stages"][stage]["output_dir"])
        latest_report = Path(second["stages"]["delivery"]["output_dir"]) / "report.json"
        self.assertEqual(json.loads(latest_report.read_text(encoding="utf-8"))["coverage"]["successful_pages"], 2)
        old_path, old_content = saved_report
        self.assertEqual(old_path.read_bytes(), old_content)
        self.assertEqual(self.calls, ["https://example.com/", "https://example.com/product/robot"])
        self.assertEqual(self._read("task.json")["pending_stages"], [])
        self.assertFalse((self._folder() / "task.lock").exists())

    def test_budget_saved_before_execution_survives_interruption(self):
        first = self._crawl_fixture()
        saved_report = self._preserved_report(first)
        with self._interrupt_after_write(lambda path, value: path.name == "task.json"
                                         and value["spec"]["budget"]["max_pages"] == 2), \
                self.assertRaises(KeyboardInterrupt):
            self._resume(max_pages=2)
        self.assertIn("collection", self._read("task.json")["pending_stages"])
        self.assertEqual(self.calls, ["https://example.com/"])
        # No repeat of --max-pages: ordinary resume must honor the saved change.
        second = self._resume()
        self._assert_grown_task(first, second, saved_report)

    def test_collection_completion_saved_before_pending_clear_survives_interruption(self):
        first = self._crawl_fixture()
        saved_report = self._preserved_report(first)
        with self._interrupt_after_write(lambda path, value: path.name == "status.json"
                                         and value.get("current_stage") == "collection"
                                         and value["stages"]["collection"]["status"] == "completed"), \
                self.assertRaises(KeyboardInterrupt):
            self._resume(max_pages=2)
        state = self._read("status.json")
        self.assertEqual(state["stages"]["collection"]["summary"]["successful_pages"], 2)
        self.assertTrue(all(state["stages"][stage]["status"] == "stale"
                            for stage in ("evidence", "review", "delivery")))
        self.assertIn("collection", self._read("task.json")["pending_stages"])
        second = self._resume()
        self._assert_grown_task(first, second, saved_report)

    def test_evidence_completion_saved_after_pending_clear_rebuilds_stale_delivery(self):
        first = self._crawl_fixture()
        saved_report = self._preserved_report(first)
        with self._interrupt_after_write(lambda path, value: path.name == "status.json"
                                         and value.get("current_stage") == "evidence"
                                         and value["stages"]["evidence"]["status"] == "completed"), \
                self.assertRaises(KeyboardInterrupt):
            self._resume(max_pages=2)
        state = self._read("status.json")
        self.assertEqual(self._read("task.json")["pending_stages"], [])
        self.assertEqual(state["stages"]["evidence"]["summary"]["processed_pages"], 2)
        self.assertTrue(all(state["stages"][stage]["status"] == "stale" for stage in ("review", "delivery")))
        # This boundary depends on persistent stale state, not on pending flags.
        second = self._resume()
        self.assertEqual(state["stages"]["evidence"]["output_dir"], second["stages"]["evidence"]["output_dir"])
        self._assert_grown_task(first, second, saved_report)

    def test_review_snapshot_saved_before_execution_survives_interruption(self):
        first = self.fixture.run_task()
        self.assertEqual(first["status"], "completed", first.get("error"))
        saved_report = self._preserved_report(first)
        evidence_path = Path(first["stages"]["evidence"]["output_dir"]) / "deployment_evidence.json"
        evidence_id = json.loads(evidence_path.read_text(encoding="utf-8"))[0]["evidence_id"]
        decisions = self.fixture.root / "new-review.json"
        decisions.write_text(json.dumps({"projects": [{
            "project_id": "project-new", "name": "医院机器人项目",
            "evidence_ids": [evidence_id], "review_status": "source_claim",
        }]}), encoding="utf-8")
        with self._interrupt_after_write(lambda path, value: path.name == "task.json"
                                         and "review" in value.get("pending_stages", [])), \
                self.assertRaises(KeyboardInterrupt):
            self._resume(review_file=decisions)
        document = self._read("task.json")
        self.assertIn("review", document["pending_stages"])
        self.assertNotEqual(document["spec"]["review"]["decisions_path"], str(decisions))
        # The original file may change after submission; resume must use its snapshot.
        decisions.write_text('{"projects": []}', encoding="utf-8")
        second = self._resume()
        self.assertEqual(second["status"], "completed", second.get("error"))
        for stage in ("collection", "evidence"):
            self.assertEqual(first["stages"][stage]["output_dir"], second["stages"][stage]["output_dir"])
        for stage in ("review", "delivery"):
            self.assertNotEqual(first["stages"][stage]["output_dir"], second["stages"][stage]["output_dir"])
        report = json.loads((Path(second["stages"]["delivery"]["output_dir"]) / "report.json").read_text(encoding="utf-8"))
        self.assertEqual([project["project_id"] for project in report["projects"]], ["project-new"])
        self.assertEqual(saved_report[0].read_bytes(), saved_report[1])
        self.assertEqual(self._read("task.json")["pending_stages"], [])
        self.assertFalse((self._folder() / "task.lock").exists())


if __name__ == "__main__":
    unittest.main()
