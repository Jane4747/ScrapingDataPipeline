"""Crawl CAICT research listings and keep medical or health pages."""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "caict-kxyj-health"

SECTIONS = {
    "蓝皮书": "https://www.caict.ac.cn/kxyj/qwfb/bps/",
    "ICT深度观察": "https://www.caict.ac.cn/kxyj/qwfb/sdgc/",
    "权威数据": "https://www.caict.ac.cn/kxyj/qwfb/qwsj/",
    "专题报告": "https://www.caict.ac.cn/kxyj/qwfb/ztbg/",
    "CAICT观点": "https://www.caict.ac.cn/kxyj/caictgd/",
}

MEDICAL_TERMS = (
    "医疗",
    "医药",
    "医院",
    "卫生",
    "医保",
    "药监",
    "生物医药",
    "数字健康",
    "智慧医疗",
    "大健康",
    "公共卫生",
    "诊疗",
    "药品",
    "医疗器械",
    "健康医疗",
    "医疗健康",
    "健康中国",
    "健康产业",
)
METAPHOR = re.compile(r"健康(发展|稳定|有序|运行|可持续|成长|平稳)")
ARTICLE = re.compile(r"/kxyj/.+\.(?:htm|html|pdf)(?:$|\?)", re.I)
DATE_IN_URL = re.compile(r"/t(20\d{6})_")
MAX_PAGES = 80


def matched_terms(title: str) -> list[str]:
    found = [term for term in MEDICAL_TERMS if term in title]
    remainder = METAPHOR.sub("", title)
    if "健康" in remainder and "健康" not in found:
        found.append("健康")
    return found


def published_on(url: str) -> str:
    match = DATE_IN_URL.search(url)
    if not match:
        return ""
    raw = match.group(1)
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


async def listing_links(crawler, url: str) -> list[dict]:
    config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=45000)
    result = await crawler.arun(url=url, config=config)
    if not result.success:
        return [], ""
    rows = []
    next_url = ""
    for item in (result.links or {}).get("internal") or []:
        href = urljoin(url, (item.get("href") or "").strip())
        text = (item.get("text") or "").replace("\xa0", " ").strip()
        if text == "下一页" and href:
            next_url = href
        if ARTICLE.search(href) and "index" not in href.rsplit("/", 1)[-1]:
            rows.append({"href": href.split("#")[0], "text": text})
    return rows, next_url


async def crawl_section(crawler, name: str, start: str) -> tuple[list[dict], int]:
    seen_pages = set()
    found = {}
    url = start
    pages = 0
    while url and url not in seen_pages and pages < MAX_PAGES:
        seen_pages.add(url)
        pages += 1
        try:
            rows, next_url = await listing_links(crawler, url)
        except Exception as exc:
            print(f"FAIL {name} {url} {exc}")
            break
        print(f"{name} page {pages} items {len(rows)}")
        for row in rows:
            title = row["text"] or row["href"]
            terms = matched_terms(title)
            if not terms:
                continue
            found[row["href"]] = {
                "栏目": name,
                "标题": title,
                "日期": published_on(row["href"]),
                "链接": row["href"],
                "命中词": "、".join(terms),
                "列表页": url,
            }
        url = next_url
    return list(found.values()), pages


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    collected = []
    page_counts = {}
    async with AsyncWebCrawler() as crawler:
        for name, start in SECTIONS.items():
            rows, pages = await crawl_section(crawler, name, start)
            collected.extend(rows)
            page_counts[name] = pages
    collected.sort(key=lambda row: (row["日期"], row["栏目"]), reverse=True)
    frame = pd.DataFrame(collected)
    excel = OUT / "caict_kxyj_health.xlsx"
    payload = {
        "source": "https://www.caict.ac.cn/kxyj/",
        "theme": "医疗、健康",
        "crawled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pages_scanned": page_counts,
        "count": len(collected),
        "rows": collected,
    }
    (OUT / "caict_kxyj_health.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if collected:
        frame.to_excel(excel, index=False)
    print(json.dumps({"count": len(collected), "pages": page_counts, "excel": str(excel)}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
