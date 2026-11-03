# -*- coding: utf-8 -*-
"""把 8 个分片的官网/公众号检索结果合并成一份可索引的对照文件。

只做合并与去重，不做推断。同名多条时保留"信息更全"的那条，并在 note 里记录冲突。

用法：
  python scripts/merge_institution_contact.py \
      --contact-dir outputs/institution-registry-20261030/_contact \
      --out configs/institution_contact_20261101.json
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


def norm(s: str) -> str:
    return re.sub(r"[\s（）()]", "", s or "")


def norm_url(u: str) -> str:
    """统一 scheme / www / 尾斜杠后再比较，避免把同一域名判成冲突。"""
    u = (u or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/")


def richness(r: dict) -> int:
    """有官网 +2，有公众号 +2，note 非空 +1。用于同名取更全的一条。"""
    return (2 if r.get("website") else 0) + (2 if r.get("wechat") else 0) + \
           (1 if r.get("note") else 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--contact-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows, conflicts = [], []
    by_name, by_id = {}, {}
    files = sorted(Path(args.contact_dir).glob("result_part*.json"))
    if not files:
        raise SystemExit(f"未在 {args.contact_dir} 找到 result_part*.json")

    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        for r in d.get("rows", []):
            name = (r.get("机构全称") or "").strip()
            if not name:
                continue
            rec = {
                "机构ID": r.get("机构ID", ""),
                "机构全称": name,
                "官网": (r.get("website") or "").strip(),
                "官网来源": (r.get("website_source") or "").strip(),
                "微信公众号": (r.get("wechat") or "").strip(),
                "公众号来源": (r.get("wechat_source") or "").strip(),
                "状态": r.get("status", ""),
                "备注": (r.get("note") or "").strip(),
            }
            key = norm(name)
            if key in by_name:
                old = by_name[key]
                if richness(rec) > richness(old):
                    by_name[key] = rec
                    rows[rows.index(old)] = rec
                if old["官网"] and rec["官网"] and norm_url(old["官网"]) != norm_url(rec["官网"]):
                    conflicts.append({"机构全称": name, "A": old["官网"], "B": rec["官网"]})
            else:
                by_name[key] = rec
                rows.append(rec)
            if rec["机构ID"]:
                by_id[rec["机构ID"]] = rec

    out = {
        "meta": {
            "merged_from": [f.name for f in files],
            "机构数": len(rows),
            "有官网": sum(1 for r in rows if r["官网"]),
            "有公众号": sum(1 for r in rows if r["微信公众号"]),
            "仅官网": sum(1 for r in rows if r["官网"] and not r["微信公众号"]),
            "两项皆空": sum(1 for r in rows if not r["官网"] and not r["微信公众号"]),
            "状态分布": dict(Counter(r["状态"] for r in rows)),
            "官网域名冲突": conflicts,
            "note": ("公众号只在官方页面写出明确名称时才录入，未用机构全称推断。"
                     "官网排除第三方挂号平台与聚合登记页。"),
        },
        "rows": rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(json.dumps(out["meta"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
