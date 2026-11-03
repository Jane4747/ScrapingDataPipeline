#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按认证主体抓取省级运营商公众号（名称 + 微信号 + 主办方 + 简介）。

数据源：wxnum.cn（第三方收录站）。该站对“订阅号/发布号”覆盖较好，
对“服务号/营业厅号”（如 XX移动10086）覆盖差，因此结果偏内容发布端，
恰好对应传播 mapping 需要的“可投放内容号”。
任何一条在投放前仍须在微信搜一搜核对认证主体。
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request

SEARCH = "https://www.wxnum.cn/search/?w="
SITE = "https://www.wxnum.cn"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"

PROVINCES = [
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
    "广东", "广西", "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西",
    "甘肃", "青海", "宁夏", "新疆",
]

OPS = [
    ("移动", ["{p}移动10086", "{p}移动", "{p}移动发布", "{p}移动掌厅"],
     ["中国移动通信集团" + "{p}"]),
    ("电信", ["{p}电信", "{p}电信10000", "{p}天翼", "{p}电信发布"],
     ["中国电信股份有限公司" + "{p}", "中国电信集团" + "{p}", "中国电信股份有限公司" + "{p}分公司"]),
    ("联通", ["{p}联通", "{p}联通10010", "{p}联通发布", "{p}联通客服"],
     ["中国联合网络通信有限公司" + "{p}"]),
]

CARD_HREF = re.compile(r'^<a href="(/[a-z0-9\-]+\.html)"')
CARD_H3 = re.compile(r'<h3>(.*?)</h3>', re.S)
CARD_CORP = re.compile(r'<span class="s-r-corp">主办方：\s*([^<]*)</span>')
CARD_INFO = re.compile(r'<span class="l-infos">(.*?)</span>', re.S)
ID_RE = re.compile(r'公众号ID[:：]\s*(?:<[^>]+>\s*)*([A-Za-z0-9_\-]{4,40})')


def strip_tags(s):
    return re.sub(r'<[^>]+>', '', s or '').strip()


def fetch(url, retries=2):
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception:
            if i == retries:
                return ""
            time.sleep(2)


def search(kw):
    html = fetch(SEARCH + urllib.parse.quote(kw))
    out = []
    for block in re.split(r'(?=<a href="/[a-z0-9\-]+\.html")', html):
        m_href = CARD_HREF.match(block)
        if not m_href:
            continue
        m_corp = CARD_CORP.search(block)
        m_h3 = CARD_H3.search(block)
        if not (m_corp and m_h3):
            continue
        m_info = CARD_INFO.search(block)
        out.append({
            "slug": m_href.group(1),
            "name": strip_tags(m_h3.group(1)),
            "corp": strip_tags(m_corp.group(1)),
            "intro": strip_tags(m_info.group(1))[:120] if m_info else "",
        })
    return out


def get_wxid(slug):
    html = fetch(SITE + slug)
    m = ID_RE.search(html)
    return m.group(1) if m else ""


def main():
    provinces = ["广东", "四川"] if "--probe" in sys.argv else PROVINCES
    results, reqs = {}, 0
    for p in provinces:
        results[p] = {}
        for op, tmpls, corp_keys in OPS:
            hits = {}
            for t in tmpls:
                kw = t.format(p=p)
                for r in search(kw):
                    reqs += 1
                    ok = any(k.format(p=p) in r["corp"] for k in corp_keys)
                    if not ok or r["name"] in hits:
                        continue
                    r["kw"] = kw
                    hits[r["name"]] = r
                time.sleep(1.2)
            for name, r in hits.items():
                r["wxid"] = get_wxid(r["slug"])
                reqs += 1
                time.sleep(1.0)
            results[p][op] = sorted(hits.values(), key=lambda x: x["name"])
            print(f"[{p}/{op}] {len(hits)} -> " +
                  " | ".join(f'{x["name"]}({x["wxid"] or "-"})' for x in results[p][op]),
                  file=sys.stderr)
    out = ("outputs/pr-gzh-wxnum/probe2.json" if "--probe" in sys.argv
           else "outputs/pr-gzh-wxnum/candidates.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print(f"requests={reqs} -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
