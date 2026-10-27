import csv
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

from pipeline.catalog import OUTPUTS, PYTHON, TOOLS, runtime_env


class RunError(RuntimeError):
    pass


def run_task(tree: dict, args) -> dict:
    tool = tree["tool"]
    if tool not in TOOLS:
        raise RunError("还没有选定工具。")
    out_dir = OUTPUTS / tree["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    runners = {
        "goverment_spider": _run_goverment,
        "NewsCrawler": _run_newscrawler,
        "crawl4ai": _run_crawl4ai,
        "feapder": _run_feapder,
        "news-please": _run_news_please,
    }
    result = runners[tool](tree, args, out_dir)
    result["output_dir"] = str(out_dir)
    return result


def _python_cmd() -> str:
    if not PYTHON.exists():
        raise RunError(f"找不到 Python 解释器：{PYTHON}")
    return str(PYTHON)


def _run_goverment(tree: dict, args, out_dir: Path) -> dict:
    repo = TOOLS["goverment_spider"]["path"]
    before = _excel_snapshot(repo)
    before_text = _file_snapshot(repo / "files", "*.txt") if args.site else {}
    if args.site:
        script = _find_site(repo, args.site)
        command = [_python_cmd(), str(script)]
        if args.start_date:
            command.extend(["--start_date", args.start_date])
    else:
        if not args.all_sites:
            raise RunError("政府爬虫需要 --site 指定一个站点脚本名，或显式加上 --all-sites。")
        command = [_python_cmd(), str(repo / "start_project.py")]
        if args.start_date:
            command.extend(["--start_date", args.start_date])
            if args.only_start_date:
                command.append("--only_start_date")
    _subprocess(command, repo, **_timeout_options(args))
    changed = _changed_excel(repo, before)
    # Upstream site scripts write TSV-like text; only the all-site entry builds XLSX.
    # Convert changed text directly so unrelated historical site results stay excluded.
    if args.site and not changed:
        result = _government_text_result(repo, before_text, args, out_dir)
        result["command"] = command
        return result
    exported = _export_latest_excel(repo, out_dir, args.delivery, before=before)
    return {
        "command": command, "files": exported,
        "status": "completed" if exported else "failed",
        "success_count": len(changed) if exported else 0,
        "failure_count": 0 if exported else 1,
        "count": len(changed) if exported else 0,
        "count_unit": "workbooks",
        "note": "已导出本次生成或更新的工作簿。" if exported else "脚本已退出，但没有发现本次生成或更新的 Excel，未交付历史文件。",
    }


def _government_text_result(repo: Path, before: dict, args, out_dir: Path) -> dict:
    current = _file_snapshot(repo / "files", "*.txt")
    changed = sorted(path for path, signature in current.items() if before.get(path) != signature)
    rows = []
    invalid = 0
    columns = ["部门名称", "类型", "标题", "日期", "链接"]
    for path in changed:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for values in csv.reader(stream, delimiter="\t"):
                if not values or not any(value.strip() for value in values):
                    continue
                if len(values) != len(columns):
                    invalid += 1
                    continue
                if getattr(args, "only_start_date", False) and args.start_date and values[3] != args.start_date:
                    continue
                row = dict(zip(columns, values))
                row["来源文件"] = str(path.relative_to(repo / "files"))
                rows.append(row)
    files = [str(_write_delivery(rows, args.delivery, out_dir))] if rows else []
    return {
        "files": files, "status": "partial" if rows and invalid else "completed" if rows else "failed",
        "success_count": len(rows), "failure_count": invalid if rows else max(1, invalid),
        "count": len(rows), "count_unit": "records", "source_files": [str(path) for path in changed],
        "note": "已将本次生成或更新的站点文本导出；历史未更新文件已排除。" if rows else "没有本次有效新增或更新的站点数据，未交付历史文件。",
    }


def _find_site(repo: Path, site: str) -> Path:
    codes = repo / "codes"
    matches = [path for path in codes.glob("*.py") if site in path.name]
    if len(matches) == 1:
        return matches[0]
    if len(matches) == 0:
        raise RunError(f"codes/ 里没有包含「{site}」的脚本。")
    names = "、".join(path.name for path in matches[:8])
    raise RunError(f"「{site}」匹配到多个脚本：{names}")


