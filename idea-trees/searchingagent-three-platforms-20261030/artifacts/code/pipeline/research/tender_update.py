"""Resumable three-source medical digital procurement update, orchestrated by Dagu.

Uses the existing collectors/parsers. No paid search, model, CAPTCHA solving or
automatic retry of access denials. The immutable request freezes the end date.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import csv
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import subprocess

from bs4 import BeautifulSoup
from pipeline.research import national_ggzy, zycg
from pipeline.research.fetch import Fetcher
from pipeline.research.tenders import decode_html
from pipeline.research.tender_fields import HEADERS, normalize, link_qualifications
from pipeline.research.beijing_ggzy import collect as collect_beijing_search

SOURCES = ("zycg", "ggzy_national", "ggzy_beijing")
REPO = Path(__file__).resolve().parents[2]
NAMES = {"zycg": "央采", "ggzy_national": "全国公共资源交易平台", "ggzy_beijing": "北京公共资源交易平台"}
BEIJING = "https://ggzyfw.beijing.gov.cn"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_scope(start, end, task_id, delay, pages, api_calls, details):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", task_id):
        raise ValueError("Invalid task ID")
    if date.fromisoformat(start) > date.fromisoformat(end) or date.fromisoformat(end) > date.today():
        raise ValueError("Invalid publication date range")
    if delay < 3 or min(pages, api_calls, details) < 1:
        raise ValueError("Minimum delay is 3 seconds; budgets must be positive")


@contextmanager
def source_lock(folder):
    path = folder / "source.lock"
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "started_at": now()}, handle)
    except FileExistsError:
        raise ValueError(f"Source lock exists; verify its process before recovery: {path}") from None
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def progress(folder, source, **fields):
    path = folder / "progress.json"
    value = read(path) if path.exists() else {}
    value.update(source=source, source_name=NAMES[source], updated_at=now(), **fields)
    write(path, value)
    print(json.dumps(value, ensure_ascii=False), flush=True)


def contract_files():
    return [Path(__file__), Path(zycg.__file__), Path(national_ggzy.__file__),
            REPO / "pipeline/research/fetch.py", REPO / "pipeline/research/bid_common.py",
            REPO / "pipeline/research/tender_fields.py", REPO / "pipeline/research/beijing_ggzy.py",
            REPO / "scripts/export_tender_workbook.mjs"]


def request_for(args):
    validate_scope(args.start, args.end, args.task_id, args.delay, args.max_pages, args.max_api_calls, args.max_details)
    return {"schema_version": 1, "task_id": args.task_id, "start": args.start, "end": args.end,
            "date_basis": "publication", "scope": "medical_digital_procurement", "sources": list(SOURCES), "fields": HEADERS,
            "allow_network": True, "delay": args.delay, "max_pages": args.max_pages,
            "max_api_calls": args.max_api_calls, "max_details": args.max_details,
            "node": args.node, "artifact_modules": args.artifact_modules,
            "code_sha256": {str(p.relative_to(REPO)): digest(p) for p in contract_files()}}


def verify(task_dir):
    request = read(task_dir / "request.json")
    revision_path = task_dir / "code-revisions" / "current.json"
    revision = read(revision_path) if revision_path.exists() else None
    if revision and revision.get("original_request_sha256") != digest(task_dir / "request.json"):
        raise ValueError("Code revision does not match the immutable original request")
    expected_hashes = revision["code_sha256"] if revision else request["code_sha256"]
    for filename, expected in expected_hashes.items():
        if digest(REPO / filename) != expected:
            raise ValueError(f"Code changed since task creation; create a new task: {filename}")
    if request.get("allow_network") is not True or request["sources"] != list(SOURCES):
        raise ValueError("Unexpected task contract")
    if revision:
        print(json.dumps({"code_revision": revision["revision"], "reason": revision["reason"]}, ensure_ascii=False), flush=True)
    return request


def generate_dag(task_dir, dag_dir, python):
    request = read(task_dir / "request.json")
    dag_name = "medical-tender-" + request["task_id"]
    scalar = lambda x: json.dumps(str(x), ensure_ascii=False)
    # Parameters never enter a shell command: the task path is an environment variable.
    executable = "'" + str(python).replace("'", "''") + "'"
    lines = [f"description: {scalar('医疗数字化采购：' + request['start'] + ' 至 ' + request['end'])}",
             "type: graph", "queue: medical-tender-updates", "max_active_steps: 3",
             "working_dir: " + scalar(REPO), "env:", "  PYTHONUTF8: '1'", "  PYTHONDONTWRITEBYTECODE: '1'",
             "  TENDER_UPDATE_TASK_DIR: " + scalar(task_dir), "steps:"]
    steps = [("verify", "校验范围与代码版本", "verify", [])]
    steps += [(source, NAMES[source] + "（2024年至今）", "run-source --source " + source, ["verify"]) for source in SOURCES]
    steps += [("summary", "汇总数据与覆盖缺口", "summarize", list(SOURCES)),
              ("export", "生成完整字段表格", "export", ["summary"])]
    for sid, name, command, dependencies in steps:
        lines += ["  - id: " + sid, "    name: " + scalar(name)]
        if dependencies:
            lines += ["    depends: " + json.dumps(dependencies)]
        lines += ["    run: |", f"      & {executable} -u -B -m pipeline.research.tender_update {command}",
                  "      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }", "    with:", "      shell: powershell"]
        if sid in SOURCES or sid == "summary":
            lines += ["    continue_on:", "      failure: true", "      mark_success: false"]
    # Always retain an honest summary if cancelled or if a prerequisite failed.
    lines += ["handler_on:", "  exit:", "    run: |",
              f"      & {executable} -u -B -m pipeline.research.tender_update summarize --snapshot",
              "    with:", "      shell: powershell"]
    path = Path(dag_dir) / (dag_name + ".yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def plan(args):
    request = request_for(args)
    task_dir = Path(args.output).resolve() / args.task_id
    if args.dry_run:
        print(json.dumps({"status": "validated", "task_dir": str(task_dir), "request": request}, ensure_ascii=False))
        return 0
    if (task_dir / "request.json").exists():
        existing = read(task_dir / "request.json")
        business_scope = lambda value: {k:v for k,v in value.items() if k != "code_sha256"}
        if not args.resume or business_scope(existing) != business_scope(request):
            raise ValueError("Existing task differs or --resume is missing; use a new task ID")
        verify(task_dir)
    else:
        if task_dir.exists() and any(task_dir.iterdir()):
            raise ValueError("Task output is not empty")
        task_dir.mkdir(parents=True, exist_ok=True)
        write(task_dir / "request.json", request)
        for source in SOURCES:
            folder = task_dir / source
            folder.mkdir(exist_ok=True)
            progress(folder, source, status="queued", start=args.start, end=args.end, records=0)
    dag = generate_dag(task_dir, args.dag_dir, args.python)
    print(json.dumps({"status": "planned", "task_dir": str(task_dir), "dag_name": dag.stem, "dag_file": str(dag)}, ensure_ascii=False))
    return 0


def seed_zycg_cache(folder, first, last):
    """Only historical, exact month lists; current-month lists always stay fresh."""
    cache = folder / "cache"
    cache.mkdir(exist_ok=True)
    tag = f"page-{first}_{last}-"
    imported = []
    if last >= date.today().replace(day=1).isoformat():
        return
    for prior in (REPO / "outputs/zycg-2026-medical").glob("*/cache"):
        for path in prior.glob(tag + "*.html"):
            target = cache / path.name
            if not target.exists() and zycg.parse_search_page(decode_html(path.read_bytes())):
                shutil.copy2(path, target)
                imported.append({"source": str(path), "target": str(target), "sha256": digest(path)})
    if imported:
        write(folder / "cache-provenance.json", imported)


def collect_zycg(request, folder):
    rows, windows = [], zycg.month_windows(request["start"], request["end"])
    completed, failed = 0, False
    for first, last in windows:
        month = folder / (first + "_" + last)
        month.mkdir(exist_ok=True)
        seed_zycg_cache(month, first, last)
        result_file = month / "zycg_medical_bid.json"
        previous = read(result_file) if result_file.exists() else {}
        if previous.get("status") != "completed":
            def update(message):
                progress(folder, "zycg", status="running", current_window=[first, last],
                         completed_months=completed, total_months=len(windows), message=message)
            zycg.collect(first, last, month, request["max_pages"], 30, request["delay"],
                         split_monthly=False, progress=update, include_all=True)
        payload = read(result_file)
        for record in payload["records"]:
            detail = record.get("detail", {})
            published = detail.get("公告日期", "")[:10]
            if request["start"] <= published <= request["end"]:
                rows.append({**detail, **record.get("row", {}), "公告日期": published, "相关网页": detail.get("公告链接", ""),
                             "公告类型": detail.get("公告类型", ""), "来源": "央采（中国政府采购网代理机构精确检索）",
                             "原文文件": str(month / "cache" / ("detail-" + hashlib.md5(detail.get("公告链接", "").encode()).hexdigest()[:12] + ".html"))})
        write(folder / "records.json", rows)
        if payload.get("status") != "completed":
            failed = True
            progress(folder, "zycg", status="partial", records=len(rows), completed_months=completed,
                     total_months=len(windows), failures=payload.get("failures", []),
                     current_window=[first, last], message="窗口未完整完成；保留缓存，停止后续月份")
            break
        completed += 1
        progress(folder, "zycg", status="running", records=len(rows), completed_months=completed, total_months=len(windows))
    status = "partial" if failed or completed != len(windows) else "completed"
    progress(folder, "zycg", status=status, records=len(rows), completed_months=completed, total_months=len(windows))
    return 0 if status == "completed" else 3


def seed_national_cache(request, folder):
    destination = folder / "lists"
    destination.mkdir(exist_ok=True)
    manifest = folder / "cache-provenance.json"
    if manifest.exists():
        return
    imported = []
    base = REPO / "outputs/national-ggzy-medical-digital-2026-20261028"
    for collection in ("collection", "collection-v2"):
        for path in (base / collection / "lists").glob("*.json"):
            try:
                payload = read(path)
                form = payload.get("form", {})
                if payload.get("response", {}).get("code") != 200 or not (request["start"] <= form.get("TIMEBEGIN", "") <= form.get("TIMEEND", "") <= request["end"]):
                    continue
                # An unfinished current month may acquire new records; never seed it.
                if form["TIMEEND"] >= date.today().replace(day=1).isoformat():
                    continue
                key = hashlib.sha256(json.dumps(form, sort_keys=True).encode()).hexdigest()[:20]
                target = destination / (key + ".json")
                if not target.exists():
                    shutil.copy2(path, target)
                    imported.append({"source": str(path), "target": str(target), "sha256": digest(path)})
            except (ValueError, KeyError):
                continue
    write(manifest, imported)


def collect_national(request, folder):
    seed_national_cache(request, folder)
    args = ["--start", request["start"], "--end", request["end"], "--output", str(folder),
            "--delay", str(request["delay"]), "--max-api-calls", str(request["max_api_calls"]),
            "--max-details", str(request["max_details"])]
    if (folder / "state.json").exists():
        args.append("--resume")
    code = national_ggzy.main(args)
    state = read(folder / "state.json")
    write(folder / "records.json", [{**row, "来源": NAMES["ggzy_national"]} for row in state.get("records", {}).values()])
    return code


def parse_beijing_list(html):
    soup = BeautifulSoup(html, "html.parser")
    result = []
    for li in soup.select("li"):
        a = li.find("a", href=True)
        if not a or not re.search(r"/20\d{6}/\d+\.html$", a["href"]):
            continue
        stamp = li.find(class_="list-times1")
        published = stamp.get_text(" ", strip=True) if stamp else ""
        match = re.search(r"20\d{2}-\d{2}-\d{2}", published)
        if not match:
            continue
        from urllib.parse import urljoin
        result.append({"title": (a.get("title") or a.get_text(" ", strip=True)).strip(),
                       "publishTime": match.group(), "url": urljoin(BEIJING, a["href"]),
                       "informationType": "0202", "informationTypeText": "中标成交公告", "provinceText": "北京"})
    return result


def collect_beijing(request, folder):
    state_file = folder / "state.json"
    state = read(state_file) if state_file.exists() else {"page": 1, "records": {}, "failures": [], "pages": {}, "listing_complete": False}
    fetcher = Fetcher(timeout=30, retries=0, delay=request["delay"], transport="auto")
    (folder / "raw").mkdir(exist_ok=True)
    try:
        while not state["listing_complete"] and state["page"] <= request["max_pages"]:
            page = state["page"]
            suffix = "index.html" if page == 1 else f"index_{page}.html"
            url = BEIJING + "/jyxxzbjggg/" + suffix
            raw_file = folder / "raw" / suffix
            result = {"status": "ok", "raw": raw_file.read_bytes()} if raw_file.exists() else fetcher.fetch(url, ["ggzyfw.beijing.gov.cn"])
            if result["status"] != "ok":
                state["failures"].append({k: v for k, v in result.items() if k not in ("raw", "text", "links")})
                break
            raw = result["raw"]
            raw_file.write_bytes(raw)
            items = parse_beijing_list(decode_html(raw))
            if not items:
                state["failures"].append({"url": url, "status": "unexpected_response", "error": "未取得有效列表；不能将空壳/挑战页视为已覆盖历史"})
                break
            body_hash = hashlib.sha256(raw).hexdigest()
            if str(page) not in state["pages"] and body_hash in state["pages"].values():
                state["failures"].append({"url": url, "status": "repeated_page"})
                break
            state["pages"][str(page)] = body_hash
            stop = False
            for notice in items:
                if not request["start"] <= notice["publishTime"] <= request["end"] or not national_ggzy.in_scope(notice["title"]):
                    continue
                key = hashlib.sha256(notice["url"].encode()).hexdigest()[:20]
                if key in state["records"]:
                    continue
                detail_path = folder / "raw" / (key + ".html")
                detail = {"status": "ok", "raw": detail_path.read_bytes()} if detail_path.exists() else fetcher.fetch(notice["url"], ["ggzyfw.beijing.gov.cn"])
                if detail["status"] != "ok":
                    state["failures"].append({"url": notice["url"], "status": detail["status"], "error": detail.get("error", "")})
                    stop = True
                    break
                detail_path.write_bytes(detail["raw"])
                row = national_ggzy.parse_article(decode_html(detail["raw"]), notice)
                row.pop("_text", None)
                row.update(来源=NAMES["ggzy_beijing"], 原文文件=str(detail_path), 日期依据="官方列表发布日期，待正文交叉核实")
                state["records"][key] = row
            if stop:
                break
            if max(n["publishTime"] for n in items) < request["start"]:
                state["listing_complete"] = True
            else:
                state["page"] += 1
            write(state_file, state)
            progress(folder, "ggzy_beijing", status="running", list_pages=len(state["pages"]), records=len(state["records"]), current_page=page)
    finally:
        fetcher.close()
        write(state_file, state)
        write(folder / "records.json", list(state["records"].values()))
    status = "completed" if state["listing_complete"] and not state["failures"] else "partial"
    progress(folder, "ggzy_beijing", status=status, records=len(state["records"]), list_pages=len(state["pages"]),
             failures=state["failures"], message="已到日期边界" if status == "completed" else "访问受限、历史入口缺口或达到页数预算；未声称已完整更新")
    return 0 if status == "completed" else 3


def run_source(task_dir, source):
    request = verify(task_dir)
    folder = task_dir / source
    folder.mkdir(exist_ok=True)
    with source_lock(folder):
        attempts = folder / "attempts"
        attempts.mkdir(exist_ok=True)
        attempt = attempts / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(os.getpid()))
        attempt.mkdir()
        started = now()
        write(attempt / "code-version.json", {"started_at": started, "code_sha256": {str(p.relative_to(REPO)): digest(p) for p in contract_files()}})
        progress(folder, source, status="running", started_at=started, message="开始执行；保留实际覆盖缺口")
        try:
            function = {"zycg": collect_zycg, "ggzy_national": collect_national,
                        "ggzy_beijing": lambda r, f: collect_beijing_search(r, f, lambda **kw: progress(f, source, **kw))}[source]
            code = function(request, folder)
        except Exception as exc:
            progress(folder, source, status="failed", error=f"{type(exc).__name__}: {exc}")
            code = 2
        current = read(folder / "progress.json")
        write(attempt / "receipt.json", {"source": source, "started_at": started, "finished_at": now(),
                                          "exit_code": code, "request_sha256": digest(task_dir / "request.json"),
                                          "progress": current})
        summarize(task_dir, snapshot=True)
        return code


def summarize(task_dir, snapshot=False):
    request = read(task_dir / "request.json")
    source_rows, records, seen = [], [], set()
    for source in SOURCES:
        folder = task_dir / source
        info = read(folder / "progress.json") if (folder / "progress.json").exists() else {"status": "not_started"}
        source_rows.append({"source": source, "source_name": NAMES[source], **info})
        row_file = folder / "records.json"
        if source == "ggzy_national" and (folder / "state.json").exists():
            values = read(folder / "state.json").get("records", {}).values()
            rows = [{**r, "来源": NAMES[source]} for r in values]
        else:
            rows = read(row_file) if row_file.exists() else []
        accepted = 0
        for row in rows:
            published = str(row.get("公告日期", ""))[:10]
            if not request["start"] <= published <= request["end"]:
                continue
            # Keep source attribution; identical project names are never auto-merged.
            identity = (source, row.get("相关网页", ""), row.get("项目编号", ""), row.get("项目名称", ""))
            if identity not in seen:
                seen.add(identity)
                records.append(normalize(row, NAMES[source]))
                accepted += 1
        source_rows[-1]["records"] = accepted
    statuses = [s["status"] for s in source_rows]
    status = "completed" if all(s == "completed" for s in statuses) else "running" if any(s in ("running", "queued") for s in statuses) else "partial"
    link_qualifications(records)
    summary = {"task_id": request["task_id"], "status": status, "generated_at": now(),
               "start": request["start"], "end": request["end"], "date_basis": "publication",
               "records": len(records), "sources": source_rows, "facts_verified": False,
               "note": "按来源保留公告；同名项目不自动归并。未知日期不计入本期，执行完成不等于全国无遗漏或事实已核验。"}
    # Source workers may snapshot concurrently: write one independent view per PID.
    target = task_dir / ("snapshot-" + str(os.getpid()) + ".json") if snapshot else task_dir / "summary.json"
    write(target, summary)
    if not snapshot:
        export = task_dir / "delivery"
        export.mkdir(exist_ok=True)
        write(export / "records.json", records)
        headers = HEADERS
        with (export / "公告明细.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
        lines = ["# 三平台医疗数字化采购更新", "", f"发布日期范围：{request['start']} 至 {request['end']}。", "",
                 f"总体状态：{status}；保留来源的公告记录 {len(records)} 条。", "",
                 "| 来源 | 执行状态 | 记录数 |", "| --- | --- | ---: |"]
        lines += [f"| {r['source_name']} | {r['status']} | {r.get('records', 0)} |" for r in source_rows]
        lines += ["", summary["note"], "", "失败原因及未完成窗口见各来源 progress.json/state.json。"]
        (export / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if snapshot or status == "completed" else 3


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--task-id", required=True)
    p.add_argument("--start", default="2024-01-01")
    p.add_argument("--end", default=date.today().isoformat())
    p.add_argument("--output", default=str(REPO / "outputs/tender-updates"))
    p.add_argument("--dag-dir", required=True)
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--node", required=True)
    p.add_argument("--artifact-modules", required=True)
    p.add_argument("--delay", type=float, default=3.5)
    p.add_argument("--max-pages", type=int, default=100)
    p.add_argument("--max-api-calls", type=int, default=6000)
    p.add_argument("--max-details", type=int, default=10000)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--resume", action="store_true")
    sub.add_parser("verify")
    sub.add_parser("export")
    p = sub.add_parser("run-source")
    p.add_argument("--source", choices=SOURCES, required=True)
    p = sub.add_parser("summarize")
    p.add_argument("--snapshot", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            return plan(args)
        task_dir = Path(os.environ["TENDER_UPDATE_TASK_DIR"]).resolve()
        if args.command == "verify":
            value = verify(task_dir)
            print(json.dumps({"status": "validated", "task_id": value["task_id"], "start": value["start"], "end": value["end"]}))
            return 0
        if args.command == "export":
            request = read(task_dir / "request.json")
            return subprocess.call([request["node"], str(REPO / "scripts/export_tender_workbook.mjs"),
                                    str(task_dir), request["artifact_modules"]])
        if args.command == "run-source":
            return run_source(task_dir, args.source)
        return summarize(task_dir, args.snapshot)
    except (KeyError, ValueError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
