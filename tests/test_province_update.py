import json
from pathlib import Path
import tempfile
import unittest

from pipeline.research.national_ggzy import region_key
from pipeline.research.province_update import (BATCHES, region_values, validate_scope, summarize,
                                               request_for, generate_dag, main, MAX_ACTIVE_REGIONS)

BATCH1 = ["上海", "北京", "深圳", "广州", "江苏", "浙江", "湖北", "四川", "山东"]
BATCH2 = ["广东", "河南", "福建", "湖南", "安徽", "陕西", "重庆", "辽宁", "天津", "河北", "江西", "广西",
          "山西", "云南", "贵州", "黑龙江", "吉林", "内蒙古", "新疆", "甘肃", "宁夏", "青海", "海南", "西藏"]


class BatchTests(unittest.TestCase):
    def test_batches_match_the_requested_region_order(self):
        self.assertEqual([v["name"] for v in region_values(1)], BATCH1)
        self.assertEqual([v["name"] for v in region_values(2)], BATCH2)

    def test_region_ids_are_unique_and_cover_31_provinces_plus_two_cities(self):
        ids = [v["id"] for batch in (1, 2) for v in region_values(batch)]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 33)
        provinces = {v["province"] for batch in (1, 2) for v in region_values(batch)}
        self.assertEqual(len(provinces), 31)
        cities = [v for batch in (1, 2) for v in region_values(batch) if v["city"]]
        self.assertEqual({v["city"] for v in cities}, {"440300", "440100"})

    def test_city_regions_declare_their_own_expected_city(self):
        shenzhen = next(v for v in region_values(1) if v["name"] == "深圳")
        self.assertEqual((shenzhen["province"], shenzhen["city"], shenzhen["city_text"]), ("440000", "440300", "深圳市"))
        self.assertEqual(shenzhen["scope"], "city")

    def test_unknown_batch_is_rejected(self):
        with self.assertRaises(ValueError):
            region_values(3)

    def test_scope_validation_rejects_bad_city_province_pairs(self):
        regions = region_values(1)
        broken = [dict(regions[0]), dict(regions[1])]
        broken[1]["city"] = "310000"          # belongs to 上海, not 北京
        broken[1]["province"] = "110000"
        with self.assertRaises(ValueError):
            validate_scope("2024-01-01", "2024-02-01", "task-1", 3.5, 10, 10, broken)

    def test_scope_validation_rejects_duplicates_and_short_delay(self):
        regions = region_values(1)
        with self.assertRaises(ValueError):
            validate_scope("2024-01-01", "2024-02-01", "task-1", 3.5, 10, 10, [regions[0], regions[0]])
        with self.assertRaises(ValueError):
            validate_scope("2024-01-01", "2024-02-01", "task-1", 2.0, 10, 10, regions)

    def test_province_name_suffixes_compare_as_one_region(self):
        self.assertEqual(region_key("北京市"), region_key("北京"))
        self.assertEqual(region_key("广西壮族自治区"), "广西")
        self.assertEqual(region_key("新疆维吾尔自治区"), "新疆")
        self.assertEqual(region_key("宁夏回族自治区"), "宁夏")
        self.assertEqual(region_key("内蒙古自治区"), "内蒙古")
        self.assertNotEqual(region_key("江苏省"), region_key("浙江省"))


