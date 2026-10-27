import json
from datetime import datetime
from pathlib import Path

from pipeline.catalog import TREES


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def tree_dir(tree_id: str) -> Path:
    return TREES / tree_id


def create_tree(requirement: str, route: dict) -> dict:
    tree_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    tree = {
        "id": tree_id,
        "created_at": _now(),
        "updated_at": _now(),
        "status": "awaiting_jane",
        "requirement": requirement,
        "theme": None,
        "delivery": None,
        "tool": route["tool"],
        "route": route,
        "nodes": [
            {
                "id": "need",
                "parent": None,
                "kind": "requirement",
                "at": _now(),
                "text": requirement,
            },
            {
                "id": "route",
                "parent": "need",
                "kind": "choice",
                "at": _now(),
                "text": _route_text(route),
                "tool": route["tool"],
            },
        ],
    }
    save_tree(tree)
    return tree


def load_tree(tree_id: str) -> dict:
    path = tree_dir(tree_id) / "tree.json"
    return json.loads(path.read_text(encoding="utf-8"))


def save_tree(tree: dict) -> Path:
    folder = tree_dir(tree["id"])
    folder.mkdir(parents=True, exist_ok=True)
    tree["updated_at"] = _now()
    (folder / "tree.json").write_text(
        json.dumps(tree, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (folder / "tree.md").write_text(render_markdown(tree), encoding="utf-8")
    return folder


def add_node(tree: dict, node_id: str, parent: str, kind: str, text: str, **extra) -> None:
    tree["nodes"].append(
        {
            "id": node_id,
            "parent": parent,
            "kind": kind,
            "at": _now(),
            "text": text,
            **extra,
        }
    )


def render_markdown(tree: dict) -> str:
    lines = [
        f"# 想法树 {tree['id']}",
        "",
        f"- 状态：{tree['status']}",
        f"- 创建：{tree['created_at']}",
        f"- 更新：{tree['updated_at']}",
        f"- 工具：{tree.get('tool') or '待确认'}",
        f"- 主题：{tree.get('theme') or '待 Jane 确认'}",
        f"- 交付：{tree.get('delivery') or '待 Jane 确认'}",
        "",
        "## 节点",
        "",
    ]
    by_parent: dict[str | None, list] = {}
    for node in tree["nodes"]:
        by_parent.setdefault(node["parent"], []).append(node)

    def walk(parent: str | None, depth: int) -> None:
        for node in by_parent.get(parent, []):
            lines.append(f"{'  ' * depth}- **{node['kind']}** `{node['id']}`：{node['text']}")
            walk(node["id"], depth + 1)

    walk(None, 0)
    lines.append("")
    return "\n".join(lines)


def _route_text(route: dict) -> str:
    if route["ambiguous"]:
        return "需求里的线索不足以唯一选定工具，需要和 Jane 确认主题后再选。"
    hits = "、".join(route["hits"].get(route["tool"], []))
    return f"选定 {route['tool']}。命中线索：{hits}。"
