"""中央国家机关政府采购中心（央采）医卫数字化中标采集。

口径与边界：
- “央采”= 公告中采购执行机构为“中央国家机关政府采购中心”的项目，用检索接口的 agentName 精确锁定，
  不靠采购人名称猜测。
- 只取中标（成交）结果类公告（/zbgg/ 中标公告、/cjgg/ 成交公告），排除招标、更正、终止公告。
- 医卫数字化 = 采购对象是医疗卫生机构/卫生行政/疾控/医保，且采购内容为数字化产品与服务；
  只有医卫属性没有数字化属性的（餐饮、保洁、纯医疗设备）不进表。

已知入口失败：央采本站 www.zycg.gov.cn 的公告列表接口 /freecms/rest/v1/notice/selectInfoMore.do
对任何参数组合都返回 {"code":"-1","msg":"公告列表查询失败"}，因此列表发现改走中国政府采购网检索接口，
其公告与央采本站同源（正文末尾即“中央国家机关政府采购中心”署名）。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from pipeline.research.bid_common import (
    COLUMNS,
    DIGITAL,
    MED_ORG,
    NON_DIGITAL,
    STAGE_WORDS,
    amount_field,
    amount_wan,
    build_row,
    carrier_type,
    classify_scope,
    clean,
    customer_tag,
    field,
    labeled_lines,
    scene_of,
    write_bid_workbook,
)
from pipeline.research.fetch import Fetcher
from pipeline.research.tenders import decode_html, write_json
from pipeline.research.tender_fields import add_fields

SEARCH_URL = "http://search.ccgp.gov.cn/bxsearch"
AGENT = "中央国家机关政府采购中心"
ALLOWED_DOMAINS = ["search.ccgp.gov.cn", "www.ccgp.gov.cn"]


def page_html(result: dict) -> str:
    """取页结果里 raw 是原始字节；text 只是可读文本，不能用来选 DOM。"""
    raw = result.get("raw")
    if raw:
        return decode_html(raw)
    return result.get("text") or ""


def search_url(page: int, start: str, end: str) -> str:
    params = {
        "searchtype": "1", "page_index": str(page), "bidSort": "0", "buyerName": "",
        "projectId": "", "pinMu": "0", "bidType": "0", "dbselect": "bidx", "kw": "",
        "start_time": start.replace("-", ":"), "end_time": end.replace("-", ":"),
        "timeType": "6", "displayZone": "", "zoneId": "", "pppStatus": "0",
        "agentName": AGENT,
    }
    return f"{SEARCH_URL}?{urlencode(params)}"


def parse_search_page(html: str) -> list[dict]:
    """解析检索结果列表。每行自带发布时间、地域、采购人、代理机构与公告类型。"""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for li in soup.select("ul.vT-srch-result-list-bid li"):
        link = li.find("a")
        if not link or not link.get("href"):
            continue
        text = clean(li.get_text(" ", strip=True))
        notice_date = re.search(r"(20\d{2})\.(\d{2})\.(\d{2})", text)
        buyer = re.search(r"采购人[：:]\s*([^|]+?)\s*(?:\||代理机构|$)", text)
        agent = re.search(r"代理机构[：:]\s*([^|]+?)\s+(中标公告|成交公告|招标公告|公开招标公告|"
                          r"更正公告|终止公告|单一来源|询价|竞争性|资格预审|其他公告)", text)
        region = re.search(r"(中标公告|成交公告|招标公告|公开招标公告|更正公告|终止公告)\s*\|\s*([^\s|]+)", text)
        items.append({
            "title": clean(link.get_text(" ", strip=True)),
            "url": link["href"],
            "published_at": f"{notice_date.group(1)}-{notice_date.group(2)}-{notice_date.group(3)}"
            if notice_date else "",
            "buyer": clean(buyer.group(1)) if buyer else "",
            "agent": clean(agent.group(1)) if agent else "",
            "notice_type": agent.group(2) if agent else "",
            "region": clean(region.group(2)) if region else "",
        })
    return items


def is_result_notice(url: str) -> bool:
    """只要中标/成交结果公告；招标、更正、终止公告不进入结果表。"""
    return "/zbgg/" in url or "/cjgg/" in url


def parse_detail(html: str, url: str, fallback: dict | None = None) -> dict:
    fallback = fallback or {}
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one("div.vF_detail_content") or soup.select_one("div.vF_detail_main") or soup
    text = node.get_text("\n", strip=True)
    flat = clean(text)

    suppliers = [v for k, v in labeled_lines(text).items() if k.startswith("供应商名称")]
    if not suppliers:
        suppliers = re.findall(r"供应商名称[：:]\s*([^\n]{2,40})", text)
    amount_raw = amount_field(text, "(?:中标（成交）金额|中标金额|成交金额|成交价)") or \
        amount_field(text, "中标（成交）金额")

    buyer = field(text, r"采购人信息\s*名\s*称") or fallback.get("buyer", "")
    agency = field(text, r"采购执行机构信息\s*名\s*称")

    products = extract_products(soup)
    project = field(text, "项目名称") or fallback.get("title", "")
    project = re.sub(r"(中标（成交）结果公告|中标公告|成交公告)$", "", clean(project)).strip()
    code = field(text, "项目编号", r"[A-Za-z0-9\-\[\]（）()．./]{4,40}")
    budget = amount_wan(field(text, "预算金额"))
    return {
        "公告标题": fallback.get("title", ""),
        "项目名称": project,
        "项目编号": code,
        "采购方式": field(text, "采购方式", r"[\u4e00-\u9fa5]{2,10}"),
        "预算金额（万元）": budget,
        "招标单位": buyer,
        "采购执行机构": agency,
        "中标单位": "；".join(dict.fromkeys(clean(s) for s in suppliers if clean(s))),
        "中标金额原文": amount_raw,
        "中标金额（万元）": amount_wan(amount_raw),
        "产品": "、".join(products[:4]),
        "品牌": "、".join(extract_brands(soup)[:4]),
        "正文长度": len(flat),
        "公告链接": url,
        "公告日期": fallback.get("published_at", ""),
        "地域": fallback.get("region", ""),
    }


def _bid_table_rows(soup: BeautifulSoup) -> list[list[str]]:
    rows = []
    for table in soup.select("table"):
        header = clean(table.get_text(" ", strip=True))[:60]
        if not re.search(r"标的|品牌|规格型号", table.get_text(" ", strip=True)):
            continue
        for tr in table.select("tr"):
            cells = [clean(td.get_text(" ", strip=True)) for td in tr.select("td,th")]
            cells = [c for c in cells if c]
            if len(cells) >= 3:
                rows.append(cells)
    return rows


def extract_products(soup: BeautifulSoup) -> list[str]:
    """取“主要投标标的名称”列；跳过序号列与表头。"""
    out: list[str] = []
    for cells in _bid_table_rows(soup):
        first = cells[0]
        if re.fullmatch(r"\d+", first):
            if len(cells) > 1:
                out.append(cells[1])
        elif re.search(r"标的名称|货物名称|服务名称", first):
            continue
        else:
            out.append(first)
    cleaned = [c for c in (clean(x) for x in out)
               if c and len(c) <= 40 and not c.isdigit() and c not in {"序号", "主要投标标的名称", "标的名称"}]
    return list(dict.fromkeys(cleaned))


def extract_brands(soup: BeautifulSoup) -> list[str]:
    brands: list[str] = []
    for cells in _bid_table_rows(soup):
        if len(cells) >= 4 and not re.fullmatch(r"\d+", cells[0]):
            continue
        if len(cells) >= 4:
            brand = cells[2]
            if brand and not re.fullmatch(r"[\d.]+", brand) and len(brand) <= 20:
                brands.append(brand)
    return list(dict.fromkeys(brands))


def month_windows(start: str, end: str) -> list[tuple[str, str]]:
    """按月切窗：检索站对单次查询的深页（page_index≥100）返回挑战页，按月切可把每窗压到20多页。"""
    first = datetime.strptime(start, "%Y-%m-%d").date()
    last = datetime.strptime(end, "%Y-%m-%d").date()
    windows = []
    cursor = first.replace(day=1)
    while cursor <= last:
        month_end = (cursor.replace(day=28) + __import__("datetime").timedelta(days=4)).replace(day=1) - __import__("datetime").timedelta(days=1)
        w_start = max(cursor, first)
        w_end = min(month_end, last)
        windows.append((w_start.isoformat(), w_end.isoformat()))
        cursor = month_end + __import__("datetime").timedelta(days=1)
    return windows


def discover(fetcher: Fetcher, start: str, end: str, max_pages: int, log, cache_dir: Path | None = None, tag: str = ""):
    """按页发现公告。抓到的原始页落盘缓存，被挑战打断后重跑可续采，不重复请求已取页。"""
    discover.blocked_at = None
    found: list[dict] = []
    failures: list[dict] = []
    seen: set[str] = set()
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
    blocked_at = None
    for page in range(1, max_pages + 1):
        url = search_url(page, start, end)
        name = f"page-{tag}-{page:04d}.html" if tag else f"page-{page:04d}.html"
        cache_file = cache_dir / name if cache_dir else None
        raw = None
        if cache_file and cache_file.exists() and cache_file.stat().st_size > 2000:
            raw = cache_file.read_bytes()
            log(f"[discovery] 第{page}页命中缓存")
        if raw is None:
            result = fetcher.fetch(url, ALLOWED_DOMAINS)
            if result["status"] != "ok":
                failures.append({"stage": "discovery", "code": result["status"], "url": url,
                                 "page": page, "reason": result.get("error", "")})
                log(f"[discovery] 第{page}页失败：{result['status']} {result.get('error','')[:80]}")
                blocked_at = page
                break
            raw = result.get("raw") or b""
            if cache_file and raw:
                cache_file.write_bytes(raw)
        html = decode_html(raw)
        items = parse_search_page(html)
        if not items:
            soup = BeautifulSoup(html, "html.parser")
            if not soup.select_one("ul.vT-srch-result-list-bid") and not re.search(r"没有找到|暂无相关|共找到\s*0\s*条", soup.get_text(" ", strip=True)):
                failures.append({"stage": "discovery", "code": "unexpected_response", "url": url,
                                 "page": page, "reason": "未取得有效搜索列表；可能为挑战页面，不能按空结果完成"})
                blocked_at = page
                break
            log(f"[discovery] 第{page}页无结果，结束")
            break
        fresh = 0
        for item in items:
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            fresh += 1
            found.append(item)
        dates = [i["published_at"] for i in items if i["published_at"]]
        log(f"[discovery] 第{page}页 {len(items)} 条，新增 {fresh}，日期 {min(dates) if dates else '-'}~{max(dates) if dates else '-'}")
        pagination = re.search(r"Pager\s*\(\s*\{\s*size\s*:\s*(\d+)", html, re.S)
        if pagination and page >= int(pagination.group(1)):
            log("[discovery] 已达到页面声明的最后一页，窗口完整结束")
            break
        if dates and max(dates) < start:
            log("[discovery] 已早于起始日期，结束翻页")
            break
        if fresh == 0:
            failures.append({"stage": "discovery", "code": "repeated_page", "url": url,
                             "page": page, "reason": "重复列表页，历史范围尚未证明遍历完成"})
            break
        time.sleep(random.uniform(0, 0.8))
    else:
        failures.append({"stage": "discovery", "code": "page_budget", "page": max_pages,
                         "reason": "达到列表页预算，尚未证明本窗口已遍历完成"})
    if blocked_at:
        log(f"[discovery] 在第{blocked_at}页被站点挑战打断，已保留已取页缓存；稍后重跑会从缓存续采")
    discover.blocked_at = blocked_at
    return found, failures


def load_from_cache(cache_dirs: list[Path], log) -> list[dict]:
    """离线合并多个运行目录已落盘的列表页，用于限流期间不重复请求站点。"""
    notices: list[dict] = []
    seen: set[str] = set()
    for folder in cache_dirs:
        folder = Path(folder)
        files = sorted(set(folder.glob("page-*.html")) | set((folder / "cache").glob("page-*.html")))
        log(f"[cache] {folder} 列表页 {len(files)} 个")
        for path in files:
            for item in parse_search_page(decode_html(path.read_bytes())):
                if item["url"] in seen:
                    continue
                seen.add(item["url"])
                notices.append(item)
    log(f"[cache] 合并去重后 {len(notices)} 条公告")
    return notices


def collect(start: str, end: str, out_dir: Path, max_pages: int, timeout: int, delay: float,
            limit: int | None = None, dry_run: bool = False, split_monthly: bool = True,
            from_cache: list[Path] | None = None, progress=None, include_all=False) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "cache").mkdir(parents=True, exist_ok=True)
    fetcher = Fetcher(timeout=timeout, retries=1, delay=delay)
    lines: list[str] = []

    def log(message: str) -> None:
        print(message, flush=True)
        lines.append(message)
        if progress:
            progress(message)

    try:
        windows = month_windows(start, end) if split_monthly else [(start, end)]
        notices, failures, seen = [], [], set()
        blocked_windows = []
        completed_windows = []
        if from_cache:
            notices = load_from_cache(from_cache + [out_dir / "cache"], log)
            windows = [(start, end)]
        for w_start, w_end in ([] if from_cache else windows):
            tag = f"{w_start}_{w_end}"
            log(f"[window] {w_start}~{w_end}")
            part, part_fail = discover(fetcher, w_start, w_end, max_pages, log, out_dir / "cache", tag)
            failures.extend(part_fail)
            if getattr(discover, "blocked_at", None):
                blocked_windows.append(tag)
            for notice in part:
                if notice["url"] in seen:
                    continue
                seen.add(notice["url"])
                notices.append(notice)
            if part_fail:
                log("[pause] 本窗口出现缺口，停止后续窗口；保留缓存供显式恢复")
                break
            completed_windows.append((w_start, w_end))
        log(f"[discovery] 分{len(windows)}个窗口，去重后共 {len(notices)} 条公告；被挑战窗口 {len(blocked_windows)} 个")
        outside_window = [n for n in notices if not n.get("published_at") or not start <= n["published_at"] <= end]
        results = [n for n in notices if (include_all or is_result_notice(n["url"])) and n.get("published_at") and start <= n["published_at"] <= end]
        log(f"[discovery] 结果类公告 {len(results)} 条（总抓取 {len(notices)} 条，含招标/更正/终止）")

        kept, review = [], []
        for notice in results:
            ok, reason = classify_scope(notice["title"], notice["buyer"])
            (kept if ok else review).append({**notice, "scope_reason": reason})
        log(f"[filter] 医卫数字化候选 {len(kept)} 条；排除 {len(review)} 条")
        detail_limited = bool(limit and len(kept) > limit)
        if limit:
            kept = kept[:limit]

        records, detail_failures = [], []
        for index, notice in enumerate(kept, 1):
            if dry_run:
                records.append({**notice, "row": {}, "detail": {}})
                continue
            detail_name = f"detail-{hashlib.md5(notice['url'].encode()).hexdigest()[:12]}.html"
            cache_file = out_dir / "cache" / detail_name
            raw = None
            for folder in [out_dir / "cache"] + [Path(d) for d in (from_cache or [])]:
                candidate = Path(folder) / detail_name
                if candidate.exists() and candidate.stat().st_size > 2000:
                    raw = candidate.read_bytes()
                    break
            result = {"status": "ok", "raw": raw} if raw else fetcher.fetch(notice["url"], ALLOWED_DOMAINS)
            if result["status"] == "ok" and raw is None:
                cache_file.write_bytes(result.get("raw") or b"")
            if result["status"] != "ok":
                detail_failures.append({"stage": "detail", "code": result["status"], "url": notice["url"],
                                         "title": notice["title"], "reason": result.get("error", "")})
                log(f"[detail] {index}/{len(kept)} 失败：{notice['title'][:32]} {result['status']}")
                continue
            detail = parse_detail(page_html(result), notice["url"], notice)
            detail["公告类型"] = notice.get("notice_type", "")
            if not is_result_notice(notice["url"]):
                detail["中标单位"] = ""
                detail["中标金额（万元）"] = None
                detail["中标金额原文"] = ""
                detail["信息缺口"] = "非最终结果公告，未填写中标事实"
            add_fields(detail, page_html(result), notice["title"], notice["url"])
            row = build_row(detail)
            if not detail.get("产品"):
                row["产品"] = ""
            records.append({"row": row, "detail": detail, "notice": notice})
            log(f"[detail] {index}/{len(kept)} {row['项目名称'][:30]} | {row['中标金额（万元）']} 万元 | {row['场景']}")
    finally:
        fetcher.close()

    pending_windows = [w for w in windows if w not in completed_windows] if not from_cache else []
    status = "partial" if failures or detail_failures or pending_windows or detail_limited or dry_run or from_cache else "completed"
    payload = {
        "status": status,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "中国政府采购网中央公告（代理机构=中央国家机关政府采购中心）",
        "window": {"start": start, "end": end},
        "counts": {"notices": len(notices), "result_notices": len(results),
                   "candidates": len(kept), "records": len(records),
                   "excluded": len(review), "detail_failures": len(detail_failures)},
        "records": records,
        "excluded": review,
        "windows": windows,
        "completed_windows": completed_windows,
        "pending_windows": pending_windows,
        "outside_or_unknown_date": outside_window,
        "details_limited": detail_limited,
        "blocked_windows": blocked_windows,
        "blocked_at_page": getattr(discover, "blocked_at", None),
        "failures": failures + detail_failures,
        "log": lines,
    }
    write_json(out_dir / "zycg_medical_bid.json", payload)
    write_table(records, out_dir, start, end)
    return 0 if status == "completed" else 3


def write_table(records: list[dict], out_dir: Path, start: str = "2026-01-01", end: str = "2026-12-31") -> None:
    """八列主表 + 明细页；出表逻辑与北京/雄安共用在 bid_common。"""
    write_bid_workbook(
        records, out_dir,
        stem="央采医卫数字化中标_" + (start[:4] if start[:4] == end[:4] else start[:4] + "-" + end[:4]),
        sheet_title="央采医卫数字化中标",
        detail_columns=["公告日期", "公告类型", "项目编号", "采购方式", "预算金额（万元）",
                        "地域", "品牌", "中标金额原文", "公告链接"],
    )



def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="央采医卫数字化中标采集")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--output", default="outputs/zycg-medical-from-2024")
    parser.add_argument("--max-pages", type=int, default=400)
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--delay", type=float, default=1.2)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="只跑列表发现与过滤，不取详情")
    parser.add_argument("--no-split", action="store_true", help="不按月切窗（单次查询超过100页会被站点挑战）")
    parser.add_argument("--from-cache", default="", help="逗号分隔的已有运行目录，离线合并其列表页缓存，不再请求检索站")
    parser.add_argument("--all-notices", action="store_true", help="同时保留采购公告与资格要求；非结果公告不填写中标事实")
    args = parser.parse_args(argv)
    if date.fromisoformat(args.start) > date.fromisoformat(args.end) or args.max_pages < 1 or args.delay < 0 or (args.limit is not None and args.limit < 1):
        parser.error("Invalid date range or collection budget")
    cache_dirs = [Path(x.strip()) for x in args.from_cache.split(",") if x.strip()]
    return collect(args.start, args.end, Path(args.output), args.max_pages,
                   args.timeout, args.delay, args.limit, args.dry_run, not args.no_split, cache_dirs or None, include_all=args.all_notices)


if __name__ == "__main__":
    sys.exit(main())
