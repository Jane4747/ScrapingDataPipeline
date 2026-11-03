"""Offline tests for rendering idea-tree markdown from tree.json."""
import json
import tempfile
import unittest
from pathlib import Path

from scripts import idea_tree_writer as tool


def sample_tree():
    return {
        'id': 'unit-test-tree',
        'created_at': '2026-10-27T00:00:00+08:00',
        'updated_at': '2026-10-27T00:00:00+08:00',
        'status': 'partial',
        'tool': '离线探针与回写代码',
        'theme': '单元测试主题',
        'delivery': 'tree.md',
        'nodes': [
            {'id': 'need', 'parent': None, 'kind': '需求', 'text': '示例需求', 'status': 'completed'},
            {'id': 'method', 'parent': 'need', 'kind': '方法', 'text': '分批执行', 'status': 'partial'},
            {'id': 'gap', 'parent': 'method', 'kind': '缺口', 'text': '未核实29家', 'status': 'open'},
        ],
        'result': {'records': 3},
    }


class IdeaTreeWriterTests(unittest.TestCase):
    def test_render_matches_readable_outline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'tree.json'
            path.write_text(json.dumps(sample_tree(), ensure_ascii=False), encoding='utf-8')
            result = tool.render_tree(path)
            markdown = Path(result['markdown']).read_text(encoding='utf-8')
            self.assertEqual(result['nodes'], 3)
            self.assertIn('# 想法树 unit-test-tree', markdown)
            self.assertIn('- **需求** `need`：示例需求', markdown)
            self.assertIn('  - **方法** `method`：分批执行', markdown)
            self.assertIn('    - **缺口** `gap`：未核实29家', markdown)
            self.assertIn('- 主题：单元测试主题', markdown)

    def test_touch_refreshes_updated_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'tree.json'
            path.write_text(json.dumps(sample_tree(), ensure_ascii=False), encoding='utf-8')
            tool.render_tree(path, touch=True)
            tree = json.loads(path.read_text(encoding='utf-8'))
            self.assertNotEqual(tree['updated_at'], '2026-10-27T00:00:00+08:00')

    def test_invalid_parent_or_status_is_rejected(self):
        tree = sample_tree()
        tree['nodes'][1]['status'] = 'unknown-status'
        with self.assertRaises(ValueError):
            tool.validate(tree)
        tree = sample_tree()
        tree['nodes'][1]['parent'] = 'missing'
        with self.assertRaises(ValueError):
            tool.validate(tree)

    def test_first_node_must_be_need(self):
        tree = sample_tree()
        tree['nodes'].reverse()
        with self.assertRaises(ValueError):
            tool.validate(tree)


if __name__ == '__main__':
    unittest.main()
