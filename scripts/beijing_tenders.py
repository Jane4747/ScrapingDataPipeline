"""Experimental Beijing tender discovery and draft extraction.

This separate portal adapter was not used for the 2026-10-27 full-roster rerun.
Its live transport and portal behaviour are not covered by offline tests.
Use the bounded research task pipeline for production collection. Extraction
produces pending drafts; export requires review_status=reviewed and then applies
the shared date, roster, evidence and award-field validation.

This fills the gap left by ``tender_tools.py``: that adapter takes candidate URLs
as given, so every project needed a manual search step. Here the discovery is
automated against the two statutory portals, notice pages are fetched and parsed,
and only then does the existing seven-column export apply.

Why curl: ``ggzyfw.beijing.gov.cn`` negotiates an EC curve that Python's OpenSSL
build rejects (SSL: BAD_ECPOINT), so requests/urllib fail before TLS completes.
curl is used as the transport only; all parsing stays in Python.

Two portals are used because neither alone is sufficient:

* ``search.ccgp.gov.cn`` — statutory publisher, keeps the historical archive, but
  rate-limits ("频繁访问") and its search tokenises the query.
* ``ggzyfw.beijing.gov.cn`` — keeps only the last ~month of list pages, so the
  archive is reachable only through its full-text search, which OR-tokenises
  "北京普康中医医院" into "中医|医院" and returns 486k rows. The workaround is to
  scan the index by keyword in date order and match the roster offline.

Usage::

    python -B scripts/beijing_tenders.py roster  --workbook X.xlsx --sheet 03-一级医院 --output hospitals.json
    python -B scripts/beijing_tenders.py portal  --roster hospitals.json --output out/ccgp
    python -B scripts/beijing_tenders.py scan    --roster hospitals.json --output out/scan
    python -B scripts/beijing_tenders.py verify  --hits out/scan/hits.json --roster hospitals.json --output out/verified
    python -B scripts/beijing_tenders.py extract --hits out/ccgp/hits.json --roster hospitals.json --output out/records
    python -B scripts/beijing_tenders.py export  --roster hospitals.json --records out/records/records.json --output out

Run ``verify`` before ``extract``: tokenised search recall is noisy, and a title
that names a same-brand hospital of another tier is not a hit. Every stage caches
raw HTML, so a rerun is cheap and a partial run is resumable.
"""
from __future__ import annotations

import argparse, csv, json, re, shutil, subprocess, sys, time, urllib.parse
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

