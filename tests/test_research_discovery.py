import argparse
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pipeline.research.config import load_config
from pipeline.research.discovery import (
    BRAVE_ENDPOINT, build_query_plan, load_import, merge_candidates, register,
    search_brave,
)


class Response:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self.payload = {"web": {"results": []}} if payload is None else payload
        self.closed = False

    def iter_content(self, chunk_size):
        yield json.dumps(self.payload).encode("utf-8")

    def close(self):
        self.closed = True


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "version": 1, "topic": "智慧健康部署研究",
            "sources": [
                {"id": "alpha", "name": "甲医疗", "seeds": ["https://example.com/"],
                 "allowed_domains": ["example.com"]},
                {"id": "beta", "name": "乙医疗", "seeds": ["https://example.org/"],
                 "allowed_domains": ["example.org"]},
            ],
        }

    def parser(self):
        parser = argparse.ArgumentParser()
        register(parser.add_subparsers(required=True))
        return parser

    def test_plan_covers_every_source_and_rotates_budget_fairly(self):
        plan = build_query_plan(self.config["sources"], 6)
        self.assertEqual(len(plan), 12)
        self.assertEqual([row["source_id"] for row in plan[:2]], ["alpha", "beta"])
        self.assertEqual(len({row["query_id"] for row in plan}), 12)
        self.assertIn('"甲医疗"', plan[0]["query"])
        self.assertIn("site:example.com", plan[0]["query"])
        self.assertIn("q=", plan[0]["bing_url"])
        bundled_plan = build_query_plan(load_config()["sources"])
        self.assertEqual(len(bundled_plan), 126)
        mobile = next(row for row in bundled_plan if row["source_id"] == "china_mobile")
        self.assertIn('"中国移动"', mobile["query"])
        self.assertNotIn("医疗行业团队", mobile["query"])

    def test_import_checks_allowlist_and_keeps_query_provenance(self):
        original = copy.deepcopy(self.config)
        items = [
            {"source_id": "alpha", "url": "https://news.example.com/case?utm_source=x&id=3#part",
             "title": "医院案例", "query": "甲医疗 试点"},
            {"source_id": "alpha", "url": "https://news.example.com/case?id=3", "query": "甲医疗 验收"},
            {"source_id": "alpha", "url": "https://example.com.evil.org/case"},
            {"source_id": "alpha", "url": "https://evilexample.com/case"},
            {"source_id": "alpha", "url": "https://example.org/case"},
            {"source_id": "new", "url": "https://example.com/case"},
            {"source_id": "beta", "url": "https://example.org/case"},
        ]
        merged, accepted, rejected = merge_candidates(self.config, items, {"alpha"})
        self.assertEqual(self.config, original)
        self.assertEqual(len(accepted), 2)
        self.assertEqual(accepted[0]["outcome"], "added_candidate_seed")
        self.assertEqual(accepted[1]["outcome"], "already_present")
        self.assertEqual(accepted[1]["query"], "甲医疗 验收")
        self.assertTrue(all(item["candidate_only"] for item in accepted))
        self.assertEqual(len(rejected), 5)
        self.assertEqual(merged["sources"][0]["seeds"],
                         ["https://example.com/", "https://news.example.com/case?id=3"])
        self.assertEqual(merged["sources"][0]["allowed_domains"], ["example.com"])

    def test_parent_domain_removes_redundant_queries_without_losing_topics(self):
        source = copy.deepcopy(self.config["sources"][0])
        source["allowed_domains"] = ["www.example.com", "example.com", "news.www.example.com"]
        original = copy.deepcopy(source)
        plan = build_query_plan([source])
        self.assertEqual(source, original)
        self.assertEqual(len(plan), 6)
        self.assertEqual({row["domain"] for row in plan}, {"example.com"})
        self.assertEqual([row["purpose"] for row in plan], [
            "部署与试点", "医院应用案例", "智能装备", "健康与康养", "合作与验收", "战略与年度披露",
        ])
        # The same regression used to affect the bundled Mindray configuration.
        mindray = next(source for source in load_config()["sources"] if source["id"] == "mindray")
        self.assertEqual(len({row["purpose"] for row in build_query_plan([mindray])}), 6)

    def test_nonoverlapping_domains_share_first_six_topics_before_expansion(self):
        source = copy.deepcopy(self.config["sources"][0])
        source["allowed_domains"] = ["example.com", "example.org"]
        plan = build_query_plan([source], max_queries=12)
        self.assertEqual(len(plan), 12)
        self.assertEqual(len({row["purpose"] for row in plan[:6]}), 6)
        self.assertEqual([row["domain"] for row in plan[:6]], ["example.com", "example.org"] * 3)
        self.assertEqual(len({(row["purpose"], row["domain"]) for row in plan}), 12)
        self.assertEqual(len({row["query_id"] for row in plan}), 12)
        for purpose in {row["purpose"] for row in plan}:
            self.assertEqual({row["domain"] for row in plan if row["purpose"] == purpose},
                             {"example.com", "example.org"})

    def test_malformed_candidates_are_rejected_without_creating_invalid_config(self):
        urls = ["file:///tmp/data", "https://user:pass@example.com/", "https://127.0.0.1/",
                "https://example.com:8000/", "https://example.com/a b",
                "https://example.com\\other", "", None]
        items = [{"source_id": "alpha", "url": url} for url in urls] + [None, {"source_id": []}]
        merged, accepted, rejected = merge_candidates(self.config, items)
        self.assertEqual(accepted, [])
        self.assertEqual(len(rejected), len(items))
        self.assertEqual(merged, self.config)

    def test_malformed_subdomains_cannot_poison_saved_source_registry(self):
        urls = ["https://_private.example.com/case", "https://-news.example.com/case",
                "https://news-.example.com/case", "https://news..example.com/case",
                "https://" + "a" * 64 + ".example.com/case"]
        items = [{"source_id": "alpha", "url": url} for url in urls]
        items.append({"source_id": "alpha", "url": "https://News.Example.com/case#section"})
        merged, accepted, rejected = merge_candidates(self.config, items)
        self.assertEqual(len(rejected), len(urls))
        self.assertEqual({row["reason"] for row in rejected}, {"invalid_url"})
        self.assertEqual([row["normalized_url"] for row in accepted], ["https://news.example.com/case"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.discovered.json"
            path.write_text(json.dumps(merged), encoding="utf-8")
            self.assertEqual(load_config(path), merged)

    def test_task_topics_replace_defaults_and_keep_source_budget_balanced(self):
        topics = [{"purpose": "养老采购", "terms": "养老 采购 中标"},
                  {"purpose": "项目验收", "terms": "康养 验收"}]
        original = copy.deepcopy(topics)
        plan = build_query_plan(self.config["sources"], 6, query_topics=topics)
        self.assertEqual(len(plan), 4)
        self.assertEqual([row["source_id"] for row in plan], ["alpha", "beta", "alpha", "beta"])
        self.assertEqual([row["purpose"] for row in plan], ["养老采购"] * 2 + ["项目验收"] * 2)
        self.assertIn("养老 采购 中标 site:example.com", plan[0]["query"])
        self.assertEqual(topics, original)
        for value in ([], {}, [None], [{"purpose": "项目", "terms": " "}],
                      [{"purpose": "项目", "terms": 1}]):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "query_topics"):
                build_query_plan(self.config["sources"], query_topics=value)

    def test_default_plan_and_local_import_do_not_network_or_change_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_text = json.dumps(self.config, ensure_ascii=False)
            config_path.write_text(config_text, encoding="utf-8")
            import_path = root / "import.json"
            import_path.write_text(json.dumps([
                {"source_id": "alpha", "url": "https://example.com/project",
                 "title": "项目部署", "query": "甲医疗 项目"},
                {"source_id": "alpha", "url": "https://hospital.org/project"},
            ]), encoding="utf-8")
            output = root / "output"
            args = self.parser().parse_args(["discover", "--config", str(config_path),
                                            "--output-dir", str(output), "--import-results", str(import_path)])
            with patch("pipeline.research.discovery.search_brave") as brave, \
                    patch("requests.Session.get") as network, patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(args.func(args), 0)
                brave.assert_not_called()
                network.assert_not_called()
            self.assertEqual(config_path.read_text(encoding="utf-8"), config_text)
            merged = load_config(output / "config.discovered.json")
            self.assertIn("https://example.com/project", merged["sources"][0]["seeds"])
            summary = json.loads((output / "discovery_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["added_seeds"], 1)
            self.assertEqual(summary["rejected_candidates"], 1)
            self.assertEqual(summary["api_requests"], 0)
            self.assertTrue((output / "query_plan.csv").exists())
            self.assertIn("搜索结果仅为候选链接", (output / "query_plan.md").read_text(encoding="utf-8"))
            self.assertFalse((output / "discovery.lock").exists())
            with self.assertRaisesRegex(ValueError, "输出目录已有文件"):
                args.func(args)

    def test_rejects_invalid_import_root_and_does_not_touch_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / "invalid.json"
            file.write_text('{"results": []}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON 数组"):
                load_import(file)
            saved = root / "saved.txt"
            saved.write_text("user content", encoding="utf-8")
            args = self.parser().parse_args(["discover", "--output-dir", str(root)])
            with self.assertRaisesRegex(ValueError, "输出目录已有文件"):
                args.func(args)
            self.assertEqual(saved.read_text(encoding="utf-8"), "user content")

    def test_brave_auth_and_rate_limit_stop_without_echoing_credentials(self):
        plan = build_query_plan(self.config["sources"], 2)
        for code, reason in ((401, "authentication_failed"), (429, "rate_limited")):
            with self.subTest(code=code), patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "private-key"}):
                response = Response(code, {"error": "private-key"})
                session = Session([response])
                hits, statuses = search_brave(plan, session=session)
                self.assertEqual(len(session.calls), 1)
                self.assertEqual(hits, [])
                self.assertEqual(statuses[0]["reason"], reason)
                self.assertTrue(all(row["status"] == "not_requested" for row in statuses[1:]))
                self.assertNotIn("private-key", json.dumps(statuses))
                self.assertTrue(response.closed)

    def test_brave_budget_fixed_origin_no_redirects_and_count_limit(self):
        plan = build_query_plan(self.config["sources"], 2)
        payload = {"web": {"results": [{"url": "https://example.com/case", "title": "Case"},
                                          {"url": "https://example.com/extra"}]}}
        session = Session([Response(payload=payload)])
        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "private-key"}), \
                patch("pipeline.research.discovery.time.sleep") as sleep:
            hits, statuses = search_brave(plan, results_per_query=1, budget=1, session=session)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["query"], plan[0]["query"])
        self.assertEqual(session.calls[0][0], BRAVE_ENDPOINT)
        self.assertFalse(session.calls[0][1]["allow_redirects"])
        self.assertTrue(session.calls[0][1]["stream"])
        self.assertEqual(session.calls[0][1]["params"]["count"], 1)
        self.assertEqual(statuses[1]["reason"], "api_budget_exhausted")
        sleep.assert_not_called()

    def test_missing_key_and_invalid_limits_fail_before_requests(self):
        plan = build_query_plan(self.config["sources"], 1)
        with patch.dict(os.environ, {}, clear=True), patch("requests.Session.get") as network:
            with self.assertRaisesRegex(ValueError, "BRAVE_SEARCH_API_KEY"):
                search_brave(plan)
            network.assert_not_called()
        for kwargs in ({"budget": 31}, {"results_per_query": 21}, {"delay": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                search_brave(plan, **kwargs)


if __name__ == "__main__":
    unittest.main()