class ContractTests(unittest.TestCase):
    def args(self, tmp, **kwargs):
        class A:
            pass
        a = A()
        a.task_id = kwargs.get("task_id", "province-test")
        a.batch = kwargs.get("batch", 1)
        a.start = "2024-01-01"
        a.end = "2024-06-30"
        a.delay = 3.5
        a.max_pages = 100
        a.max_api_calls = 50
        a.max_details = 40
        a.node = "node"
        a.artifact_modules = "modules"
        a.output = str(tmp)
        a.dag_dir = str(tmp / "dags")
        a.python = "python"
        return a

    def test_request_freezes_scope_and_hashes_existing_files(self):
        with tempfile.TemporaryDirectory() as d:
            request = request_for(self.args(Path(d)))
            self.assertEqual(request["scope"], "province_medical_digital_procurement")
            self.assertEqual(request["batch"], 1)
            self.assertEqual(len(request["regions"]), 9)
            self.assertEqual(request["sources"], ["1"])
            self.assertEqual(request["region_order"], "newest_first")
            self.assertTrue(all((Path(__file__).parents[1] / name).exists() for name in request["code_sha256"]))

    def test_dag_has_one_step_per_region_and_a_shared_summary(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            request = request_for(self.args(tmp))
            task_dir = tmp / request["task_id"]
            task_dir.mkdir()
            (task_dir / "request.json").write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            dag = generate_dag(task_dir, tmp / "dags", "python").read_text(encoding="utf-8")
            self.assertEqual(dag.count("run-region --region"), 9)
            self.assertIn("max_active_steps: " + str(MAX_ACTIVE_REGIONS), dag)
            self.assertLessEqual(MAX_ACTIVE_REGIONS, 3)
            self.assertIn("queue: medical-tender-updates", dag)
            self.assertIn("continue_on:", dag)
            summary_block = dag.split("- id: summary")[1]
            for value in request["regions"]:
                self.assertIn("r_" + value["id"], dag)

    def test_shared_pace_keeps_one_aggregate_rate_across_workers(self):
        import argparse
        import time
        from pipeline.research.national_ggzy import Collector

        with tempfile.TemporaryDirectory() as d:
            args = argparse.Namespace(output=d, province_text="江苏省", city_text="",
                                      pace_file=str(Path(d) / "source-pace"), pace_interval=0.4, delay=3.5)
            collector = Collector(args)
            started = time.monotonic()
            collector._shared_pace(0.4)
            collector._shared_pace(0.4)
            self.assertGreaterEqual(time.monotonic() - started, 0.35)
            self.assertTrue((Path(d) / "source-pace").exists())

    def test_shared_pace_ignores_timestamp_from_before_a_reboot(self):
        """A monotonic value from a previous boot must not become a long sleep."""
        import argparse
        import time
        from pipeline.research.national_ggzy import Collector

        with tempfile.TemporaryDirectory() as d:
            pace = Path(d) / "source-pace"
            pace.write_text(str(time.monotonic() + 100000), encoding="utf-8")
            args = argparse.Namespace(output=d, province_text="江苏省", city_text="",
                                      pace_file=str(pace), pace_interval=0.4, delay=3.5)
            started = time.monotonic()
            Collector(args)._shared_pace(0.4)
            self.assertLess(time.monotonic() - started, 1.0)
            self.assertLessEqual(float(pace.read_text(encoding="utf-8")), time.monotonic())

    def test_shared_pace_survives_a_stale_lock(self):
        """A lock left by a killed worker must be reclaimed, not turn fatal."""
        import argparse
        import threading
        import time
        from pipeline.research.national_ggzy import Collector

        with tempfile.TemporaryDirectory() as d:
            pace = Path(d) / "source-pace"
            lock = Path(d) / "source-pace.lck"
            lock.write_text("", encoding="utf-8")
            args = argparse.Namespace(output=d, province_text="江苏省", city_text="",
                                      pace_file=str(pace), pace_interval=0.0, delay=0.0)
            collector = Collector(args)
            worker = threading.Thread(target=collector._shared_pace, args=(0.0,), daemon=True)
            started = time.monotonic()
            worker.start()
            time.sleep(0.3)
            self.assertFalse(pace.exists(), "worker must wait while the lock is held")
            lock.unlink()
            worker.join(10)
            self.assertFalse(worker.is_alive())
            self.assertTrue(pace.exists())
            self.assertLess(time.monotonic() - started, 5)

    def test_plan_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            a = self.args(tmp)
            argv = ["plan", "--task-id", "province-test", "--batch", "1", "--start", "2024-01-01",
                    "--end", "2024-06-30", "--output", str(tmp), "--dag-dir", str(tmp / "dags"),
                    "--python", "python", "--node", "node", "--artifact-modules", "modules",
                    "--max-api-calls", "50", "--max-details", "40", "--dry-run"]
            self.assertEqual(main(argv), 0)
            self.assertFalse((tmp / "province-test").exists())

    def test_changed_budget_cannot_reuse_an_existing_task(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            base = ["plan", "--task-id", "province-test", "--batch", "1", "--start", "2024-01-01",
                    "--end", "2024-06-30", "--output", str(tmp), "--dag-dir", str(tmp / "dags"),
                    "--python", "python", "--node", "node", "--artifact-modules", "modules",
                    "--max-api-calls", "50", "--max-details", "40"]
            self.assertEqual(main(base), 0)
            import contextlib, io
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                self.assertEqual(main(base + ["--resume", "--max-api-calls", "60"]), 2)
            self.assertIn("use a new task ID", error.getvalue())

    def test_summary_dedupes_shared_urls_and_keeps_source_counts(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            request = {"task_id": "t", "batch": 1, "start": "2024-01-01", "end": "2024-12-31",
                       "entry": "test", "regions": [v for v in region_values(1) if v["city"]]}
            (tmp / "request.json").write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            shared = "https://www.ggzy.gov.cn/information/deal/html/a/440000/0202/20240101/x.html"
            for index, value in enumerate(request["regions"]):
                folder = tmp / "regions" / value["id"]
                folder.mkdir(parents=True)
                (folder / "region-progress.json").write_text(json.dumps({"status": "partial" if index else "completed",
                                                                         "pending_search_windows": 3}), encoding="utf-8")
                rows = {"a": {"公告日期": "2024-05-01", "项目名称": "医院信息系统", "相关网页": shared,
                              "省份": value["province_text"], "_region_city_unconfirmed": bool(value["city"])},
                        "b": {"公告日期": "2024-05-02", "项目名称": "影像平台", "相关网页": shared + "-" + value["id"],
                              "省份": value["province_text"]},
                        "c": {"公告日期": "2023-12-31", "项目名称": "范围外", "相关网页": "https://example.gov.cn/out"}}
                (folder / "state.json").write_text(json.dumps({"records": rows}, ensure_ascii=False), encoding="utf-8")
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()):
                summarize(tmp, snapshot=True)
            value = json.loads((tmp / ("snapshot-" + str(__import__("os").getpid()) + ".json")).read_text(encoding="utf-8"))
            self.assertEqual(value["records"], 3)                       # 1 shared + 1 unique per region, out-of-range dropped
            self.assertEqual(value["duplicates_removed"], 1)
            self.assertEqual(value["status"], "partial")
            self.assertEqual(sum(row["records"] for row in value["sources"]), value["records"])
            self.assertEqual(value["city_unconfirmed"], 1)


    def test_publish_keeps_a_traceback_stop_reason_on_one_line(self):
        """A Playwright traceback must not leak newlines or pipes into the table."""
        from pipeline.research.province_update import table_cell
        reason = ("Page.evaluate: TypeError: Failed to fetch\n"
                  "    at eval (eval at evaluate (:370:30), <anonymous>:1:109)\n"
                  "    at UtilityScript.evaluate (<anonymous>:377:18)")
        self.assertEqual(table_cell(reason), "Page.evaluate: TypeError: Failed to fetch")
        self.assertNotIn("|", table_cell("a | b"))
        self.assertLessEqual(len(table_cell("x" * 500)), 96)

    def test_publish_without_target_falls_back_to_the_configured_folder(self):
        """`publish` with no --target must read publish.json instead of doing nothing."""
        import contextlib, io, os
        with tempfile.TemporaryDirectory() as d:
            task = Path(d) / "task"
            (task / "delivery").mkdir(parents=True)
            (task / "request.json").write_text(json.dumps({
                "task_id": "t", "batch": 1, "start": "2024-01-01", "end": "2024-12-31",
                "regions": region_values(1)[:1]}, ensure_ascii=False), encoding="utf-8")
            (task / "publish.json").write_text(json.dumps({"target": str(Path(d) / "handover")}),
                                               encoding="utf-8")
            (task / "delivery" / "公告明细.csv").write_text("表头\n", encoding="utf-8")
            (task / "summary.json").write_text(json.dumps({"batch": 1, "records": 0, "status": "partial",
                                                           "sources": []}), encoding="utf-8")
            previous = os.environ.get("PROVINCE_UPDATE_TASK_DIR")
            os.environ["PROVINCE_UPDATE_TASK_DIR"] = str(task)
            try:
                with contextlib.redirect_stdout(io.StringIO()) as captured:
                    self.assertEqual(main(["publish"]), 0)
            finally:
                if previous is None:
                    os.environ.pop("PROVINCE_UPDATE_TASK_DIR", None)
                else:
                    os.environ["PROVINCE_UPDATE_TASK_DIR"] = previous
            self.assertIn("published", captured.getvalue())
            self.assertTrue((Path(d) / "handover" / "01_地方_分省第1批" / "交付说明_第1批.md").exists())

    def test_publish_copies_a_batch_into_a_numbered_handover_folder(self):
        from pipeline.research.province_update import publish
        import contextlib, io
        with tempfile.TemporaryDirectory() as d:
            task = Path(d) / "task"
            (task / "delivery").mkdir(parents=True)
            request = {"task_id": "t", "batch": 2, "start": "2024-01-01", "end": "2024-12-31",
                       "entry": "test", "regions": region_values(2)[:1]}
            (task / "request.json").write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            (task / "delivery" / "分省医疗数字化采购_第2批_2024年至今.xlsx").write_bytes(b"placeholder")
            (task / "delivery" / "公告明细.csv").write_text("表头\n", encoding="utf-8")
            (task / "summary.json").write_text(json.dumps({
                "batch": 2, "records": 1, "duplicates_removed": 0, "city_unconfirmed": 0,
                "status": "partial", "regions_completed": 0, "sources": [
                    {"source_name": "广东", "scope": "province", "status": "partial",
                     "records": 1, "pending_search_windows": 5}]}, ensure_ascii=False), encoding="utf-8")
            target = Path(d) / "handover"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(publish(task, target), 0)
                self.assertEqual(publish(task, target), 0)          # idempotent overwrite
            folder = target / "02_地方_分省第2批"
            self.assertTrue((folder / "分省医疗数字化采购_第2批_2024年至今.xlsx").exists())
            self.assertEqual(len(list(folder.glob("*.xlsx"))), 1)
            readme = (folder / "交付说明_第2批.md").read_text(encoding="utf-8")
            self.assertIn("未完成检索窗口", readme)
            self.assertIn("不等于各省门户全量", readme)
            self.assertEqual(json.loads((task / "publish-receipt.json").read_text(encoding="utf-8"))["batch"], 2)


if __name__ == "__main__":
    unittest.main()