HEADERS = ["项目名称", "产品", "招标单位", "客户标签", "中标单位", "中标金额（万元）", "来源与追溯"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
AWARD_WORDS = ("中标公告", "成交公告", "中标结果公告", "成交结果公告", "合同公告")
TENDER_WORDS = ("公开招标公告", "招标公告", "比选公告", "遴选公告", "竞争性磋商公告",
                "竞争性谈判公告", "询价公告", "单一来源公告")
NOT_AWARD = ("废标公告", "终止公告", "更正公告", "采购意向")


# ---------------------------------------------------------------- transport

def http(url, data=None, referer=None, timeout=45):
    cmd = ["curl", "-s", "--compressed", "-m", str(timeout), "-L",
           "-H", "User-Agent: " + UA, "-H", "Accept: */*",
           "-H", "Accept-Language: zh-CN,zh;q=0.9"]
    if referer:
        cmd += ["-H", "Referer: " + referer]
    if data is not None:
        cmd += ["-H", "X-Requested-With: XMLHttpRequest",
                "-H", "Content-Type: application/x-www-form-urlencoded; charset=UTF-8",
                "--data-binary", data]
    cmd.append(url)
    out = subprocess.run(cmd, capture_output=True).stdout
    return out.decode("utf-8", "ignore")


def cached(folder, key, fetch):
    f = Path(folder) / (re.sub(r"\W+", "_", key)[-90:] + ".html")
    if f.exists():
        return f.read_text(encoding="utf-8", errors="ignore")
    html = fetch()
    if html and len(html) > 800:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(html, encoding="utf-8", errors="ignore")
        return html
    return ""


# ---------------------------------------------------------------- roster

def load_roster(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data


def name_key(name):
    """Match key: drop the 北京市 prefix so either form in a title will hit."""
    return re.sub(r"[\s\u3000]+", "", re.sub(r"^北京市?", "", name))


# ---------------------------------------------------------------- portal (ccgp)

def portal_search(kw, page=1, wait=2.5, tries=4):
    q = {"searchtype": "1", "page_index": str(page), "bidSort": "0", "buyerName": "",
         "projectId": "", "pinMu": "0", "bidType": "0", "dbselect": "bidx", "kw": kw,
         "start_time": "", "end_time": "", "timeType": "", "displayZone": "",
         "zoneId": "", "pppStatus": "0", "agentName": ""}
    url = "http://search.ccgp.gov.cn/bxsearch?" + urllib.parse.urlencode(q)
    for i in range(tries):
        html = http(url, referer="http://www.ccgp.gov.cn/")
        if "频繁访问" not in html and len(html) > 2000:
            return html
        time.sleep(wait * (i + 2))
    return ""


def portal_count(html):
    m = re.search(r"共找到[^0-9]{0,40}(\d+)", html)
    return int(m.group(1)) if m else None


def portal_items(html):
    out = []
    for m in re.finditer(r'<li[^>]*>\s*<a href="(http[^"]+)"[^>]*>(.*?)</a>(.*?)</li>', html, re.S):
        url = m.group(1)
        title = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", m.group(2)))
        # A URL timestamp is not evidence of the announcement's date.
        d = re.search(r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})", text_of(m.group(3)))
        typ = re.search(r"(中标公告|成交公告|招标公告|更正公告|废标公告|终止公告)", title)
        out.append({"title": title, "url": url,
                    "date": "%04d-%02d-%02d" % tuple(map(int,d.groups())) if d else "",
                    "date_source": "列表可见日期，待正文核实" if d else "",
                    "type": typ.group(1) if typ else ""})
    return out


def cmd_portal(args):
    roster = load_roster(args.roster)
    out_dir = Path(args.output)
    hits, log = [], []
    for n, h in enumerate(roster, 1):
        kw = name_key(h["name"])
        html = cached(out_dir / "pages", kw,
                      lambda kw=kw: portal_search(kw))
        if not html:
            log.append({"id": h["id"], "name": h["name"], "query": kw, "status": "error"})
            print(f"[{n:3d}/{len(roster)}] ERR {h['name'][:30]}", flush=True)
            continue
        total = portal_count(html) or 0
        log.append({"id": h["id"], "name": h["name"], "query": kw,
                    "count": total, "status": "ok"})
        for it in portal_items(html):
            it.update({"hospital_id": h["id"], "hospital": h["name"],
                       "district": h.get("district", ""), "query": kw})
            hits.append(it)
        print(f"[{n:3d}/{len(roster)}] {total:2d} {h['name'][:30]}", flush=True)
        time.sleep(args.wait)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "hits.json").write_text(json.dumps(hits, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"queried": len(log), "hits": len(hits)}, ensure_ascii=False))


# ---------------------------------------------------------------- exchange scan

EXCHANGE = "https://ggzyfw.beijing.gov.cn/elasticsearch/search"
EXCHANGE_REF = "https://ggzyfw.beijing.gov.cn/elasticsearch/index.jsp"
AWARD_PATH, TENDER_PATH = "/jyxxzbjggg/", "/jyxxcggg/"


def exchange_search(word, page=1, size=100):
    payload = urllib.parse.urlencode({"searchword": word, "scope": "", "page": page,
                                      "size": size, "sort": "", "starttime": "", "endtime": ""})
    for _ in range(3):
        raw = http(EXCHANGE, payload, referer=EXCHANGE_REF)
        if raw.strip():
            d = json.loads(raw)
            return d["total"], json.loads(d["result"])
        time.sleep(1.5)
    raise RuntimeError("exchange search failed for %r" % word)


