import builtins
from concurrent.futures import ThreadPoolExecutor
import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from pipeline.delivery import build_delivery
from pipeline.review import build_review, _write_json


class ReviewDeliveryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.evidence_dir = self.root / "evidence"
        self.collection_dir = self.root / "collection"
        self.evidence_dir.mkdir()
        self.collection_dir.mkdir()
        self.evidence = [
            {"evidence_id": "ev-1", "source_id": "vendor", "source_name": "厂商",
             "url": "https://vendor.example/one", "title": "部署公告", "published_at": "2025-01-01",
             "evidence_text": "公司称医院已部署机器人。", "signal_type": "operational_claim",
             "paragraph_index": 4, "fragment_index": 1, "review_status": "待人工核验"},
            {"evidence_id": "ev-2", "source_id": "hospital", "source_name": "医院",
             "url": "https://hospital.example/two", "title": "医院公告", "published_at": "",
             "evidence_text": "医院发布有关设备运行的声明。", "signal_type": "operational_claim",
             "paragraph_index": 3, "fragment_index": 1, "pdf_page": 2, "review_status": "待人工核验"},
        ]
        self.write(self.evidence_dir / "deployment_evidence.json", self.evidence)
        self.write(self.evidence_dir / "summary.json", {"evidence_count": 2, "unknown_publication_date_pages": 1})
        self.pages = [dict(self.evidence[0], status="ok"), dict(self.evidence[1], status="ok"),
                      {"source_id": "third", "url": "https://third.example", "status": "error", "error": "模拟超时"}]
        self.write(self.collection_dir / "pages.json", self.pages)
        self.write(self.collection_dir / "manifest.json", {"sources": [{"id": "vendor"}, {"id": "hospital"}, {"id": "third"}]})
        self.task = {"title": "医疗调研", "question": "有哪些项目？",
                     "time_range": {"since": "2024-01-01", "until": "2026-10-22", "basis": "event_date"}}

    def write(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def read(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def project(self, **updates):
        return {"project_id": "project-1", "name": "机器人项目", "evidence_ids": ["ev-1"], **updates}

    def decisions(self, projects):
        path = self.root / "decisions.json"
        self.write(path, {"projects": projects})
        return path

    def test_default_review_never_turns_claims_into_projects(self):
        target = self.root / "review"
        summary = build_review(self.evidence_dir, target)
        self.assertEqual(summary["project_count"], 0)
        self.assertEqual(summary["unassigned_evidence_count"], 2)
        self.assertEqual(self.read(target / "projects.json"), [])
        self.assertEqual(self.read(target / "review_template.json")["projects"], [])
        queue = self.read(target / "review_queue.json")
        self.assertTrue(all(row["queue_status"] == "pending" and not row["project_ids"] for row in queue))
        self.assertTrue(all((target / filename).is_file() for filename in summary["files"]))

    def test_decisions_preserve_explicit_values_and_link_evidence(self):
        target = self.root / "review"
        decisions = self.decisions([self.project(review_status="source_claim", notes="仅来自厂商")])
        summary = build_review(self.evidence_dir, target, decisions)
        project = self.read(target / "projects.json")[0]
        self.assertEqual(project["notes"], "仅来自厂商")
        self.assertEqual(project["event_date"], "")
        queue = self.read(target / "review_queue.json")
        self.assertEqual(queue[0]["project_ids"], ["project-1"])
        self.assertEqual(queue[0]["review_status"], "待人工核验")
        self.assertEqual(queue[1]["project_ids"], [])
        self.assertEqual(summary["status_counts"]["source_claim"], 1)

    def test_invalid_decisions_are_rejected_before_output(self):
        invalid = [
            [self.project(project_id="")], [self.project(name="")],
            [self.project(), self.project()], [self.project(evidence_ids=["missing"])],
            [self.project(evidence_ids=[])], [self.project(evidence_ids=["ev-1", "ev-1"])],
            [self.project(event_date="2025-02-30")], [self.project(event_date="2025-1-1")],
            [self.project(reviewed_at="yesterday")], [self.project(review_status="verified")],
            [self.project(entity=1)], [self.project(typo="silent loss")],
        ]
        for index, projects in enumerate(invalid):
            with self.subTest(projects=projects), self.assertRaises(ValueError):
                build_review(self.evidence_dir, self.root / f"bad-{index}", self.decisions(projects))
            self.assertFalse((self.root / f"bad-{index}").exists())

    def test_duplicate_evidence_is_rejected(self):
        self.write(self.evidence_dir / "deployment_evidence.json", [self.evidence[0], self.evidence[0]])
        with self.assertRaisesRegex(ValueError, "重复 evidence_id"):
            build_review(self.evidence_dir, self.root / "review")

    def test_corroboration_requires_reviewer_time_and_distinct_sources_and_hosts(self):
        project = self.project(review_status="corroborated", evidence_ids=["ev-1", "ev-2"],
                               reviewer="研究人员", reviewed_at="2026-10-22T08:30:00+08:00")
        for index, updates in enumerate(({"reviewer": ""}, {"reviewed_at": ""}, {"evidence_ids": ["ev-1"]})):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                build_review(self.evidence_dir, self.root / f"bad-{index}", self.decisions([{**project, **updates}]))
        self.evidence[1]["source_id"] = "vendor"
        self.write(self.evidence_dir / "deployment_evidence.json", self.evidence)
        with self.assertRaises(ValueError):
            build_review(self.evidence_dir, self.root / "same-source", self.decisions([project]))
        self.evidence[1]["source_id"] = "hospital"
        self.evidence[1]["url"] = "https://www.vendor.example/other"
        self.write(self.evidence_dir / "deployment_evidence.json", self.evidence)
        with self.assertRaises(ValueError):
            build_review(self.evidence_dir, self.root / "same-host", self.decisions([project]))

    def test_corroboration_is_explicitly_a_reviewers_claim(self):
        project = self.project(review_status="corroborated", evidence_ids=["ev-1", "ev-2"],
                               reviewer="研究人员", reviewed_at="2026-10-22", event_date="2025-01-01")
        summary = build_review(self.evidence_dir, self.root / "review", self.decisions([project]))
        self.assertEqual(summary["status_counts"]["corroborated"], 1)
        self.assertIn("不是程序事实验证", summary["review_note"])
        self.assertIn("不证明来源相互独立", summary["review_note"])

    def test_csv_formula_protection_applies_to_decisions(self):
        project = self.project(name="=HYPERLINK(\"evil\")", notes=" \t+cmd")
        build_review(self.evidence_dir, self.root / "review", self.decisions([project]))
        with (self.root / "review" / "projects.csv").open(encoding="utf-8-sig", newline="") as handle:
            row = next(csv.DictReader(handle))
        self.assertTrue(row["name"].startswith("'="))
        self.assertTrue(row["notes"].startswith("' \t+"))

    def test_nonempty_output_and_input_ancestors_are_protected(self):
        output = self.root / "review"
        output.mkdir()
        (output / "keep.txt").write_text("original")
        with self.assertRaisesRegex(ValueError, "非空"):
            build_review(self.evidence_dir, output)
        self.assertEqual((output / "keep.txt").read_text(), "original")
        self.assertFalse((output / ".write.lock").exists())
        with self.assertRaises(ValueError):
            build_review(self.evidence_dir, self.root)
        with self.assertRaises(ValueError):
            build_review(self.evidence_dir, self.evidence_dir)

    def test_concurrent_review_writers_have_only_one_winner(self):
        target = self.root / "race"
        ready = threading.Event()
        release = threading.Event()
        original = _write_json

        def slow_write(path, value):
            if path.name == "projects.json":
                ready.set()
                if not release.wait(5):
                    raise RuntimeError("test synchronization timed out")
            original(path, value)

        with patch("pipeline.review._write_json", side_effect=slow_write), ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(build_review, self.evidence_dir, target)
            self.assertTrue(ready.wait(5))
            try:
                with self.assertRaisesRegex(ValueError, "其他任务"):
                    build_review(self.evidence_dir, target)
            finally:
                release.set()
            self.assertEqual(first.result(timeout=5)["project_count"], 0)
        self.assertFalse((target / ".write.lock").exists())

    def test_atomic_json_failure_leaves_existing_file_intact(self):
        path = self.root / "atomic.json"
        self.write(path, {"old": True})
        with patch("pipeline.review.os.replace", side_effect=OSError("simulated")), self.assertRaises(OSError):
            _write_json(path, {"new": True})
        self.assertEqual(self.read(path), {"old": True})
        self.assertFalse(list(self.root.glob(".*.tmp")))

    def test_delivery_reports_gaps_empty_projects_dates_and_real_files(self):
        before = (self.collection_dir / "pages.json").read_bytes()
        review = self.root / "review"
        build_review(self.evidence_dir, review)
        target = self.root / "delivery"
        summary = build_delivery(self.task, self.collection_dir, self.evidence_dir, review, target, ("csv",))
        report = self.read(target / "report.json")
        self.assertEqual(summary["coverage"]["failed_pages"], 1)
        self.assertEqual(summary["coverage"]["unknown_publication_date_pages"], 1)
        self.assertEqual(summary["coverage"]["evidence_count"], 2)
        self.assertEqual(summary["coverage"]["project_count"], 0)
        self.assertFalse(report["claim_policy"]["facts_automatically_verified"])
        markdown = (target / "report.md").read_text(encoding="utf-8")
        for expected in ("待 GPT 综合", "线索数不等于项目数", "项目台账为空", "2024-01-01", "https://vendor.example/one", "模拟超时", "ev-1", "正文行 4", "PDF 页 2"):
            self.assertIn(expected, markdown)
        self.assertIn("事件日期范围", "".join(summary["gaps"]))
        self.assertEqual(set(summary["files"]), {file.name for file in target.iterdir()})
        self.assertEqual((self.collection_dir / "pages.json").read_bytes(), before)

    def test_delivery_keeps_review_claim_and_evidence_references(self):
        project = self.project(review_status="corroborated", evidence_ids=["ev-1", "ev-2"],
                               reviewer="研究人员", reviewed_at="2026-10-22")
        review = self.root / "review"
        build_review(self.evidence_dir, review, self.decisions([project]))
        target = self.root / "delivery"
        summary = build_delivery(self.task, self.collection_dir, self.evidence_dir, review, target)
        report = self.read(target / "report.json")
        self.assertEqual(summary["coverage"]["project_count"], 1)
        self.assertEqual(summary["coverage"]["unknown_event_date_projects"], 1)
        self.assertEqual(report["projects"][0]["evidence_ids"], ["ev-1", "ev-2"])
        self.assertEqual(report["claim_policy"]["review_status_origin"], "decision_file_author")

    def test_delivery_revalidates_project_evidence_references(self):
        review = self.root / "review"
        build_review(self.evidence_dir, review)
        self.write(review / "projects.json", [self.project(evidence_ids=["missing"])])
        with self.assertRaisesRegex(ValueError, "evidence_ids"):
            build_delivery(self.task, self.collection_dir, self.evidence_dir, review, self.root / "delivery")

    def test_delivery_rejects_mixed_input_provenance(self):
        self.write(self.evidence_dir / "summary.json", {"input_dir": str(self.root / "other-collection")})
        with self.assertRaisesRegex(ValueError, "拒绝混用资料"):
            build_delivery(self.task, self.collection_dir, self.evidence_dir, None, self.root / "delivery")

    def test_delivery_reports_source_failures_and_budget_limits(self):
        self.write(self.collection_dir / "manifest.json", {"sources": [
            {"source_id": "zero-pages", "status": "failed", "error": "初始化失败"},
            {"source_id": "vendor", "status": "partial", "stop_reason": "page_budget", "remaining_candidates": 5},
        ]})
        summary = build_delivery(self.task, self.collection_dir, self.evidence_dir, None, self.root / "delivery")
        self.assertEqual(summary["coverage"]["source_count"], 4)
        self.assertEqual(summary["coverage"]["failed_sources"], 1)
        self.assertEqual(summary["coverage"]["remaining_candidates"], 5)
        self.assertIn("页数上限", "".join(summary["gaps"]))

    def test_delivery_keeps_task_scope_and_counts_event_dates_inclusively(self):
        task = {**self.task, "region": "中国", "scenarios": ["医院", "康养机构"],
                "source_ids": ["vendor", "hospital"], "research_type": "health_deployment"}
        dates = ["2024-01-01", "2026-10-22", "2023-12-31", "2026-10-23", ""]
        projects = [self.project(project_id=f"project-{index}", event_date=value) for index, value in enumerate(dates)]
        review = self.root / "review"
        build_review(self.evidence_dir, review, self.decisions(projects))
        target = self.root / "delivery"
        summary = build_delivery(task, self.collection_dir, self.evidence_dir, review, target)
        report = self.read(target / "report.json")
        for field in ("region", "scenarios", "source_ids", "research_type"):
            self.assertEqual(report["task"][field], task[field])
        self.assertEqual(summary["coverage"]["event_date_in_range_projects"], 2)
        self.assertEqual(summary["coverage"]["event_date_out_of_range_projects"], 2)
        self.assertEqual(summary["coverage"]["unknown_event_date_projects"], 1)
        self.assertEqual(len(report["projects"]), 5)
        self.assertFalse(summary["coverage"]["event_date_range"]["unknown_included"])
        markdown = (target / "report.md").read_text(encoding="utf-8")
        for text in ("地域：中国", "场景：医院、康养机构", "范围内项目 2 个", "范围外 2 个", "逐项目判断", "未知日期未计入"):
            self.assertIn(text, markdown)

    def test_event_date_counts_support_one_sided_and_unbounded_ranges(self):
        review = self.root / "review"
        projects = [self.project(project_id=f"p-{index}", event_date=value)
                    for index, value in enumerate(("2023-01-01", "2025-01-01", ""))]
        build_review(self.evidence_dir, review, self.decisions(projects))
        for index, (interval, within, outside) in enumerate((
            ({"since": "2024-01-01"}, 1, 1), ({"until": "2024-01-01"}, 1, 1), ({}, 2, 0),
        )):
            summary = build_delivery({**self.task, "time_range": interval}, self.collection_dir,
                                     self.evidence_dir, review, self.root / f"delivery-{index}")
            self.assertEqual(summary["coverage"]["event_date_in_range_projects"], within)
            self.assertEqual(summary["coverage"]["event_date_out_of_range_projects"], outside)
            self.assertEqual(summary["coverage"]["unknown_event_date_projects"], 1)

    def test_delivery_rejects_invalid_time_ranges_before_output(self):
        for interval in ([], False, {"since": "2025-02-30"}, {"since": "2025-1-1"}, {"until": 0},
                         {"since": "2026-01-01", "until": "2025-01-01"}):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                build_delivery({**self.task, "time_range": interval}, None, None, None, self.root / "invalid")
        self.assertFalse((self.root / "invalid").exists())

    def test_upstream_writing_locks_block_partial_snapshots(self):
        lock = self.evidence_dir / "evidence.lock"
        lock.write_text("active")
        with self.assertRaisesRegex(ValueError, "写入锁"):
            build_review(self.evidence_dir, self.root / "review")
        lock.unlink()
        (self.collection_dir / "run.lock").write_text("active")
        with self.assertRaisesRegex(ValueError, "写入锁"):
            build_delivery(self.task, self.collection_dir, self.evidence_dir, None, self.root / "delivery")
        self.assertFalse((self.root / "review").exists())
        self.assertFalse((self.root / "delivery").exists())

    def test_input_changes_during_multifile_read_are_rejected(self):
        original = Path.read_bytes
        changed = False

        def mutate_evidence(path):
            nonlocal changed
            if path == self.evidence_dir / "summary.json" and not changed:
                changed = True
                self.write(self.evidence_dir / "deployment_evidence.json", self.evidence[:1])
            return original(path)

        with patch.object(Path, "read_bytes", mutate_evidence), self.assertRaisesRegex(ValueError, "输入文件发生变化"):
            build_review(self.evidence_dir, self.root / "review")
        self.assertFalse((self.root / "review").exists())

    def test_basic_delivery_does_not_import_spreadsheet_dependencies(self):
        original = builtins.__import__

        def without_optional(name, *args, **kwargs):
            if name in ("pandas", "xlsxwriter"):
                raise ImportError("unavailable")
            return original(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=without_optional):
            summary = build_delivery(self.task, self.collection_dir, self.evidence_dir, None, self.root / "basic")
            self.assertEqual(summary["files"], ["report.json", "report.md"])
            with self.assertRaisesRegex(RuntimeError, "Excel 导出"):
                build_delivery(self.task, self.collection_dir, self.evidence_dir, None, self.root / "excel", ("excel",))
        self.assertFalse((self.root / "excel").exists())

    def test_delivery_missing_stages_are_explicit_and_formats_validated(self):
        summary = build_delivery(self.task, None, None, None, self.root / "empty")
        self.assertIn("覆盖范围未知", "".join(summary["gaps"]))
        self.assertEqual(summary["coverage"]["project_count"], 0)
        for formats in ("csv", ["pdf"], None, [1], [["csv"]]):
            with self.subTest(formats=formats), self.assertRaises(ValueError):
                build_delivery(self.task, None, None, None, self.root / "bad-format", formats)

    def test_delivery_csv_is_literal_and_existing_output_is_protected(self):
        self.evidence[0]["evidence_text"] = "=HYPERLINK(\"evil\")"
        self.write(self.evidence_dir / "deployment_evidence.json", self.evidence)
        target = self.root / "delivery"
        build_delivery(self.task, self.collection_dir, self.evidence_dir, None, target, ("csv",))
        with (target / "evidence.csv").open(encoding="utf-8-sig", newline="") as handle:
            row = next(csv.DictReader(handle))
        self.assertTrue(row["evidence_text"].startswith("'="))
        with self.assertRaises(ValueError):
            build_delivery(self.task, self.collection_dir, self.evidence_dir, None, target)

    @unittest.skipUnless(importlib.util.find_spec("pandas") and importlib.util.find_spec("xlsxwriter"), "optional Excel dependencies unavailable")
    def test_excel_export_has_no_formulas_or_implicit_url_links(self):
        self.evidence[0]["evidence_text"] = "=1+2"
        self.write(self.evidence_dir / "deployment_evidence.json", self.evidence)
        target = self.root / "delivery"
        summary = build_delivery(self.task, self.collection_dir, self.evidence_dir, None, target, ("xlsx",))
        self.assertIn("report.xlsx", summary["files"])
        with ZipFile(target / "report.xlsx") as archive:
            worksheets = [archive.read(name).decode() for name in archive.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")]
        self.assertTrue(worksheets)
        self.assertTrue(all("<f>" not in xml and "<hyperlink " not in xml for xml in worksheets))


if __name__ == "__main__":
    unittest.main()
