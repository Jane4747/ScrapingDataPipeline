# -*- coding: utf-8 -*-
"""机构官网 / 微信公众号 补录工具。

两条腿：
  1) 官网：候选域名猜测 -> DNS + HTTP 探测 -> 首页 title 与机构名做 token 重合校验。
     只有「域名可达 且 title 里出现机构核心词」才算命中，低于阈值的一律记为未命中，不硬认。
  2) 公众号：公众号不在公网上，无法用 HTTP 验证。只能走检索补录，
     本脚本只负责把检索结果结构化落盘，不猜测公众号名（猜错比留空更糟）。

用法：
  python scripts/institution_contact_enrich.py probe --limit 30
  python scripts/institution_contact_enrich.py report
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import openpyxl

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# 机构全称里要剥掉的行政前缀，剩下的才是域名会用到的核心词
STRIP_PREFIX = [
    "中国医学科学院", "首都医科大学附属", "上海交通大学医学院附属", "复旦大学附属",
    "浙江大学医学院附属", "中山大学附属", "四川大学华西", "中南大学湘雅",
    "北京大学", "北京", "上海", "广州医科大学附属", "南京医科大学附属",
    "山东大学齐鲁", "武汉大学人民", "华中科技大学同济医学院附属", "同济大学附属",
    "天津医科大学", "中国医科大学附属", "南方医科大学", "重庆医科大学附属",
    "哈尔滨医科大学附属", "吉林大学", "郑州大学", "安徽医科大学", "福建医科大学附属",
    "苏州大学附属", "西安交通大学医学院", "河南省人民", "山东省立", "广东省人民",
    "江苏省人民", "浙江省人民", "四川省人民", "河北省人民", "医科大学", "大学",
]

# 已知的真实域名映射（人工核实过，作为种子和校验基准）
KNOWN = {
    "中国医学科学院阜外医院": ["www.fuwaihospital.org", "www.fuwai.com"],
    "中南大学湘雅医院": ["www.xiangya.com.cn"],
}

SUFFIX_CANDIDATES = [
    "hospital.com.cn", "hospital.org.cn", "hospital.com", "hosp.com.cn",
    "yy.com.cn", "hospital.cn", ".com.cn", ".org.cn", ".com", ".cn",
]


def core_tokens(name: str) -> list[str]:
    """剥掉行政前缀后取核心词，用于域名构造与 title 校验。"""
    s = name
    for p in sorted(STRIP_PREFIX, key=len, reverse=True):
        if s.startswith(p) and len(s) - len(p) >= 3:
            s = s[len(p):]
            break
    s = re.sub(r"(医院|医疗中心|中心医院|卫生院|护理院|妇幼保健院|疗养院|中心)$", "", s)
    return [s] if s and len(s) >= 2 else []


def pinyin_initial(s: str) -> str:
    """只处理 ASCII 场景；中文拼音缩写需要词库，这里不做，返回空。"""
    return "" if re.search(r"[\u4e00-\u9fff]", s) else s.lower()


def candidates(name: str) -> list[str]:
    """生成候选域名。中文机构名没有可靠拼音映射，主要靠『英文/拼音缩写』种子。
    没有可靠候选就返回空，不要为了凑数造域名。"""
    out = []
    if name in KNOWN:
        out.extend(KNOWN[name])
    # 名称里若本身含英文（如 XX Hospital），尝试提取
    m = re.findall(r"[A-Za-z]{3,}", name)
    if m:
        w = m[0].lower()
        for suf in [".com.cn", ".com", ".org.cn"]:
            out.append(w + suf)
    seen, uniq = set(), []
    for d in out:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq


def http_title(domain: str, timeout: int = 8) -> tuple[int, str]:
    """抓取首页 title。"""
    import urllib.request

    for scheme in ("https", "http"):
        url = f"{scheme}://{domain}/"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                body = r.read(200000).decode("utf-8", errors="ignore")
                m = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
                return r.status, (m.group(1).strip() if m else "")
        except Exception:
            continue
    return 0, ""


def title_match(title: str, name: str) -> bool:
    """域名首页 title 必须能佐证它属于这家机构，否则不算命中。"""
    if not title:
        return False
    core = core_tokens(name)
    t = title.replace(" ", "")
    for c in core:
        if c and c in t:
            return True
    # 兜底：title 里包含机构全称的前 3 个字
    return bool(name[:3] in t and len(name) >= 3)


def probe_one(row: dict) -> dict:
    name = row["机构全称"]
    res = {"机构全称": name, "机构ID": row["机构ID"], "省份": row["省份"],
           "候选域名": [], "命中": None, "http状态": 0, "首页title": "",
           "官网": "", "命中方式": ""}
    if name in KNOWN:
        for d in KNOWN[name]:
            code, title = http_title(d)
            if code == 200 and title_match(title, name):
                res.update({"候选域名": KNOWN[name], "命中": True, "http状态": code,
                            "首页title": title[:120], "官网": f"https://{d}",
                            "命中方式": "已知域名映射+title校验"})
                return res
    cands = candidates(name)
    res["候选域名"] = cands
    return res


def load_master(xlsx: Path) -> list[dict]:
    wb = openpyxl.load_workbook(xlsx)
    ws = wb["07_机构主表"]
    hdr = [c.value for c in ws[1]]
    return [dict(zip(hdr, [c.value for c in r])) for r in ws.iter_rows(min_row=2)]


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe")
    p.add_argument("--xlsx", default="outputs/institution-registry-20261030/机构台账_六表_20261031.xlsx")
    p.add_argument("--out", default="outputs/institution-registry-20261030/_research/org_contact_probe.json")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--workers", type=int, default=8)

    p2 = sub.add_parser("report")
    p2.add_argument("--src", default="outputs/institution-registry-20261030/_research/org_contact_probe.json")

    args = ap.parse_args()

    if args.cmd == "probe":
        rows = load_master(Path(args.xlsx))[: args.limit]
        t0 = time.time()
        out = []
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(probe_one, r): r for r in rows}
            for f in as_completed(futs):
                out.append(f.result())
        out.sort(key=lambda x: x["机构ID"])
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        hit = sum(1 for r in out if r["命中"])
        withcand = sum(1 for r in out if r["候选域名"])
        print(json.dumps({
            "机构数": len(out), "有候选域名": withcand, "title校验命中": hit,
            "耗时秒": round(time.time() - t0, 1), "输出": args.out,
        }, ensure_ascii=False, indent=2))
        return

    data = json.loads(Path(args.src).read_text(encoding="utf-8"))
    hit = [r for r in data if r["命中"]]
    print(f"共 {len(data)} 家，命中 {len(hit)} 家，缺候选 {sum(1 for r in data if not r['候选域名'])} 家")
    for r in hit:
        print(f"  {r['机构全称'][:26]:28s} -> {r['官网']}  ({r['首页title'][:40]})")


if __name__ == "__main__":
    main()