def cmd_scan(args):
    """Scan the index by keyword, then match the roster locally."""
    roster = load_roster(args.roster)
    out_dir = Path(args.output)
    rows, seen = [], set()
    for kw in args.keywords:
        total, pages = 0, 0
        for page in range(1, args.max_pages + 1):
            key = "%s_%d" % (kw, page)
            raw = cached(out_dir / "pages", key, lambda: "")
            if raw:
                rec = json.loads(raw)
            else:
                try:
                    total, items = exchange_search(kw, page, args.size)
                except Exception as exc:                       # noqa: BLE001
                    print("  %s p%d ERR %s" % (kw, page, exc), flush=True)
                    break
                rec = {"total": total, "items": items}
                (out_dir / "pages").mkdir(parents=True, exist_ok=True)
                (out_dir / "pages" / (re.sub(r"\W+", "_", key) + ".json")).write_text(
                    json.dumps(rec, ensure_ascii=False), encoding="utf-8")
                time.sleep(args.wait)
            pages = page
            for it in rec["items"]:
                link = it.get("link", "")
                if link in seen:
                    continue
                seen.add(link)
                rows.append({"title": re.sub(r"<[^>]+>", "", it.get("title", "")),
                             "date": it.get("releaseDate", ""), "link": link,
                             "code": it.get("projectCode", ""),
                             "source": it.get("source", "")})
            if len(rec["items"]) < args.size or page * args.size >= rec["total"]:
                break
        print("%s: pages=%d total=%s" % (kw, pages, total), flush=True)

    idx = {name_key(h["name"]): h for h in roster}
    hits = []
    for r in rows:
        title = re.sub(r"^\[[^\]]*\]", "", r["title"])
        for key, h in idx.items():
            if len(key) >= 6 and key in title:
                hits.append({**r, "hospital_id": h["id"], "hospital": h["name"],
                             "district": h.get("district", "")})
                break
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "hits.json").write_text(json.dumps(hits, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"scanned": len(rows), "hits": len(hits)}, ensure_ascii=False))


# ---------------------------------------------------------------- verification

ORG = re.compile(r"[\u4e00-\u9fa5（）()]{4,28}?(?:医院|卫生院|门诊部|护理院|社区卫生服务中心)")


def _owner(title):
    """Longest institution name mentioned in a notice title."""
    cands = [m.group(0) for m in ORG.finditer(title)]
    return max(cands, key=len) if cands else ""


def cmd_verify(args):
    """Reject brand-core recall that names a *namesake* institution.

    A tokenised search for 「长庚医院」 returns 北京清华长庚医院 — a tertiary
    hospital sharing a brand with a tier-1 namesake. Importing those titles would
    fill the table with records that are not about the roster at all, so a hit
    only counts when the full roster name (or an alias of 6+ characters) appears
    in the title. Everything else is written to rejected.json with the reason.
    """
    roster = {h["id"]: h for h in load_roster(args.roster)}
    hits = json.loads(Path(args.hits).read_text(encoding="utf-8"))
    keep, drop = [], []
    for h in hits:
        info = roster.get(h["hospital_id"], {})
        full = info.get("name", "")
        raw_aliases = info.get("aliases") or []
        if isinstance(raw_aliases,str):raw_aliases = re.split(r"[；;,，\n]",raw_aliases)
        aliases = [a.strip() for a in raw_aliases if len(a.strip()) >= 6]
        title = re.sub(r"<[^>]+>", "", h.get("title", ""))
        if full and (full in title or any(a in title for a in aliases)):
            keep.append(h)
        else:
            who = _owner(title)
            drop.append({**h, "roster_name": full, "actual_owner": who,
                         "verdict": "标题未确认名单医院；识别名称为「%s」，须核查正文及上级采购关系" % who})
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "confirmed.json").write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "rejected.json").write_text(json.dumps(drop, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"confirmed": len(keep), "rejected": len(drop)}, ensure_ascii=False))


