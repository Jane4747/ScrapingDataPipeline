"""CLI integration for repeatable multi-source medical technology research."""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re

from pipeline.catalog import OUTPUTS, TREES, runtime_env
from .config import load_config
from .crawler import ResearchCrawler, now, write_json
from .export import export_results


def register(sub):
    parser = sub.add_parser("research", help="按来源配置采集智能医疗装备技术资料")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--source", action="append", default=[], help="平台 ID，可重复传入")
    parser.add_argument("--list-sources", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="显示采集范围，不联网或写文件")
    parser.add_argument("--run-id")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--max-pages", type=int, default=12, help="每个平台累计页面上限，含失败页面")
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument("--workers", type=int, default=3, help="同时采集的平台数；单平台串行")
    parser.add_argument("--timeout", type=float, default=25)
    parser.add_argument("--delay", type=float, default=1.0, help="同主机请求最小间隔（秒）")
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--max-bytes", type=int, default=12 * 1024 * 1024, help="单个响应体积上限，单位字节")
    parser.add_argument("--browser", action="store_true", help="对允许访问的 JS 空壳页面尝试浏览器渲染")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--reprocess", action="store_true", help="只重新解析和筛选已有原始文件，不联网；需 --resume")
    parser.add_argument("--retry-failed", action="store_true", help="恢复时重试失败页（仍遵守 robots）")
    parser.add_argument("--delivery", action="append", choices=("json", "markdown", "excel"))
    parser.set_defaults(func=run)


def run(args):
    config = load_config(args.config)
    sources = config["sources"]
    if args.source:
        unknown = set(args.source) - {source["id"] for source in sources}
        if unknown:
            raise ValueError("未知平台 ID：" + ", ".join(sorted(unknown)))
        sources = [source for source in sources if source["id"] in args.source]
    if args.list_sources:
        print(json.dumps([{key: source[key] for key in ("id", "name", "seeds")}
                          for source in sources], ensure_ascii=False, indent=2))
        return 0
    if (args.retry_failed or args.reprocess) and not args.resume:
        raise ValueError("--retry-failed / --reprocess 需要同时指定 --resume")
    if args.reprocess and args.retry_failed:
        raise ValueError("--reprocess 不联网，不能与 --retry-failed 同时使用")
    if args.resume and not (args.run_id or args.output_dir):
        raise ValueError("恢复采集需要 --run-id 或 --output-dir 指定原结果目录")
    if args.output_dir:
        output_dir = args.output_dir.resolve()
        run_id = args.run_id or output_dir.name
    else:
        run_id = args.run_id or datetime.now(timezone(timedelta(hours=8))).strftime("research-%Y%m%d-%H%M%S-%f")
        output_dir = OUTPUTS / run_id
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", run_id) or ".." in run_id:
        raise ValueError("run-id 只能包含字母、数字、横线、下划线和点，不可包含路径")
    deliveries = args.delivery or ["json", "markdown"]
    options = dict(output_dir=output_dir, max_pages=args.max_pages, max_depth=args.max_depth,
                   workers=args.workers, timeout=args.timeout, retries=args.retries,
                   delay=args.delay, browser=args.browser, resume=args.resume, retry_failed=args.retry_failed,
                   reprocess=args.reprocess, max_bytes=args.max_bytes)
    crawler = ResearchCrawler(**options)
    if args.dry_run:
        print(json.dumps({"topic": config["topic"], "source_count": len(sources), "sources": sources,
                          "options": {key: str(value) if isinstance(value, Path) else value for key, value in options.items()},
                          "deliveries": deliveries}, ensure_ascii=False, indent=2))
        return 0
    if (output_dir / "manifest.json").exists() and not args.resume:
        raise ValueError("输出目录已有结果，请使用 --resume 或新的 --run-id")
    snapshot = output_dir / "config.snapshot.json"
    if args.resume and snapshot.exists():
        saved = json.loads(snapshot.read_text(encoding="utf-8"))
        if {source["id"] for source in saved["sources"]} != {source["id"] for source in sources}:
            raise ValueError("恢复时平台集合必须与原任务一致；指定子集请使用新的运行目录")
        if saved["topic"] != config["topic"]:
            raise ValueError("恢复时主题必须与原任务一致")
    crawler.validate_sources(sources)
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", runtime_env()["PLAYWRIGHT_BROWSERS_PATH"])
    output_dir.mkdir(parents=True, exist_ok=True)
    lock = output_dir / "run.lock"
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError:
        raise ValueError(f"目录正在运行或有遗留锁，请核实进程后处理：{lock}")
    tree_path = TREES / run_id / "tree.json"
    state = {"id": run_id, "kind": "research", "status": "running", "started_at": now(),
             "theme": config["topic"], "delivery": deliveries,
             "sources": [source["id"] for source in sources],
             "output_dir": str(output_dir),
             "limits": {"max_pages_per_source": args.max_pages, "max_depth": args.max_depth},
             "nodes": [{"id": "need", "parent": None, "kind": "requirement", "at": now(),
                        "text": "按用户提供的平台采集智能医疗装备技术资料；不使用研究角色或主要价值描述。"}]}
    try:
        with handle:
            handle.write(json.dumps({"pid": os.getpid(), "started_at": now()}))
        write_json(tree_path, state)
        write_json(output_dir / "config.snapshot.json", {**config, "sources": sources})
        results = crawler.collect(sources)
        manifest = export_results(results, output_dir, config["topic"], deliveries)
        state.update(status=manifest["status"], finished_at=now(),
                     result={key: manifest[key] for key in ("source_count", "attempted_pages", "successful_pages", "failed_pages", "record_count")})
        write_json(tree_path, state)
        (tree_path.parent / "tree.md").write_text(
            f"# 采集记录 {run_id}\n\n- 主题：{config['topic']}\n- 状态：{state['status']}\n"
            f"- 来源数：{len(sources)}\n- 成功页面：{manifest['successful_pages']}\n"
            f"- 资料条数：{manifest['record_count']}\n- 输出目录：{output_dir}\n"
            f"- 范围：每个平台最多 {args.max_pages} 页、链接深度 {args.max_depth}。\n",
            encoding="utf-8")
        print(json.dumps({"run_id": run_id, "output_dir": str(output_dir), **state["result"],
                          "status": state["status"]}, ensure_ascii=False, indent=2))
        return 2 if manifest["status"] == "failed" else 0
    except BaseException as exc:
        state.update(status="failed", finished_at=now(), error=f"{type(exc).__name__}: {exc}")
        write_json(tree_path, state)
        raise
    finally:
        lock.unlink(missing_ok=True)