def _run_newscrawler(tree: dict, args, out_dir: Path) -> dict:
    urls = _require_urls(args)
    code = r"""
import json, sys
sys.path.insert(0, r"%s")
from news_extractor_core.services import ExtractorService
urls = json.loads(sys.argv[1])
rows = []
for url in urls:
    item, platform = ExtractorService.extract_news(url)
    row = item.model_dump() if hasattr(item, "model_dump") else item.to_dict()
    row["platform"] = platform
    rows.append(row)
print(json.dumps(rows, ensure_ascii=False))
""" % str(TOOLS["NewsCrawler"]["path"]).replace("\\", "\\\\")
    raw = _python_stdin(code, json.dumps(urls, ensure_ascii=False), **_timeout_options(args))
    rows = json.loads(raw)
    path = _write_delivery(rows, args.delivery, out_dir)
    return _rows_result(rows, path)


def _run_crawl4ai(tree: dict, args, out_dir: Path) -> dict:
    urls = _require_urls(args)
    schema = None
    if args.schema:
        schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    code = r"""
import asyncio, json, sys
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
urls = json.loads(sys.argv[1])
schema = json.loads(sys.argv[2]) if sys.argv[2] != "-" else None

async def main():
    strategy = None
    if schema is not None:
        from crawl4ai import JsonCssExtractionStrategy
        strategy = JsonCssExtractionStrategy(schema)
    rows = []
    async with AsyncWebCrawler() as crawler:
        for url in urls:
            config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, extraction_strategy=strategy)
            try:
                result = await crawler.arun(url=url, config=config)
                rows.append({
                    "url": url,
                    "success": result.success,
                    "markdown": result.markdown if isinstance(result.markdown, str) else str(result.markdown),
                    "extracted": result.extracted_content,
                    "error": result.error_message,
                })
            except Exception as exc:
                rows.append({"url": url, "success": False, "error": str(exc)})
    print(json.dumps(rows, ensure_ascii=False))

asyncio.run(main())
"""
    raw = _python_stdin(code, json.dumps(urls, ensure_ascii=False), json.dumps(schema, ensure_ascii=False) if schema else "-", **_timeout_options(args))
    rows = json.loads(raw)
    path = _write_delivery(rows, args.delivery, out_dir)
    return _rows_result(rows, path)


def _run_news_please(tree: dict, args, out_dir: Path) -> dict:
    urls = _require_urls(args)
    code = r"""
import json, sys
from newsplease import NewsPlease
urls = json.loads(sys.argv[1])
articles = NewsPlease.from_urls(urls)
rows = []
for url in urls:
    article = articles.get(url)
    if article is None:
        rows.append({"url": url, "error": "extract failed"})
        continue
    row = article.get_serializable_dict()
    row["url"] = url
    rows.append(row)
print(json.dumps(rows, ensure_ascii=False, default=str))
"""
    raw = _python_stdin(code, json.dumps(urls, ensure_ascii=False), **_timeout_options(args))
    rows = json.loads(raw)
    path = _write_delivery(rows, args.delivery, out_dir)
    return _rows_result(rows, path)


def _run_feapder(tree: dict, args, out_dir: Path) -> dict:
    if not args.spider:
        raise RunError("feapder 需要 --spider 指向已经写好的爬虫脚本。")
    spider = Path(args.spider)
    if not spider.exists():
        raise RunError(f"找不到爬虫脚本：{spider}")
    command = [_python_cmd(), str(spider)]
    _subprocess(command, spider.parent, **_timeout_options(args))
    return {
        "command": command, "status": "partial", "files": [],
        "success_count": 0, "failure_count": 0, "external_output": True,
        "note": "已执行指定爬虫脚本。输出由该脚本管理，本工具尚未验证交付文件，不能认定采集完成。",
    }


def _require_urls(args) -> list[str]:
    urls = [item.strip() for item in (args.url or []) if item.strip()]
    if not urls:
        raise RunError("这个工具需要至少一条 --url。")
    return urls


def _timeout_options(args) -> dict:
    value = getattr(args, "process_timeout", None)
    return {"timeout": value} if value is not None else {}


def _process_timeout(value=None) -> float:
    try:
        seconds = float(value if value is not None else os.environ.get("SCRAPING_PROCESS_TIMEOUT", "600"))
    except (TypeError, ValueError) as exc:
        raise RunError("子进程超时必须是正数秒数。") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise RunError("子进程超时必须是有限的正数秒数。")
    return seconds


