import copy
import json
from pathlib import Path
import tempfile
import unittest

from pipeline.research.config import load_config


class ResearchConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "version": 1,
            "topic": "智能医疗装备技术研究",
            "sources": [{"id": "sample", "name": "示例", "seeds": ["https://www.example.com/medical"],
                         "allowed_domains": ["example.com"]}],
        }

    def load(self, config):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.json"
            path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            return load_config(path)

    def test_bundled_registry_preserves_all_21_platforms(self):
        config = load_config()
        self.assertEqual(len(config["sources"]), 21)
        sources = {source["id"]: source for source in config["sources"]}
        self.assertEqual(set(sources), {
            "genertec_health", "cr_healthcare", "sinopharm_healthcare", "cecloud", "shecc",
            "china_mobile", "china_telecom", "china_unicom", "shandong_healthcare",
            "beijing_elderly_care", "inspur_health", "yunnan_investment_health", "mindray",
            "united_imaging", "medbot", "tinavi", "edgemed", "fourier", "ai_robotics",
            "iflytek_healthcare", "yidu_tech",
        })
        self.assertIn("https://chinamobileltd.com/sc/esg/sd/2023_ashare/04.pdf", sources["china_mobile"]["seeds"])
        self.assertIn("https://cn.tinavi.com/index.php?a=type&c=article&tid=1", sources["tinavi"]["seeds"])
        for source in sources.values():
            self.assertEqual(set(source), {"id", "name", "seeds", "allowed_domains"})

    def test_custom_subset_and_dot_separated_subdomain_allowed(self):
        self.assertEqual(self.load(self.config), self.config)

    def test_duplicate_ids_rejected(self):
        self.config["sources"].append(copy.deepcopy(self.config["sources"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate source id"):
            self.load(self.config)

    def test_empty_and_nonlist_registry_rejected(self):
        for value in ([], {}, None, "sources"):
            with self.subTest(value=value):
                self.config["sources"] = value
                with self.assertRaisesRegex(ValueError, "1..1000 sources"):
                    self.load(self.config)

    def test_invalid_urls_and_lookalike_domains_rejected(self):
        for url in ("file:///tmp/secret", "javascript:alert(1)", "https://example.com.evil.org/",
                    "https://evilexample.com/", "https://example.com@evil.org/", "https://user@example.com/",
                    "https://127.0.0.1/", "https://example.com:8000/", "https://example.com/a b",
                    "https://example.com:invalid/", "https://example.com\\@evil.org/"):
            with self.subTest(url=url):
                self.config["sources"][0]["seeds"] = [url]
                with self.assertRaises(ValueError):
                    self.load(self.config)

    def test_invalid_domain_allowlists_rejected(self):
        for domains in ([], ["*.example.com"], ["https://example.com"], ["example.com/path"],
                        ["localhost"], ["example.com:443"], ["example.com", "example.com"], [None]):
            with self.subTest(domains=domains):
                self.config["sources"][0]["allowed_domains"] = domains
                with self.assertRaises(ValueError):
                    self.load(self.config)

    def test_version_and_topic_are_validated(self):
        for version in (True, 2, "1", None):
            with self.subTest(version=version):
                candidate = copy.deepcopy(self.config)
                candidate["version"] = version
                with self.assertRaisesRegex(ValueError, "version"):
                    self.load(candidate)
        self.config["topic"] = " "
        with self.assertRaisesRegex(ValueError, "topic"):
            self.load(self.config)

    def test_invalid_seed_and_id_types_raise_clear_value_error(self):
        for field, value in (("id", []), ("id", "../escape"), ("seeds", [None]), ("seeds", []),
                             ("name", ""), ("allowed_domains", "example.com")):
            with self.subTest(field=field, value=value):
                candidate = copy.deepcopy(self.config)
                candidate["sources"][0][field] = value
                with self.assertRaises(ValueError):
                    self.load(candidate)


if __name__ == "__main__":
    unittest.main()
