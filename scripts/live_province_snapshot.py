"""Build a read-only delivery snapshot from a running province task.

`run_region` only writes `delivery/` when the whole task is summarised, so a task
that is still collecting cannot show its newest rows. This helper reuses the same
field mapping and de-duplication rules as `province_update.summarize`, but writes
to a separate directory and never touches the task's own `delivery/` or state.

Usage:
    python -B -m scripts.live_province_snapshot <task_dir> <out_dir> <workbook_name>
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from pipeline.research.province_update import write
from pipeline.research.tender_fields import HEADERS, link_qualifications, normalize

ENTRY_SUFFIX = "（省级聚合入口）"


def build(task_dir, out_dir, workbook_name):
    task_dir, out_dir = Path(task_dir).resolve(), Path(out_dir).resolve()
    request = json.loads((task_dir / "request.json").read_text(encoding="utf-8-sig"))
    records, seen, duplicates, city_unconfirmed = [], set(), 0, 0
    sources = []
    for value in request["regions"]:
        folder = task_dir / "regions" / value["id"]
        state_path = folder / "state.json"
        progress_path = folder / "progress.json"
        if not state_path.exists():
            sources.append({"source_name": value["name"], "scope": value["scope"], "status": "queued",
                            "records": 0, "pending_search_windows": None, "stop_reason": None})
            continue
        state = json.loads(state_path.read_text(encoding="utf-8-sig"))
        live = json.loads(progress_path.read_text(encoding="utf-8-sig")) if progress_path.exists() else {}
        accepted = 0
        for row in state.get("records", {}).values():
            published = str(row.get("公告日期") or "")[:10]
            if not request["start"] <= published <= request["end"]:
                continue
            identity = row.get("相关网页") or (str(row.get("项目编号", "")), str(row.get("项目名称", "")))
            if identity in seen:
                duplicates += 1
                continue
            seen.add(identity)
            item = normalize(row, "全国公共资源交易平台·" + value["name"] + ENTRY_SUFFIX)
            if row.get("_region_city_unconfirmed"):
                city_unconfirmed += 1
                item["信息缺口"] = "；".join(x for x in [item.get("信息缺口", ""), "市级归属未在返回字段中标注"] if x)
            records.append(item)
            accepted += 1
        sources.append({"source_name": value["name"], "scope": value["scope"],
                        "status": live.get("status", "unknown"), "records": accepted,
                        "pending_search_windows": live.get("pending_search_windows"),
                        "stop_reason": live.get("stop_reason")})
    summary = {"task_id": request["task_id"], "batch": request["batch"], "status": "partial",
               "generated_at": datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0).isoformat(),
               "start": request["start"], "end": request["end"], "date_basis": "publication",
               "entry": request.get("entry"), "records": len(records),
               "regions_total": len(request["regions"]), "regions_completed": 0,
               "duplicates_removed": duplicates, "city_unconfirmed": city_unconfirmed,
               "sources": sources, "facts_verified": False,
               "note": "进行中快照：直接读实时 state.json，不是正式交付；正式文件由 Dagu 的 summary/export 步骤在跑完后生成。"}
    (out_dir / "delivery").mkdir(parents=True, exist_ok=True)
    write(out_dir / "request.json", {**request, "workbook_name": workbook_name})
    write(out_dir / "summary.json", summary)
    write(out_dir / "delivery" / "records.json", records)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_dir")
    parser.add_argument("out_dir")
    parser.add_argument("workbook_name")
    args = parser.parse_args(argv)
    summary = build(args.task_dir, args.out_dir, args.workbook_name)
    print(json.dumps({"status": "snapshot", "records": summary["records"],
                      "duplicates_removed": summary["duplicates_removed"],
                      "city_unconfirmed": summary["city_unconfirmed"],
                      "fields": len(HEADERS)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
