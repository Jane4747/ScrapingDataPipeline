import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from pipeline.research.deployments import build_index, csv_safe, extract_evidence, register


class DeploymentEvidenceTest(unittest.TestCase):
    def signals(self, text):
        return {row["signal_type"] for row in extract_evidence(text)}

    def test_operational_claim_stays_an_unverified_source_statement(self):
        rows = extract_evidence("该集团已在医院部署智能监护设备。")
        self.assertEqual({row["signal_type"] for row in rows}, {"operational_claim"})
        self.assertTrue(all(row["review_status"] == "待人工核验" for row in rows))
        self.assertTrue(all(row["evidence_basis"] == "来源原文陈述" for row in rows))

    def test_plan_and_negation_do_not_become_operational(self):
        examples = (
            ("计划在医院部署机器人。", {"plan"}),
            ("未来将在养老院上线智慧照护平台。", {"plan"}),
            ("智慧医院项目尚未实际落地。", {"uncertain"}),
            ("医疗设备部署尚未完成。", {"uncertain"}),
            ("尚未签署康养服务合作协议。", {"uncertain"}),
            ("规划在医院开展试点，并部署医疗机器人。", {"plan"}),
        )
        for text, expected in examples:
            with self.subTest(text=text):
                self.assertEqual(self.signals(text), expected)

    def test_distinct_signals_can_coexist_without_promoting_a_pilot(self):
        self.assertEqual(self.signals("医院与公司签署合作协议，共建康复中心。"), {"collaboration"})
        self.assertEqual(self.signals("康复机器人在医院上线试点。"), {"pilot"})
        self.assertEqual(self.signals("公司签署智慧康养合作协议并发布照护平台。"), {"collaboration", "product_release"})
        self.assertEqual(self.signals("医院已部署医疗机器人，未来计划扩大覆盖。"), {"operational_claim", "plan"})

    def test_postposed_future_modifiers_do_not_become_operational(self):
        for text in (
            "智慧健康平台上线时间预计为2027年。",
            "医院系统部署将于明年完成。",
            "医院医疗机器人部署计划于2027年推进。",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.signals(text), {"plan"})
        self.assertEqual(self.signals("医院医疗机器人已部署，未来计划扩大覆盖。"), {"operational_claim", "plan"})

    def test_earlier_plan_does_not_override_a_later_completed_claim(self):
        for text in (
            "公司计划扩大医疗服务范围，目前已在医院部署智能监护设备。",
            "医院规划开展康复试点，但目前已部署手术机器人系统。",
            "医院计划扩大覆盖。该医院已经部署医疗机器人。",
        ):
            with self.subTest(text=text):
                self.assertIn("operational_claim", self.signals(text))
        # A conjunction without its own completed claim still inherits scope.
        self.assertEqual(self.signals("规划在医院开展试点，并部署医疗机器人。"), {"plan"})
        self.assertNotIn("operational_claim", self.signals("规划在医院试点，并正式部署医疗机器人。"))

    def test_channel_names_and_floor_standing_equipment_are_not_actions(self):
        for text in (
            "该公司提供线上线下一体化医疗健康服务。",
            "医院医疗设备配有落地支架稳定器，便于医护人员操作。",
            "医疗设备采用落地式机柜和落地灯设计。",
        ):
            with self.subTest(text=text):
                self.assertEqual(extract_evidence(text), [])
        # Do not suppress genuine actions elsewhere in the same sentence.
        self.assertEqual(self.signals("线上线下医疗服务平台已正式上线。"), {"operational_claim"})
        self.assertEqual(self.signals("医院配备落地支架稳定器，医疗机器人项目已经落地。"), {"operational_claim"})

    def test_document_release_is_not_a_product_deployment(self):
        self.assertEqual(self.signals("公司发布医疗机器人发展白皮书。"), {"uncertain"})
        self.assertEqual(self.signals("公司发布新一代手术机器人系统。"), {"product_release"})

    def test_hypothetical_deployment_and_noise_are_not_operational(self):
        self.assertEqual(self.signals("该医疗平台可以部署在私有云。"), {"uncertain"})
        self.assertEqual(self.signals("智慧医疗部署方案。"), {"uncertain"})
        self.assertEqual(extract_evidence("康养合作\n人才招聘：负责医疗机器人部署。\n版权所有，智慧医院合作平台。"), [])

    def test_generic_eldercare_is_not_automatically_smart_eldercare(self):
        rows = extract_evidence("该集团与养老机构签署康养照护合作协议。")
        self.assertTrue(rows)
        self.assertTrue(all("医养与照护" in row["topic_tags"] for row in rows))
        self.assertTrue(all("智慧康养" not in row["topic_tags"] for row in rows))
        smart_rows = extract_evidence("医院正式上线智慧养老平台与智能照护系统。")
        self.assertTrue(any("智慧康养" in row["topic_tags"] for row in smart_rows))

    def test_administrative_directives_are_not_deployment_actions(self):
        for text in (
            "积极培育健康养老现代服务业的决策部署而建立的专业化平台公司。",
            "医疗单位根据工作部署推进研究。",
            "医疗健康部门组织安排部署相关事项。",
        ):
            with self.subTest(text=text):
                self.assertEqual(extract_evidence(text), [])
        self.assertEqual(self.signals("按照工作部署，医院已部署医疗机器人。"), {"operational_claim"})

    def test_bare_unrelated_operations_do_not_prove_health_deployment(self):
        text = "双方就清洁能源开发、热电项目运营、文旅康养合作等领域展开座谈交流。"
        self.assertEqual(self.signals(text), {"collaboration"})
        for text in ("公司负责运营智慧健康平台。", "养老平台已经运营。", "医疗服务平台正式运营。"):
            with self.subTest(text=text):
                self.assertEqual(self.signals(text), {"operational_claim"})

    def test_clinical_risk_model_is_found_without_a_hospital_word(self):
        text = "这套病情恶化早期预警模型上线后，从2024年2月至2025年3月，持续提供预警服务。"
        rows = extract_evidence(text)
        self.assertEqual({row["signal_type"] for row in rows}, {"operational_claim"})
        self.assertTrue(all("医疗健康服务" in row["topic_tags"] for row in rows))

    def test_words_must_be_close_in_body_not_just_title_or_navigation(self):
        self.assertEqual(extract_evidence("医疗\n新闻\n公司发布财报。"), [])
        self.assertEqual(extract_evidence("医疗" + "无关信息" * 40 + "部署服务器。"), [])
        self.assertEqual(extract_evidence("医院与医疗产业发展论坛。"), [])

    def test_pdf_page_and_paragraph_are_auditable(self):
        rows = extract_evidence("[第 2 页]\n概览\n医院上线智慧医疗平台。\n\n[第 3 页]\n养老机构计划部署照护机器人。")
        self.assertEqual([(r["pdf_page"], r["paragraph_index"]) for r in rows], [(2, 2), (3, 3)])

    def test_csv_prevents_formula_prefixes(self):
        for value in ("=SUM(1,2)", " +cmd", "-2+3", "@SUM(1)", "\t=cmd", "\nhello"):
            with self.subTest(value=value):
                self.assertTrue(csv_safe(value).startswith("'"))
        self.assertEqual(csv_safe("正常原文"), "正常原文")
        self.assertEqual(csv_safe(["康复", "医疗"]), "康复、医疗")

    def test_all_ok_pages_including_nontechnical_pages_and_truncation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "body.txt").write_text("康养机构建成养老中心。\n公司计划部署养老服务平台。", encoding="utf-8")
            (root / "raw.html").write_text("<p>完整页面</p>", encoding="utf-8")
            pages = [
                {"source_id": "elder", "source_name": "=恶意公式", "status": "ok", "relevance": "none", "url": "https://example.com/a",
                 "title": "医养布局", "text_file": "body.txt", "raw_file": "raw.html", "fetched_at": "2026-10-22T00:00:00Z"},
                {"source_id": "failed", "source_name": "失败平台", "status": "blocked", "text_file": "does-not-exist.txt"},
            ]
            (root / "pages.json").write_text(json.dumps(pages), encoding="utf-8")
            # Deliberately no records.json: excluded crawler pages must be used.
            summary = build_index(root, max_per_page=1)
            output = root / "deployment-index"
            rows = json.loads((output / "deployment_evidence.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["source_count"], 2)
            self.assertEqual(summary["processed_pages"], 1)
            self.assertEqual(summary["matched_source_count"], 1)
            self.assertEqual(summary["truncated_page_count"], 1)
            self.assertEqual(summary["omitted_evidence_count"], 1)
            self.assertEqual(rows[0]["published_at"], "")
            self.assertEqual(rows[0]["collected_at"], pages[0]["fetched_at"])
            self.assertEqual(rows[0]["source_run"], str(root.resolve()))
            self.assertEqual(Path(rows[0]["text_path"]), root / "body.txt")
            self.assertEqual(rows[0]["raw_file"], "raw.html")
            self.assertTrue((output / "deployment_evidence.csv").read_bytes().startswith(b"\xef\xbb\xbf"))
            with (output / "deployment_evidence.csv").open(encoding="utf-8-sig", newline="") as handle:
                self.assertEqual(next(csv.DictReader(handle))["source_name"], "'=恶意公式")
            self.assertEqual((root / "body.txt").read_text(encoding="utf-8"), "康养机构建成养老中心。\n公司计划部署养老服务平台。")

    def test_existing_nonempty_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pages.json").write_text("[]", encoding="utf-8")
            output = root / "deployment-index"
            output.mkdir()
            protected = output / "summary.json"
            protected.write_text("existing-result", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "--output-dir"):
                build_index(root)
            self.assertEqual(protected.read_text(encoding="utf-8"), "existing-result")
            empty = root / "empty-index"
            empty.mkdir()
            build_index(root, empty)
            self.assertTrue((empty / "summary.json").is_file())

    def test_concurrent_index_run_cannot_write_or_release_the_owners_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "body.txt").write_text("医院已部署医疗机器人。", encoding="utf-8")
            (root / "pages.json").write_text(json.dumps([
                {"status": "ok", "text_file": "body.txt", "source_id": "owner"}
            ]), encoding="utf-8")
            output = root / "output"
            entered, release = threading.Event(), threading.Event()

            def hold_first_run(text, **kwargs):
                if not entered.is_set():
                    entered.set()
                    if not release.wait(5):
                        raise RuntimeError("test did not release owner")
                return extract_evidence(text, **kwargs)

            with patch("pipeline.research.deployments.extract_evidence", side_effect=hold_first_run), \
                    ThreadPoolExecutor(max_workers=2) as executor:
                owner = executor.submit(build_index, root, output)
                try:
                    self.assertTrue(entered.wait(5))
                    other = executor.submit(build_index, root, output)
                    with self.assertRaisesRegex(ValueError, "--output-dir"):
                        other.result(timeout=5)
                    self.assertTrue((output / "evidence.lock").is_file())
                finally:
                    release.set()
                self.assertEqual(owner.result(timeout=5)["evidence_count"], 1)
            self.assertFalse((output / "evidence.lock").exists())
            rows = json.loads((output / "deployment_evidence.json").read_text(encoding="utf-8"))
            self.assertEqual([row["source_id"] for row in rows], ["owner"])

    def test_failure_releases_its_lock_and_allows_retry_when_no_output_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pages.json").write_text("[]", encoding="utf-8")
            output = root / "output"
            with patch("pipeline.research.deployments._write_json", side_effect=OSError("disk failure")):
                with self.assertRaisesRegex(OSError, "disk failure"):
                    build_index(root, output)
            self.assertFalse((output / "evidence.lock").exists())
            self.assertEqual(list(output.iterdir()), [])
            self.assertEqual(build_index(root, output)["processed_pages"], 0)

    def test_file_added_during_processing_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "body.txt").write_text("医院已部署医疗机器人。", encoding="utf-8")
            (root / "pages.json").write_text(json.dumps([
                {"status": "ok", "text_file": "body.txt"}
            ]), encoding="utf-8")
            output = root / "output"
            protected = output / "summary.json"

            def add_external_file(text, **kwargs):
                protected.write_text("external document", encoding="utf-8")
                return extract_evidence(text, **kwargs)

            with patch("pipeline.research.deployments.extract_evidence", side_effect=add_external_file):
                with self.assertRaises(FileExistsError):
                    build_index(root, output)
            self.assertEqual(protected.read_text(encoding="utf-8"), "external document")
            self.assertFalse((output / "evidence.lock").exists())

    def test_external_paths_are_rejected_and_errors_are_visible(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "input"
            root.mkdir()
            (parent / "outside.txt").write_text("医疗平台已经上线。", encoding="utf-8")
            (root / "pages.json").write_text(json.dumps([
                {"status": "ok", "text_file": "../outside.txt"},
                {"status": "ok", "text_file": str(parent / "outside.txt")},
                {"status": "ok", "text_file": "missing.txt"},
            ]), encoding="utf-8")
            summary = build_index(root)
            self.assertEqual(summary["processed_pages"], 0)
            self.assertEqual(summary["evidence_count"], 0)
            self.assertEqual(len(summary["read_errors"]), 3)
            self.assertIn("超出", summary["read_errors"][0]["error"])
            with self.assertRaises(ValueError):
                build_index(root, root)

    def test_register_has_no_network_or_runtime_dependency(self):
        parser = argparse.ArgumentParser()
        register(parser.add_subparsers())
        args = parser.parse_args(["evidence", "--input-dir", "data"])
        self.assertEqual(args.input_dir, Path("data"))
        self.assertEqual(args.max_per_page, 30)
        self.assertTrue(callable(args.func))

    def test_date_filter_keeps_unknown_and_skips_known_out_of_range_and_jobs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "body.txt").write_text("康养机构已建成养老中心。", encoding="utf-8")
            pages = [{"status": "ok", "text_file": "body.txt", "title": title,
                      "published_at": publication, "url": f"https://example.com/{index}"}
                     for index, (title, publication) in enumerate([
                         ("养老项目", "2020-01-01"), ("养老项目", "2025-10-22T10:00:00Z"),
                         ("养老项目", ""), ("养老招聘职位", "2025-10-22"),
                         ("养老项目", "2027-01-01"),
                     ])]
            (root / "pages.json").write_text(json.dumps(pages), encoding="utf-8")
            summary = build_index(root, since="2021-01-01", until="2026-10-22")
            self.assertEqual(summary["processed_pages"], 2)
            self.assertEqual(summary["unknown_publication_date_pages"], 1)
            self.assertEqual(len(summary["skipped_pages"]), 3)
            with self.assertRaises(ValueError):
                build_index(root, since="2026-10-23", until="2026-10-22")


if __name__ == "__main__":
    unittest.main()