# ---------------------------------------------------------------- parsing

def text_of(html):
    h = re.sub(r"<(script|style).*?</\1>", " ", html, flags=re.S | re.I)
    h = re.sub(r"<br\s*/?>", "\n", h, flags=re.I)
    h = re.sub(r"</(p|div|tr|li|h\d)>", "\n", h, flags=re.I)
    h = re.sub(r"</t[dh]>", "\t", h, flags=re.I)   # keep cell boundaries for label\tvalue rows
    h = re.sub(r"<[^>]+>", "", h)
    h = h.replace("&nbsp;", " ").replace("&amp;", "&")
    h = re.sub(r"[ \u3000]+", " ", h)
    return re.sub(r"\n\s*\n+", "\n", h)


def _grab(pat, text, flags=0):
    m = re.search(pat, text, flags)
    return m.group(1).strip(" :：\t") if m else None


def tidy_amount(s):
    """'50.000000万元' -> '50万元'."""
    if not s:
        return s
    return re.sub(r"(\d+)\.(\d*?)0+(?=\s*万?元)",
                  lambda m: m.group(1) + ("." + m.group(2) if m.group(2) else ""), s)


def product_noun(project_name, hospital=""):
    """The purchase object, read off the project name: '…医用耗材采购项目' -> '医用耗材'.

    Preferred over the portal's 品目 classification, which falls back to a
    catch-all such as 「其他医疗设备」 even when the notice is about consumables.
    """
    s = (project_name or "").strip()
    for pre in (hospital, "北京市", "北京"):
        if pre and s.startswith(pre):
            s = s[len(pre):]
            break
    cut = len(s)
    for suf in ("采购项目", "比选项目", "招标项目", "公开招标", "竞争性磋商",
                "竞争性谈判", "单一来源", "项目", "采购", "比选", "招标",
                "（", "(", "【", "["):
        i = s.find(suf)
        if 0 < i < cut:
            cut = i
    return s[:cut].strip("，、；:： ")


def product_hint(t):
    """Fallback description from the 品目 row and the 采购需求 sentence."""
    parts = []
    m = re.search(r"^\s*品目\t([^\n\t]{2,80})", t, re.M)
    if m:
        cat = m.group(1).strip()
        if "/" in cat:
            cat = cat.rsplit("/", 1)[-1].strip() or cat
        if not cat.startswith("其他"):
            parts.append(cat)
    m = re.search(r"采购需求[:：]\s*([^\n]{4,200})", t)
    if m:
        need = re.split(r"[。；]", re.sub(r"\s+", "", m.group(1)))[0]
        parts.append(need[:80])
    return "；".join(dict.fromkeys(p for p in parts if p))


