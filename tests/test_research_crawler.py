import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pipeline.research.crawler import ResearchCrawler, link_priority
from pipeline.research.export import export_results


SOURCE = {"id": "test", "name": "测试平台", "seeds": ["https://example.com/"], "allowed_domains": ["example.com"]}


class FakeFetcher:
    calls = []
    responses = {}

    def __init__(self, **kwargs):
        pass

    def fetch(self, url, allowed_domains):
        self.calls.append(url)
        result = self.responses.get(url, {"status": "error", "error": "fixture missing"})
        return {"requested_url": url, "url": url, "title": "手术机器人技术研究", "text": "手术机器人采用高精度导航与力反馈控制，完成临床验证。",
                "content_type": "text/html", "method": "http", "links": [], **result}

    def close(self):
        pass


class CrawlerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        FakeFetcher.calls = []
        FakeFetcher.responses = {
            "https://example.com/": {"status": "ok", "links": [
                {"url": "https://example.com/product/robot", "text": "手术机器人产品"},
                {"url": "https://outside.example/product/robot", "text": "手术机器人"},
                {"url": "https://example.com/career", "text": "人才招聘"}]},
            "https://example.com/product/robot": {"status": "ok", "text": "康复机器人采用力控技术，提供个性化步态训练和康复评价。"}}

    def tearDown(self):
        self.temp.cleanup()

    def crawler(self, **kwargs):
        return ResearchCrawler(self.folder, fetcher_factory=FakeFetcher, **kwargs)

    def test_scope_budget_and_resume(self):
        first = self.crawler(max_pages=1).collect([SOURCE])[0]
        self.assertEqual(first["status"], "partial")
        self.assertEqual(len(first["pages"]), 1)
        self.assertEqual(FakeFetcher.calls, ["https://example.com/"])
        second = self.crawler(max_pages=3, resume=True).collect([SOURCE])[0]
        self.assertEqual(len(second["pages"]), 2)
        self.assertEqual(FakeFetcher.calls, ["https://example.com/", "https://example.com/product/robot"])
        self.assertEqual(second["status"], "completed")

    def test_failure_is_not_empty_success_and_can_retry(self):
        FakeFetcher.responses["https://example.com/"] = {"status": "robots_denied", "error": "disallowed"}
        first = self.crawler().collect([SOURCE])[0]
        self.assertEqual(first["status"], "failed")
        self.assertEqual(first["records"], [])
        FakeFetcher.responses["https://example.com/"] = {"status": "ok"}
        second = self.crawler(resume=True, retry_failed=True).collect([SOURCE])[0]
        self.assertEqual(second["status"], "completed")
        self.assertEqual(second["failed_pages"], 0)

    def test_config_change_is_rejected_on_resume(self):
        self.crawler(max_pages=1).collect([SOURCE])
        changed = {**SOURCE, "seeds": ["https://example.com/other"]}
        with self.assertRaisesRegex(ValueError, "配置已变化"):
            self.crawler(resume=True).collect([changed])
        state = json.loads((self.folder / "sources/test/state.json").read_text(encoding="utf-8"))
        self.assertEqual(len(state["pages"]), 1)

    def test_content_duplicate_keeps_one_record_and_provenance(self):
        FakeFetcher.responses["https://example.com/product/robot"].pop("text")
        result = self.crawler().collect([SOURCE])[0]
        self.assertEqual(len(result["pages"]), 2)
        self.assertEqual(len(result["records"]), 1)
        self.assertIn("duplicate_of", result["pages"][1])

    def test_exports_failures_and_coverage(self):
        FakeFetcher.responses["https://example.com/product/robot"] = {"status": "blocked", "error": "HTTP 403"}
        result = self.crawler().collect([SOURCE])
        manifest = export_results(result, self.folder, "智能医疗装备")
        self.assertEqual(manifest["status"], "partial")
        self.assertEqual(manifest["failed_pages"], 1)
        failures = json.loads((self.folder / "failures.json").read_text(encoding="utf-8"))
        self.assertEqual(failures[0]["status"], "blocked")
        self.assertTrue((self.folder / "research.md").exists())

    def test_resume_higher_depth_rebuilds_frontier(self):
        self.crawler(max_depth=0).collect([SOURCE])
        self.crawler(max_depth=1, resume=True).collect([SOURCE])
        self.assertIn("https://example.com/product/robot", FakeFetcher.calls)

    def test_link_priority_skips_assets_and_jobs(self):
        self.assertLess(link_priority("https://example.com/logo.png", "医疗装备"), 0)
        self.assertLess(link_priority("https://example.com/jobs", "人才招聘"), 0)
        self.assertGreater(link_priority("https://example.com/product", "腔镜手术机器人"), 0)

    def test_reprocess_uses_saved_text_without_network(self):
        first = self.crawler(max_pages=1).collect([SOURCE])[0]
        calls = list(FakeFetcher.calls)
        second = self.crawler(resume=True, reprocess=True).collect([SOURCE])[0]
        self.assertEqual(FakeFetcher.calls, calls)
        self.assertEqual(first["records"][0]["collected_at"], second["records"][0]["collected_at"])
        self.assertEqual(second["status"], "partial")

    def test_failed_reprocess_preserves_all_old_records_and_paths(self):
        first = self.crawler().collect([SOURCE])[0]
        state_path = self.folder / "sources/test/state.json"
        before = state_path.read_bytes()
        second_text = self.folder / first["pages"][1]["text_file"]
        second_text.unlink()
        result = self.crawler(resume=True, reprocess=True).collect([SOURCE])[0]
        self.assertEqual(state_path.read_bytes(), before)
        self.assertEqual(len(result["records"]), len(first["records"]))
        self.assertIn("缓存重新解析失败", result["error"])
        self.assertEqual(result["pages"][1]["text_file"], first["pages"][1]["text_file"])

    def test_returned_parse_error_does_not_delete_prior_evidence(self):
        FakeFetcher.responses["https://example.com/"]["raw"] = b"<html>cached</html>"
        first = self.crawler(max_pages=1).collect([SOURCE])[0]
        state_path = self.folder / "sources/test/state.json"
        before = state_path.read_bytes()
        with patch.object(FakeFetcher, "extract_cached", create=True,
                          return_value={"status": "unsupported", "error": "missing parser"}):
            result = self.crawler(resume=True, reprocess=True).collect([SOURCE])[0]
        self.assertEqual(state_path.read_bytes(), before)
        self.assertEqual(result["records"], first["records"])


if __name__ == "__main__":
    unittest.main()
