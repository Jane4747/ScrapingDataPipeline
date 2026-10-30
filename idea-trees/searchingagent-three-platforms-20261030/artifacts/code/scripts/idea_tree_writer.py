"""Render idea-tree markdown from the richer tree.json used in this repository.

The repository keeps two artefacts per tree: `tree.json` holds node status and the
result counters, `tree.md` is the readable outline. This keeps the two in sync
instead of editing them by hand, which is how facts and outlines used to drift
apart after every new round of work.

Timestamps are preserved by default; pass `--touch` to refresh `updated_at`.
Node status lives only in JSON, matching the existing tree files.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

ALLOWED_STATUS = {'completed', 'partial', 'open', 'planned', 'awaiting_jane'}


def read_tree(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def validate(tree):
    if not isinstance(tree, dict):
        raise ValueError('Tree must be a JSON object')
    for field in ('id', 'created_at', 'updated_at', 'status', 'nodes'):
        if field not in tree:
            raise ValueError(f'Missing tree field: {field}')
    if tree['status'] not in ALLOWED_STATUS:
        raise ValueError(f"Unsupported tree status: {tree['status']}")
    ids = []
    for node in tree['nodes']:
        if node['id'] in ids:
            raise ValueError(f"Duplicate node id: {node['id']}")
        ids.append(node['id'])
        if node.get('status') not in ALLOWED_STATUS:
            raise ValueError(f"Unsupported node status on {node['id']}: {node.get('status')}")
        if node.get('parent') is not None and node['parent'] not in ids and node['parent'] not in tree['nodes']:
            raise ValueError(f"Unknown parent on {node['id']}: {node['parent']}")
    if tree['nodes'] and tree['nodes'][0]['id'] != 'need':
        raise ValueError('First node must be `need`')
    return tree


def render_markdown(tree):
    by_parent = {}
    for node in tree['nodes']:
        by_parent.setdefault(node.get('parent'), []).append(node)
    lines = [
        f"# 想法树 {tree['id']}",
        '',
        f"- 状态：{tree['status']}",
        f"- 创建：{tree['created_at']}",
        f"- 更新：{tree['updated_at']}",
        f"- 工具：{tree.get('tool') or '待确认'}",
        f"- 主题：{tree.get('theme') or '待确认'}",
        f"- 交付：{tree.get('delivery') or '待确认'}",
        '',
        '## 节点',
        '',
    ]

    def walk(parent, depth):
        for node in by_parent.get(parent, []):
            lines.append(f"{'  ' * depth}- **{node['kind']}** `{node['id']}`：{node['text']}")
            walk(node['id'], depth + 1)

    walk(None, 0)
    lines.append('')
    return '\n'.join(lines)


def render_tree(path, touch=False):
    source = Path(path)
    tree = validate(read_tree(source))
    if touch:
        tree['updated_at'] = datetime.now().astimezone().replace(microsecond=0).isoformat()
        source.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding='utf-8')
    markdown = render_markdown(tree)
    target = source.with_name('tree.md')
    target.write_text(markdown, encoding='utf-8')
    return {'tree_id': tree['id'], 'nodes': len(tree['nodes']),
            'markdown': str(target), 'status': tree['status'], 'touch': touch}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--tree', required=True)
    parser.add_argument('--touch', action='store_true', help='Refresh updated_at before rendering')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(render_tree(args.tree, touch=args.touch), ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