def parse_notice(html, title=""):
    t = text_of(html)
    published = re.search(r"(?:发布时间|公告时间|发布日期)[\s:：]*(\d{4})[-年](\d{1,2})[-月](\d{1,2})",t)
    code = (_grab(r"(?:^|\n)[一二三四]?[、.．]?\s*项目编号[:：]\s*(\[[0-9]{4}\][0-9A-Za-z\-]{4,40})", t)
            or _grab(r"(?:^|\n)[一二三四]?[、.．]?\s*项目编号[:：]\s*([0-9A-Za-z\-（）()]{6,40})", t)
            or _grab(r"项目编号[:：]\s*(110[0-9A-Za-z\-（）()]{6,40})", t))
    winners = []
    for m in re.finditer(r"中标成交供应商名称[:：]\s*([^\n]{2,60})", t):
        seg = t[m.end(): m.end() + 200]
        amt = re.search(r"中标金额[:：]\s*([\d,\.]+\s*万?元)", seg)
        winners.append({"name": m.group(1).strip(), "amount": amt.group(1).strip() if amt else ""})
    products = []
    i = html.find("主要标的信息")
    if i > 0:
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html[i: i + 20000], re.S):
            cells = [re.sub(r"\s+", " ", text_of(c)).strip()
                     for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
            if len(cells) >= 3 and cells[1] and cells[1] not in ("商品名称", "标的名称"):
                if cells[1] not in products:
                    products.append(cells[1])
    m = re.search(r"采购人信息.{0,40}?名\s*称[:：]\s*([^\n]{2,60})", t, re.S)
    buyer = m.group(1).strip(" :：\t") if m else None
    if not buyer:                       # central-portal summary strip: "采购单位\tX\t"
        buyer = _grab(r"^\s*采购单位\t([^\n\t]{2,60})", t, re.M)
    return {
        "project_name": _grab(r"项目名称[:：]\s*([^\n]{2,120})", t) or title,
        "project_code": code,
        "purchaser": buyer,
        "total_amount": (_grab(r"总中标成交金额[:：]\s*([\d,\.]+\s*万?元)", t)
                         or _grab(r"中标（成交）金额[:：]\s*([\d,\.]+\s*万?元)", t)),
        "budget": _grab(r"预算金额[\t :：]*[￥¥]?\s*([\d,\.]+\s*万?元)", t),
        "winners": winners, "products": products[:8],
        "product_hint": product_hint(t),
        "date": "%04d-%02d-%02d" % tuple(map(int,published.groups())) if published else "",
        "announcement_type": next((w for w in NOT_AWARD + AWARD_WORDS + TENDER_WORDS
                                   if w in title), "公告"),
    }


def to_wan(quote):
    if not quote:
        return None
    m = re.search(r"([\d.]+)\s*(万元|元)", str(quote).replace(",", ""))
    if not m:
        return None
    try:
        v = Decimal(m.group(1))
    except InvalidOperation:
        return None
    return float(v / Decimal(10000) if m.group(2) == "元" else v)


def cmd_extract(args):
    roster = {h["id"]: h for h in load_roster(args.roster)}
    hits = json.loads(Path(args.hits).read_text(encoding="utf-8"))
    out_dir = Path(args.output)
    records, skipped = [], []
    for h in hits:
        title = h.get("title", "")
        if any(k in title for k in NOT_AWARD):
            skipped.append({"title": title, "why": "非结果类公告"})
            continue
        html = cached(out_dir / "pages", h["url"], lambda u=h["url"]: http(u, timeout=40))
        if not html:
            skipped.append({"title": title, "why": "原文不可取", "url": h["url"]})
            continue
        p = parse_notice(html, title)
        hosp = roster.get(h["hospital_id"], {})
        label = "；".join(filter(None, [hosp.get("level", ""), hosp.get("category", ""),
                                        hosp.get("district", "")]))
        product = ("；".join(p["products"][:4])
                   or product_noun(p["project_name"], hosp.get("name", ""))
                   or p["product_hint"])
        note = (h.get("source") or
                ("中国政府采购网（法定发布媒介）" if "ccgp.gov.cn" in h["url"]
                 else "北京市公共资源交易服务平台"))
        if p["purchaser"] and hosp.get("name") and hosp["name"] not in p["purchaser"]:
            note += "；公告采购人为「%s」，与名单医院的关系待核实" % p["purchaser"]
        if p["product_hint"] and p["product_hint"] not in product:
            note += "；采购内容：%s" % p["product_hint"][:70]
        if not p["winners"] and not p["total_amount"]:
            note += "；本次未解析到中标单位及金额，公告阶段和缺失原因待核实"
            if p["budget"]:
                note += "，预算 %s（预算不当中标金额）" % tidy_amount(p["budget"])
        base = {"hospital_id": h["hospital_id"], "project_name": p["project_name"],
                "product": product, "purchaser": p["purchaser"] or "",
                "customer_label": label, "date": p["date"], "url": h["url"],
                "listed_date": h.get("date", ""), "review_status": "pending",
                "project_number": p["project_code"] or h.get("code", ""),
                "announcement_type": p["announcement_type"],
                "quote": (p["total_amount"] or ""), "source_note": note}
        aw = any(w in p["announcement_type"] for w in AWARD_WORDS)
        if aw and p["winners"]:
            for w in p["winners"]:
                records.append({**base, "winner": w["name"], "amount_wan": to_wan(w["amount"]),
                                "amount_quote": w["amount"]})
        else:
            records.append({**base, "winner": "", "amount_wan": None, "amount_quote": ""})
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "records.json").write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "skipped.json").write_text(json.dumps(skipped, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"records": len(records), "skipped": len(skipped)}, ensure_ascii=False))


