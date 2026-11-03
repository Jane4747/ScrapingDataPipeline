"""Province-by-province medical digital procurement update (batch 1 and batch 2).

Each region is collected through the national platform's documented province /
city search dimension, so every region keeps its own process, output folder,
budget and lock. Aggregated coverage is measured against this entry point only:
it is not the same as a full census of every provincial portal.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from pipeline.research import national_ggzy
from pipeline.research.tender_fields import HEADERS, link_qualifications, normalize

REPO = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = 1
KEYWORDS = "医,卫生,疾控,妇幼,血站,急救"
# Batch 1 was stopped by the platform's rate-limit code after ~700 concurrent
# requests. Workers now share one aggregate pace (one request per --delay
# seconds across all regions) and take one long cooldown before giving up.
CHALLENGE_COOLDOWN = 900
CHALLENGE_RETRIES = 1
MAX_ACTIVE_REGIONS = 3

# (region id, display name, province code, city code, expected province text, expected city text)
BATCHES = {
    1: [
        ("310000", "上海", "310000", "", "上海市", ""),
        ("110000", "北京", "110000", "", "北京市", ""),
        ("440300", "深圳", "440000", "440300", "广东省", "深圳市"),
        ("440100", "广州", "440000", "440100", "广东省", "广州市"),
        ("320000", "江苏", "320000", "", "江苏省", ""),
        ("330000", "浙江", "330000", "", "浙江省", ""),
        ("420000", "湖北", "420000", "", "湖北省", ""),
        ("510000", "四川", "510000", "", "四川省", ""),
        ("370000", "山东", "370000", "", "山东省", ""),
    ],
    2: [
        ("440000", "广东", "440000", "", "广东省", ""),
        ("410000", "河南", "410000", "", "河南省", ""),
        ("350000", "福建", "350000", "", "福建省", ""),
        ("430000", "湖南", "430000", "", "湖南省", ""),
        ("340000", "安徽", "340000", "", "安徽省", ""),
        ("610000", "陕西", "610000", "", "陕西省", ""),
        ("500000", "重庆", "500000", "", "重庆市", ""),
        ("210000", "辽宁", "210000", "", "辽宁省", ""),
        ("120000", "天津", "120000", "", "天津市", ""),
        ("130000", "河北", "130000", "", "河北省", ""),
        ("360000", "江西", "360000", "", "江西省", ""),
        ("450000", "广西", "450000", "", "广西壮族自治区", ""),
        ("140000", "山西", "140000", "", "山西省", ""),
        ("530000", "云南", "530000", "", "云南省", ""),
        ("520000", "贵州", "520000", "", "贵州省", ""),
        ("230000", "黑龙江", "230000", "", "黑龙江省", ""),
        ("220000", "吉林", "220000", "", "吉林省", ""),
        ("150000", "内蒙古", "150000", "", "内蒙古自治区", ""),
        ("650000", "新疆", "650000", "", "新疆维吾尔自治区", ""),
        ("620000", "甘肃", "620000", "", "甘肃省", ""),
        ("640000", "宁夏", "640000", "", "宁夏回族自治区", ""),
        ("630000", "青海", "630000", "", "青海省", ""),
        ("460000", "海南", "460000", "", "海南省", ""),
        ("540000", "西藏", "540000", "", "西藏自治区", ""),
    ],
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def region_values(batch):
    if int(batch) not in BATCHES:
        raise ValueError("Unknown batch; only batch 1 and 2 are defined")
    return [{"id": rid, "name": name, "province": province, "city": city,
             "province_text": ptext, "city_text": ctext, "batch": int(batch),
             "scope": "city" if city else "province"}
            for rid, name, province, city, ptext, ctext in BATCHES[int(batch)]]


def regions_for(request):
    return request["regions"]


def region_for(request, region_id):
    for value in regions_for(request):
        if value["id"] == region_id:
            return value
    raise ValueError(f"Region not in this task: {region_id}")


def validate_scope(start, end, task_id, delay, api_calls, details, regions):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,30}", task_id):
        raise ValueError("Invalid task ID; keep it short enough for the workflow name")
    if date.fromisoformat(start) > date.fromisoformat(end) or date.fromisoformat(end) > date.today():
        raise ValueError("Invalid publication date range")
    if delay < 3 or min(api_calls, details) < 1:
        raise ValueError("Minimum delay is 3 seconds; budgets must be positive")
    if not regions:
        raise ValueError("At least one region is required")
    ids = [value["id"] for value in regions]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate region in the same task")
    for value in regions:
        if not re.fullmatch(r"\d{6}", value["province"]):
            raise ValueError("Province code must be six digits")
        if value["city"] and (not re.fullmatch(r"\d{6}", value["city"]) or not value["city"].startswith(value["province"][:2])):
            raise ValueError("City code must be six digits and belong to the province")
        if not value["province_text"]:
            raise ValueError("Expected province name is required for scope verification")


def contract_files():
    return [Path(__file__), Path(national_ggzy.__file__),
            REPO / "pipeline/research/fetch.py", REPO / "pipeline/research/bid_common.py",
            REPO / "pipeline/research/tender_fields.py", REPO / "pipeline/research/zycg.py",
            REPO / "scripts/export_province_workbook.mjs"]


def request_for(args):
    regions = region_values(args.batch)
    validate_scope(args.start, args.end, args.task_id, args.delay, args.max_api_calls, args.max_details, regions)
    return {"schema_version": SCHEMA_VERSION, "task_id": args.task_id, "batch": int(args.batch),
            "start": args.start, "end": args.end, "date_basis": "publication",
            "scope": "province_medical_digital_procurement",
            "entry": "全国公共资源交易平台省级/市级检索（SOURCE_TYPE=1 + DEAL_PROVINCE/DEAL_CITY）",
            "keywords": KEYWORDS.split(","), "notice_types": ["0202", "0201"], "sources": ["1"],
            "fields": HEADERS, "regions": regions, "region_order": "newest_first",
            "allow_network": True, "delay": args.delay, "max_pages": args.max_pages,
            "max_api_calls": args.max_api_calls, "max_details": args.max_details,
            "workbook_name": f"分省医疗数字化采购_第{int(args.batch)}批_{args.start[:4]}年至今.xlsx",
            "node": args.node, "artifact_modules": args.artifact_modules,
            "code_sha256": {str(p.relative_to(REPO)): digest(p) for p in contract_files()}}


def verify(task_dir):
    task_dir = Path(task_dir)
    request = read(task_dir / "request.json")
    revision_path = task_dir / "code-revisions" / "current.json"
    revision = read(revision_path) if revision_path.exists() else None
    if revision and revision.get("original_request_sha256") != digest(task_dir / "request.json"):
        raise ValueError("Code revision does not match the immutable original request")
    expected = revision["code_sha256"] if revision else request["code_sha256"]
    for filename, value in expected.items():
        if digest(REPO / filename) != value:
            raise ValueError(f"Code changed since task creation; create a new task: {filename}")
    if request.get("allow_network") is not True or request.get("scope") != "province_medical_digital_procurement":
        raise ValueError("Unexpected task contract")
    if revision:
        print(json.dumps({"code_revision": revision["revision"], "reason": revision["reason"]}, ensure_ascii=False), flush=True)
    return request


@contextmanager
def source_lock(folder):
    path = Path(folder) / "source.lock"
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "started_at": now()}, handle)
    except FileExistsError:
        raise ValueError(f"Source lock exists; verify its process before recovery: {path}") from None
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def generate_dag(task_dir, dag_dir, python):
    request = read(task_dir / "request.json")
    dag_name = "pt-" + request["task_id"]
    scalar = lambda x: json.dumps(str(x), ensure_ascii=False)
    executable = "'" + str(python).replace("'", "''") + "'"
    region_steps = [("r_" + value["id"], value["name"] + "（" + value["province_text"] + ("·" + value["city_text"] if value["city_text"] else "") + "）",
                     "run-region --region " + value["id"], ["verify"]) for value in regions_for(request)]
    lines = [f"description: {scalar('分省医疗数字化采购：第' + str(request['batch']) + '批，' + request['start'] + ' 至 ' + request['end'])}",
             "type: graph", "queue: medical-tender-updates", "max_active_steps: " + str(MAX_ACTIVE_REGIONS),
             "working_dir: " + scalar(REPO), "env:", "  PYTHONUTF8: '1'", "  PYTHONDONTWRITEBYTECODE: '1'",
             "  PROVINCE_UPDATE_TASK_DIR: " + scalar(task_dir), "steps:"]
    steps = [("verify", "校验范围、区域与代码版本", "verify", [])] + region_steps
    steps += [("summary", "汇总各省覆盖与缺口", "summarize", [step[0] for step in region_steps]),
              ("export", "生成分省字段表格", "export", ["summary"])]
    for sid, name, command, dependencies in steps:
        lines += ["  - id: " + sid, "    name: " + scalar(name)]
        if dependencies:
            lines += ["    depends: " + json.dumps(dependencies)]
        lines += ["    run: |", f"      & {executable} -u -B -m pipeline.research.province_update {command}",
                  "      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }", "    with:", "      shell: powershell"]
        if sid.startswith("r_") or sid == "summary":
            lines += ["    continue_on:", "      failure: true", "      mark_success: false"]
    lines += ["handler_on:", "  exit:", "    run: |",
              f"      & {executable} -u -B -m pipeline.research.province_update summarize --snapshot",
              "    with:", "      shell: powershell"]
    path = Path(dag_dir) / (dag_name + ".yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def plan(args):
    request = request_for(args)
    task_dir = Path(args.output).resolve() / args.task_id
    if args.dry_run:
        print(json.dumps({"status": "validated", "task_dir": str(task_dir),
                          "batch": request["batch"], "regions": [v["id"] for v in request["regions"]],
                          "region_count": len(request["regions"]), "request": request}, ensure_ascii=False))
        return 0
    if (task_dir / "request.json").exists():
        existing = read(task_dir / "request.json")
        business_scope = lambda value: {k: v for k, v in value.items() if k != "code_sha256"}
        if not args.resume or business_scope(existing) != business_scope(request):
            raise ValueError("Existing task differs or --resume is missing; use a new task ID")
        verify(task_dir)
    else:
        if task_dir.exists() and any(task_dir.iterdir()):
            raise ValueError("Task output is not empty")
        task_dir.mkdir(parents=True, exist_ok=True)
        write(task_dir / "request.json", request)
        for value in request["regions"]:
            folder = task_dir / "regions" / value["id"]
            folder.mkdir(parents=True, exist_ok=True)
            write(folder / "region-progress.json", {"region": value["id"], "name": value["name"], "status": "queued",
                                                    "records": 0, "start": request["start"], "end": request["end"]})
    dag = generate_dag(task_dir, args.dag_dir, args.python)
    print(json.dumps({"status": "planned", "task_dir": str(task_dir), "dag_name": dag.stem, "dag_file": str(dag),
                      "regions": len(request["regions"])}, ensure_ascii=False))
    return 0


def run_region(task_dir, region_id):
    request = verify(task_dir)
    value = region_for(request, region_id)
    folder = Path(task_dir) / "regions" / value["id"]
    folder.mkdir(parents=True, exist_ok=True)
    with source_lock(folder):
        attempts = folder / "attempts"
        attempts.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(os.getpid())
        attempt = attempts / stamp
        attempt.mkdir()
        started = now()
        pacing = {"pace_file": str(Path(task_dir) / ".source-pace"),
                  "pace_interval": float(request["delay"]),
                  "challenge_cooldown": CHALLENGE_COOLDOWN, "challenge_retries": CHALLENGE_RETRIES}
        write(attempt / "code-version.json", {"started_at": started, "region": value, "pacing": pacing,
                                              "code_sha256": {str(p.relative_to(REPO)): digest(p) for p in contract_files()}})
        write(folder / "region-progress.json", {"region": value["id"], "name": value["name"], "status": "running",
                                                 "started_at": started, "records": 0,
                                                 "message": "按最新月份优先扣减本省预算；缺口保留"})
        order = "newest" if request.get("region_order") == "newest_first" else "oldest"
        arguments = ["--start", request["start"], "--end", request["end"], "--output", str(folder),
                     "--delay", str(request["delay"]), "--max-api-calls", str(request["max_api_calls"]),
                     "--max-details", str(request["max_details"]), "--keywords", ",".join(request["keywords"]),
                     "--notice-types", ",".join(request["notice_types"]), "--sources", ",".join(request["sources"]),
                     "--province-code", value["province"], "--province-text", value["province_text"],
                     "--order", order,
                     "--pace-file", pacing["pace_file"], "--pace-interval", str(pacing["pace_interval"]),
                     "--challenge-cooldown", str(CHALLENGE_COOLDOWN), "--challenge-retries", str(CHALLENGE_RETRIES)]
        if value["city"]:
            arguments += ["--city-code", value["city"], "--city-text", value["city_text"]]
        if (folder / "state.json").exists():
            arguments.append("--resume")
        try:
            code = national_ggzy.main(arguments)
        except (Exception, SystemExit) as exc:
            write(folder / "region-progress.json", {"region": value["id"], "name": value["name"], "status": "failed",
                                                     "error": f"{type(exc).__name__}: {exc}"})
            code = 2
        state_file = folder / "state.json"
        state = read(state_file) if state_file.exists() else {}
        rows = []
        for row in state.get("records", {}).values():
            prepared = {**row}
            prepared.setdefault("省份", row.get("省份") or value["province_text"])
            rows.append(prepared)
        write(folder / "records.json", rows)
        progress_file = folder / "progress.json"
        counts = read(progress_file) if progress_file.exists() else {}
        status = "failed" if code == 2 else counts.get("status", "partial")
        write(folder / "region-progress.json", {
            "region": value["id"], "name": value["name"], "scope": value["scope"],
            "province_text": value["province_text"], "city_text": value["city_text"],
            "status": status, "started_at": started, "updated_at": now(), "records": len(rows),
            "api_calls_total": counts.get("api_calls_total"), "detail_calls_total": counts.get("detail_calls_total"),
            "pending_search_windows": counts.get("pending_search_windows"),
            "complete_windows": counts.get("complete_windows"), "failures": counts.get("failures"),
            "excluded_province": counts.get("excluded_province"), "excluded_city": counts.get("excluded_city"),
            "city_unconfirmed": counts.get("city_unconfirmed"), "stop_reason": state.get("stop_reason"),
            "challenge_waits": state.get("challenge_waits", 0), "exit_code": code,
            "message": "已完成声明的检索范围" if counts.get("status") == "completed" else "预算或站点限制导致覆盖不完整，未声称全省全量"})
        write(attempt / "receipt.json", {"region": value["id"], "region_short": value["name"], "started_at": started,
                                          "finished_at": now(), "exit_code": code,
                                          "request_sha256": digest(Path(task_dir) / "request.json")})
        summarize(task_dir, snapshot=True)
        return code


def summarize(task_dir, snapshot=False):
    task_dir = Path(task_dir)
    request = read(task_dir / "request.json")
    region_rows, records, seen, duplicates, city_unconfirmed = [], [], set(), 0, 0
    for value in regions_for(request):
        folder = task_dir / "regions" / value["id"]
        progress = read(folder / "region-progress.json") if (folder / "region-progress.json").exists() else {"status": "queued"}
        state = read(folder / "state.json") if (folder / "state.json").exists() else {}
        accepted = 0
        for row in state.get("records", {}).values():
            published = str(row.get("公告日期") or "")[:10]
            if not request["start"] <= published <= request["end"]:
                continue
            source_url = row.get("相关网页") or ""
            identity = source_url or (str(row.get("项目编号", "")), str(row.get("项目名称", "")))
            if identity in seen:
                duplicates += 1
                continue
            seen.add(identity)
            item = normalize(row, "全国公共资源交易平台·" + value["name"] + "（省级聚合入口）")
            if row.get("_region_city_unconfirmed"):
                city_unconfirmed += 1
                item["信息缺口"] = "；".join(x for x in [item.get("信息缺口", ""), "市级归属未在返回字段中标注"] if x)
            records.append(item)
            accepted += 1
        region_rows.append({"source": value["id"], "source_name": value["name"], "scope": value["scope"],
                            "province_text": value["province_text"], "city_text": value["city_text"],
                            "status": progress.get("status", "queued"), "records": accepted,
                            "api_calls_total": progress.get("api_calls_total"),
                            "detail_calls_total": progress.get("detail_calls_total"),
                            "pending_search_windows": progress.get("pending_search_windows"),
                            "complete_windows": progress.get("complete_windows"),
                            "city_unconfirmed": progress.get("city_unconfirmed"),
                            "stop_reason": progress.get("stop_reason") or progress.get("error") or progress.get("message")})
    statuses = [row["status"] for row in region_rows]
    status = "completed" if all(s == "completed" for s in statuses) else "running" if any(s in ("running", "queued") for s in statuses) else "partial"
    link_qualifications(records)
    summary = {"task_id": request["task_id"], "batch": request["batch"], "status": status, "generated_at": now(),
               "start": request["start"], "end": request["end"], "date_basis": "publication",
               "entry": request.get("entry"), "records": len(records), "regions_total": len(region_rows),
               "regions_completed": sum(1 for s in statuses if s == "completed"),
               "duplicates_removed": duplicates, "city_unconfirmed": city_unconfirmed,
               "sources": region_rows, "facts_verified": False,
               "note": "分省记录来自全国公共资源交易平台的省级聚合检索，覆盖以该入口收录为限，不等于各省门户全量；"
                       "深圳、广州为市级口径，与广东省级窗口存在重叠，已按网址去重；公告数不等于独立项目数。"}
    target = task_dir / ("snapshot-" + str(os.getpid()) + ".json") if snapshot else task_dir / "summary.json"
    write(target, summary)
    if not snapshot:
        export = task_dir / "delivery"
        export.mkdir(exist_ok=True)
        write(export / "records.json", records)
        import csv
        with (export / "公告明细.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=HEADERS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
        lines = ["# 分省医疗数字化采购更新（第" + str(request["batch"]) + "批）", "",
                 f"发布日期范围：{request['start']} 至 {request['end']}。", "",
                 f"总体状态：{status}；保留记录 {len(records)} 条；区域 {summary['regions_completed']}/{summary['regions_total']} 个完成声明范围。", "",
                 "| 区域 | 口径 | 执行状态 | 记录数 | 未完成检索窗口 |", "| --- | --- | --- | ---: | ---: |"]
        lines += [f"| {r['source_name']} | {'市级' if r['scope'] == 'city' else '省级'} | {r['status']} | {r['records']} | {r['pending_search_windows'] if r['pending_search_windows'] is not None else ''} |" for r in region_rows]
        lines += ["", summary["note"], "", "各区域未完成原因与失败记录见 regions/<区域>/region-progress.json 与 progress.json。"]
        (export / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "sources"}, ensure_ascii=False), flush=True)
    return 0 if snapshot or status == "completed" else 3


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--task-id", required=True)
    p.add_argument("--batch", type=int, choices=[1, 2], required=True)
    p.add_argument("--start", default="2024-01-01")
    p.add_argument("--end", default=date.today().isoformat())
    p.add_argument("--output", default=str(REPO / "outputs/province-updates"))
    p.add_argument("--dag-dir", required=True)
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--node", required=True)
    p.add_argument("--artifact-modules", required=True)
    p.add_argument("--delay", type=float, default=3.5)
    p.add_argument("--max-pages", type=int, default=100)
    p.add_argument("--max-api-calls", type=int, default=1600)
    p.add_argument("--max-details", type=int, default=1400)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--resume", action="store_true")
    sub.add_parser("verify")
    sub.add_parser("export")
    p = sub.add_parser("run-region")
    p.add_argument("--region", required=True)
    p = sub.add_parser("summarize")
    p.add_argument("--snapshot", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            return plan(args)
        task_dir = Path(os.environ["PROVINCE_UPDATE_TASK_DIR"]).resolve()
        if args.command == "verify":
            value = verify(task_dir)
            print(json.dumps({"status": "validated", "task_id": value["task_id"], "batch": value["batch"],
                              "regions": len(value["regions"]), "start": value["start"], "end": value["end"]}))
            return 0
        if args.command == "export":
            request = read(task_dir / "request.json")
            return subprocess.call([request["node"], str(REPO / "scripts/export_province_workbook.mjs"),
                                    str(task_dir), request["artifact_modules"]])
        if args.command == "run-region":
            return run_region(task_dir, args.region)
        return summarize(task_dir, args.snapshot)
    except (KeyError, ValueError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
