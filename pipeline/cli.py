import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from pipeline.catalog import PYTHON, TOOLS, runtime_env
from pipeline.idea_tree import add_node, create_tree, load_tree, save_tree
from pipeline.router import choose_tool
from pipeline.runner import RunError, run_task


class CommandParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        return _main(argv)
    except (RunError, ValueError, OSError, ImportError) as exc:
        if "--json" in argv:
            print(json.dumps({"schema_version": 1, "status": "failed", "error_type": type(exc).__name__,
                              "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"执行失败：{exc}", file=sys.stderr)
        return 2


def _main(argv) -> int:
    parser = CommandParser(description="本地公开资料调研：任务、来源发现、采集、证据与交付")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="检查 BigData 环境能否导入各仓库")
    check.add_argument("--profile", choices=("research", "full"), default="research")
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=cmd_check)

    plan = sub.add_parser("plan", help="根据需求生成想法树，不运行采集")
    plan.add_argument("--requirement", required=True)
    plan.set_defaults(func=cmd_plan)

    run = sub.add_parser("run", help="Jane 确认主题和交付格式后运行")
    run.add_argument("--tree-id", required=True)
    run.add_argument("--theme", required=True)
    run.add_argument("--delivery", required=True, choices=["json", "excel", "markdown"])
    run.add_argument("--url", action="append", default=[])
    run.add_argument("--site")
    run.add_argument("--spider")
    run.add_argument("--schema")
    run.add_argument("--start-date")
    run.add_argument("--only-start-date", action="store_true")
    run.add_argument("--all-sites", action="store_true")
    run.add_argument("--process-timeout", type=float, help="旧采集器子进程超时秒数，默认600")
    run.add_argument("--json", action="store_true", help="机器读取结果；采集器日志写入stderr")
    run.set_defaults(func=cmd_run)

    # Help and environment checks must work before optional dependencies are installed.
    modules = {"research": ("cli", "按来源采集医疗技术资料"),
               "discover": ("discovery", "生成搜索计划、导入候选或调用可选搜索API"),
               "evidence": ("deployments", "从已有原文提取待核验部署线索")}
    for name, (module, help_text) in modules.items():
        if argv and argv[0] == name:
            from importlib import import_module
            import_module("pipeline.research." + module).register(sub)
        else:
            sub.add_parser(name, help=help_text)
    from pipeline.task_runner import register as register_tasks
    register_tasks(sub)
    review = sub.add_parser("review", help="从线索创建待核验队列或导入项目核验记录")
    review.add_argument("--input-dir", type=Path, required=True)
    review.add_argument("--output-dir", type=Path, required=True)
    review.add_argument("--decisions", type=Path)
    review.add_argument("--json", action="store_true")
    review.set_defaults(func=cmd_review)
    args = parser.parse_args(argv)
    return args.func(args)


def cmd_check(args) -> int:
    full = getattr(args, "profile", "research") == "full"
    probes = {"requests": "import requests", "beautifulsoup4": "import bs4", "pypdf": "import pypdf"}
    if full:
        probes.update({
        "pandas": "import pandas",
        "feapder": "import feapder",
        "newsplease": "from newsplease import NewsPlease",
        "crawl4ai": "import crawl4ai",
        "news_extractor_core": "import news_extractor_core",
        "xlsxwriter": "import xlsxwriter",
        "openpyxl": "import openpyxl",
        })
    checks = [{"name": "python", "ok": PYTHON.is_file(), "path": str(PYTHON)}]
    failed = 0
    for name, statement in probes.items():
        env = runtime_env()
        if name == "news_extractor_core":
            repo = str(TOOLS["NewsCrawler"]["path"])
            env["PYTHONPATH"] = repo + os.pathsep + env.get("PYTHONPATH", "")
        try:
            completed = subprocess.run([str(PYTHON), "-B", "-X", "utf8", "-c", statement],
                                       text=True, capture_output=True, encoding="utf-8", errors="replace", env=env, timeout=45)
            detail = (completed.stderr or completed.stdout).strip().splitlines()
            checks.append({"name": name, "ok": completed.returncode == 0,
                           "detail": "" if completed.returncode == 0 else detail[-1] if detail else "import failed"})
        except (OSError, subprocess.TimeoutExpired) as exc:
            checks.append({"name": name, "ok": False, "detail": str(exc)})
    if full:
        for name, spec in TOOLS.items():
            checks.append({"name": "repo:" + name, "ok": spec["path"].is_dir(), "path": str(spec["path"])})
    failed = sum(not item["ok"] for item in checks)
    result = {"schema_version": 1, "profile": "full" if full else "research",
              "status": "failed" if failed else "completed", "failed_checks": failed, "checks": checks,
              "note": "仅检查本地导入和目录；不代表真实网站、浏览器渲染或搜索API已验证。"}
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for item in checks:
            print(f"{'OK' if item['ok'] else 'FAIL'} {item['name']} {item.get('detail', item.get('path', ''))}")
    return 2 if failed else 0


def cmd_review(args):
    from pipeline.review import build_review
    summary = build_review(args.input_dir, args.output_dir, args.decisions)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cmd_plan(args) -> int:
    route = choose_tool(args.requirement)
    tree = create_tree(args.requirement, route)
    print(json.dumps({
        "tree_id": tree["id"],
        "status": tree["status"],
        "tool": tree["tool"],
        "ambiguous": route["ambiguous"],
        "path": str(Path("idea-trees") / tree["id"]),
        "ask_jane": ["主题", "交付格式（json、excel 或 markdown）"],
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_run(args) -> int:
    tree = load_tree(args.tree_id)
    if tree.get("route", {}).get("ambiguous") and not tree.get("tool"):
        raise RunError("工具还没选定。先和 Jane 确认主题，再用明确需求重新 plan。")
    tree["theme"] = args.theme
    tree["delivery"] = args.delivery
    tree["status"] = "running"
    add_node(tree, "theme", "route", "decision", f"主题确认为：{args.theme}")
    add_node(tree, "delivery", "theme", "decision", f"交付格式确认为：{args.delivery}")
    save_tree(tree)
    try:
        result = run_task(tree, args)
    except Exception as exc:
        tree["status"] = "failed"
        add_node(tree, "failure", "delivery", "error", str(exc), error_type=type(exc).__name__)
        save_tree(tree)
        raise
    tree["status"] = result.get("status", "partial")
    if tree["status"] not in {"completed", "partial", "failed"}:
        tree["status"] = "failed"
    add_node(tree, "run", "delivery", "action", "采集器已返回，成功与失败以结果统计为准。", result=result)
    save_tree(tree)
    print(json.dumps({"tree_id": tree["id"], "status": tree["status"], "result": result}, ensure_ascii=False, indent=2))
    return {"completed": 0, "partial": 3, "failed": 2}[tree["status"]]