# ---------------------------------------------------------------- export

def cmd_export(args):
    from tender_tools import export_records,read_json,save_json
    records = json.loads(Path(args.records).read_text(encoding="utf-8"))
    if not getattr(args,"roster",None):
        raise ValueError("导出必须提供 --roster，以校验医院名单")
    roster = load_roster(args.roster)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    reviewed=[r for r in records if r.get("review_status")=="reviewed"]
    pending=[{"record":r,"reasons":["自动抽取草稿尚未核实；需阅读原文、补全证据并设置review_status=reviewed"]}
             for r in records if r.get("review_status")!="reviewed"]
    result=export_records(roster,reviewed,out_dir,
                          since=getattr(args,"since","2024-01-01"),
                          until=getattr(args,"until",date.today().isoformat()))
    pending=read_json(out_dir/'records.needs_review.json')+pending
    save_json(out_dir/'records.needs_review.json',pending)
    path = out_dir / "records.csv"
    shutil.copyfile(out_dir/'北京一级医院数智化招采信息.csv',path)
    print(json.dumps({"rows":result['accepted'],"needs_review":len(pending),"file":str(path)},ensure_ascii=False))


def _cell(v):
    """Neutralise spreadsheet formulas without corrupting genuinely empty cells.

    ``"" in "=+-@"`` is True in Python, so a naive membership test would prefix
    every blank field with an apostrophe.
    """
    if v is None:
        return ""
    if isinstance(v, str):
        return "'" + v if v[:1] and v[:1] in "=+-@" else v
    return v


# ---------------------------------------------------------------- cli

def cmd_roster(args):
    from tender_tools import read_roster
    roster = [h for h in read_roster(args.workbook) if h["level"].startswith("一级")]
    Path(args.output).write_text(json.dumps(roster, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"hospitals": len(roster)}, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("roster"); q.add_argument("--workbook", required=True)
    q.add_argument("--output", required=True); q.set_defaults(func=cmd_roster)

    q = sub.add_parser("portal"); q.add_argument("--roster", required=True)
    q.add_argument("--output", required=True); q.add_argument("--wait", type=float, default=2.5)
    q.set_defaults(func=cmd_portal)

    q = sub.add_parser("scan"); q.add_argument("--roster", required=True)
    q.add_argument("--output", required=True)
    q.add_argument("--keywords", nargs="+", default=["医院", "中医院", "中西医结合"])
    q.add_argument("--max-pages", type=int, default=100)
    q.add_argument("--size", type=int, default=100)
    q.add_argument("--wait", type=float, default=0.45)
    q.set_defaults(func=cmd_scan)

    q = sub.add_parser("extract"); q.add_argument("--hits", required=True)
    q.add_argument("--roster", required=True); q.add_argument("--output", required=True)
    q.set_defaults(func=cmd_extract)

    q = sub.add_parser("verify"); q.add_argument("--hits", required=True)
    q.add_argument("--roster", required=True); q.add_argument("--output", required=True)
    q.set_defaults(func=cmd_verify)

    q = sub.add_parser("export"); q.add_argument("--records", required=True)
    q.add_argument("--roster"); q.add_argument("--output", required=True)
    q.add_argument("--since",default="2024-01-01");q.add_argument("--until",default=date.today().isoformat())
    q.set_defaults(func=cmd_export)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
