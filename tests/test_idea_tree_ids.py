import json
import unittest

from pipeline.idea_tree import add_node, find_node, render_markdown, upsert_node


def make_tree():
    return {"id": "t", "status": "running", "created_at": "", "updated_at": "",
            "theme": None, "delivery": None, "tool": "goverment_spider",
            "nodes": [{"id": "need", "parent": None, "kind": "requirement", "at": "", "text": "需求"},
                      {"id": "route", "parent": "need", "kind": "choice", "at": "", "text": "选型"}]}


class IdeaTreeIdTest(unittest.TestCase):
    def test_same_id_added_twice_gets_suffix(self):
        tree = make_tree()
        add_node(tree, "run", "route", "action", "第一次")
        add_node(tree, "run", "route", "action", "第二次")
        ids = [n["id"] for n in tree["nodes"]]
        self.assertEqual(ids.count("run"), 1)
        self.assertIn("run-2", ids)
        self.assertEqual(len(ids), len(set(ids)))

    def test_upsert_rewrites_instead_of_duplicating(self):
        tree = make_tree()
        upsert_node(tree, "theme", "route", "decision", "主题A")
        upsert_node(tree, "theme", "route", "decision", "主题B")
        themes = [n for n in tree["nodes"] if n["id"] == "theme"]
        self.assertEqual(len(themes), 1)
        self.assertEqual(themes[0]["text"], "主题B")

    def test_upsert_creates_when_missing(self):
        tree = make_tree()
        upsert_node(tree, "delivery", "theme", "decision", "json")
        self.assertIsNotNone(find_node(tree, "delivery"))

    def test_render_does_not_repeat_shared_ids(self):
        tree = make_tree()
        for index in range(3):
            add_node(tree, "run", "route", "action", f"第{index + 1}次")
        text = render_markdown(tree)
        self.assertEqual(text.count("**action**"), 3)
        self.assertEqual(text.count("`run`"), 1)

    def test_ids_stay_unique_across_many_runs(self):
        tree = make_tree()
        for _ in range(10):
            add_node(tree, "run", "route", "action", "执行")
        ids = [n["id"] for n in tree["nodes"]]
        self.assertEqual(len(ids), len(set(ids)))
        json.dumps(tree, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