def _subprocess(command: list[str], cwd: Path, timeout=None) -> None:
    seconds = _process_timeout(timeout)
    try:
        completed = subprocess.run(command, cwd=str(cwd), text=True, env=runtime_env(), timeout=seconds, stdout=sys.stderr)
    except subprocess.TimeoutExpired as exc:
        raise RunError(f"子进程超过 {seconds:g} 秒，已停止等待。可用 --process-timeout 调整。") from exc
    if completed.returncode != 0:
        raise RunError(f"命令退出码 {completed.returncode}：{' '.join(command)}")


def _python_stdin(code: str, *argv: str, timeout=None) -> str:
    seconds = _process_timeout(timeout)
    try:
        completed = subprocess.run(
            [_python_cmd(), "-B", "-X", "utf8", "-c", code, *argv],
            text=True,
            capture_output=True,
            encoding="utf-8",
            env=runtime_env(),
            timeout=seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RunError(f"子进程超过 {seconds:g} 秒，已停止等待。可用 --process-timeout 调整。") from exc
    if completed.returncode != 0:
        raise RunError(completed.stderr.strip() or completed.stdout.strip() or "Python 子进程失败")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RunError("子进程没有返回 JSON。")
    return lines[-1]


def _write_delivery(rows: list, delivery: str, out_dir: Path) -> Path:
    if delivery == "json":
        path = out_dir / "result.json"
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
    if delivery == "markdown":
        path = out_dir / "result.md"
        parts = ["# 采集结果", ""]
        for index, row in enumerate(rows, start=1):
            parts.append(f"## {index}")
            parts.append("")
            parts.append("```json")
            parts.append(json.dumps(row, ensure_ascii=False, indent=2))
            parts.append("```")
            parts.append("")
        path.write_text("\n".join(parts), encoding="utf-8")
        return path
    if delivery != "excel":
        raise RunError(f"不支持的交付格式：{delivery}")
    pd = _pandas()
    frame = pd.json_normalize(rows)
    path = out_dir / "result.xlsx"
    frame.to_excel(path, index=False)
    return path


def _pandas():
    try:
        import pandas
    except ImportError as exc:
        raise RunError("此项 Excel 操作需要完整依赖。请运行 scripts/install.ps1 -Profile full。") from exc
    return pandas


def _rows_result(rows: list, path: Path) -> dict:
    successes = sum(1 for row in rows if row.get("success", True) and not row.get("error"))
    failures = len(rows) - successes
    exported = path.is_file()
    status = "completed" if successes and not failures and exported else "partial" if successes and exported else "failed"
    return {"files": [str(path)] if exported else [], "count": len(rows), "status": status,
            "success_count": successes, "failure_count": failures}


def _excel_snapshot(repo: Path) -> dict:
    return _file_snapshot(repo / "xls_files", "*.xlsx")


def _file_snapshot(folder: Path, pattern: str) -> dict:
    snapshot = {}
    for path in folder.rglob(pattern):
        if path.is_file() and not path.name.startswith("~$"):
            stat = path.stat()
            snapshot[path] = (stat.st_mtime_ns, stat.st_size, hashlib.sha256(path.read_bytes()).hexdigest())
    return snapshot


def _changed_excel(repo: Path, before: dict) -> list[Path]:
    return sorted(path for path, signature in _excel_snapshot(repo).items() if before.get(path) != signature)


def _export_latest_excel(repo: Path, out_dir: Path, delivery: str, before=None) -> list[str]:
    """Keep the legacy helper name; export all workbooks changed during this run."""
    if before is None:
        return []  # Without a pre-run snapshot no workbook can be attributed to this run.
    files = _changed_excel(repo, before)
    if not files:
        return []
    written = []
    if delivery == "excel":
        for source in files:
            target = out_dir / source.relative_to(repo / "xls_files")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            written.append(str(target))
        return written
    if delivery not in {"json", "markdown"}:
        raise RunError(f"不支持的交付格式：{delivery}")
    pd = _pandas()
    combined = []
    for source in files:
        frame = pd.read_excel(source, sheet_name=None)
        for sheet, table in frame.items():
            table = table.copy()
            table.insert(0, "来源工作表", sheet, allow_duplicates=True)
            table.insert(0, "来源工作簿", str(source.relative_to(repo / "xls_files")), allow_duplicates=True)
            combined.append(table)
    merged = pd.concat(combined, ignore_index=True) if combined else pd.DataFrame()
    if delivery == "json":
        path = out_dir / "result.json"
        path.write_text(merged.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")
    else:
        path = out_dir / "result.md"
        path.write_text(merged.to_markdown(index=False), encoding="utf-8")
    written.append(str(path))
    return written
