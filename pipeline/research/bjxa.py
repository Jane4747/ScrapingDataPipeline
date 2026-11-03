"""北京、雄安医卫数字化中标采集。

口径沿用 `pipeline/research/bid_common.py`（与央采同一套八列），本模块只处理这两地的站点差异。

入口勘察结论（2026-10-27 实测）：

1. 北京市公共资源交易服务平台 `ggzyfw.beijing.gov.cn`：首页与 robots.txt 一律 403（WAF 拦截本站 UA）。
   按“遇到拒绝不绕过、不伪装浏览器 UA、不关证书校验”的既定规则，该入口不用，只记录留证。
2. 北京市政府采购网 `www.ccgp-beijing.gov.cn`：市级/区级「中标公告」列表是静态 HTML，
   翻页形如 `A002004001002index_N.htm`。实测每个频道 TotalPage=143，第 144 页直接 404，
   即站点只保留最近约 2000 条列表（市级回溯到 2026-07-15、区级回溯到 2026-08-10）。
   站内检索接口 `/api/search/query` 可查全史，但 `range` 日期过滤实测无效（各种格式一律 0 条或 400），
   因此不能靠它按月补窗。结论：北京主链路取静态列表可达范围，缺口在文档里写明。
3. 雄安新区公共资源交易服务平台 `www.xaprtc.com`：交易公开 → 政府采购（channelId=273）为列表，
   10 条/页、翻页形如 `queryContent_2-jyxx.jspx?channelId=273`，可回溯到 2026 年初。
   但详情页是壳：公告类型/交易方式/项目编号为空，只有「公告来源」指向河北省政府采购网。
   正文必须再取一次 `ccgp-hebei.gov.cn/xazq/...` 或 `.../bd/bd_rc/...` 的文章页，
   其正文由内嵌 JS 字符串（`content`、`PROJECTNAME`、`PurchaserName`）渲染，需按 `#_@_@` 分节解析。

节流：全部请求走 `pipeline/research/fetch.py` 的 Fetcher——robots 检查、单站点最小间隔、
401/403/429 判 blocked 不重试不绕过、UA 自报 `CAICTMedicalResearchBot/1.0`。
列表页与详情页都落盘缓存，重跑命中缓存不发请求，`--from-cache` 可离线重出表。
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from pipeline.research.bid_common import (
    COLUMNS,
    amount_field,
    amount_wan,
    boundary_hint,
    build_row,
    classify_scope,
    clean,
    customer_tag,
    field,
    write_bid_workbook,
    write_csv,
)
from pipeline.research.fetch import Fetcher
from pipeline.research.tenders import decode_html, write_json
from pipeline.research.zycg import month_windows, parse_search_page

# 北京市政府采购网：市级/区级「中标公告」列表。站点只保留 143 页，第 144 页 404。
BEIJING_CHANNELS = [
    ("市级", "shi", "http://www.ccgp-beijing.gov.cn/xxgg/sjxxgg/zbggs/A002004001002index_{page}.htm"),
    ("区级", "qu", "http://www.ccgp-beijing.gov.cn/xxgg/qjxxgg/qjzbggs/A002004002002index_{page}.htm"),
]
BEIJING_DOMAINS = ["www.ccgp-beijing.gov.cn", "ccgp-beijing.gov.cn"]

# 雄安新区公共资源交易服务平台：交易公开→政府采购（channelId=273），10 条/页。
XIONGAN_FIRST = "https://www.xaprtc.com/queryContent-jyxx.jspx?channelId=273"
XIONGAN_PAGE = "https://www.xaprtc.com/queryContent_{page}-jyxx.jspx?channelId=273"
XIONGAN_DOMAINS = ["www.xaprtc.com", "xaprtc.com"]

# 补窗与正文来源：中国政府采购网（robots.txt 404，无额外约束）。
# 河北政采 robots.txt 返回 403，按 fail-closed 不取；雄安平台详情页只是壳，因此正文走 ccgp 镜像。
CCGP_SEARCH = "http://search.ccgp.gov.cn/bxsearch"
CCGP_DOMAINS = ["search.ccgp.gov.cn", "www.ccgp.gov.cn"]
BEIJING_ZONE = "110000"

# 地域口径：检索站按全文命中，"雄县"能命中云南"镇雄县"，"中标"能命中外省项目，
# 因此候选池必须在入表前过一道地域校验（见 region_guard）。
# 雄安的地名要带行政后缀：裸"安新"会命中浙江"磐安新城区"、营口"华安新邨"。
BEIJING_LOCAL_RE = r"北京|东城|西城|朝阳|丰台|石景山|海淀|门头沟|房山|通州|顺义|昌平|大兴|怀柔|平谷|密云|延庆"
XIONGAN_LOCAL_RE = r"雄安|容城县|安新县|(?<!镇)雄县|容东|容西"
# 雄安宣武医院这类项目由北京单位代发，检索站地域标签给的是"北京"，故一并放行
XIONGAN_REGION_LABELS = {"河北", "北京", "雄安", "雄安新区"}


def _plain(text: str) -> str:
    """检索结果标题里的关键词高亮会被 get_text 拆成"安新 县"，比对地名前先去掉空白。"""
    return re.sub(r"\s+", "", text or "")

BEIJING_DETAIL_COLUMNS = ["公告日期", "公告渠道", "项目编号", "采购方式", "采购代理机构",
                          "中标金额原文", "品牌", "公告链接"]
XIONGAN_DETAIL_COLUMNS = ["公告日期", "公告区县", "项目编号", "预算金额（万元）", "采购人",
                          "标的名称", "各包金额（元）", "公告来源", "公告链接"]


def page_html(result: dict) -> str:
    raw = result.get("raw")
    return decode_html(raw) if raw else (result.get("text") or "")


def cache_name(prefix: str, key: str) -> str:
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}.html"


def read_cache(path: Path) -> bytes | None:
    if path.exists() and path.stat().st_size > 1500:
        return path.read_bytes()
    return None


# ---------------------------------------------------------------- 北京


def beijing_list_url(channel_url: str, page: int) -> str:
    return channel_url.format(page=page)


def parse_beijing_list(html: str, channel: str = "", base: str = "http://www.ccgp-beijing.gov.cn/") -> list[dict]:
    """列表项只有标题与日期，采购人/金额都要进详情页取。"""
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict] = []
    for li in soup.select("ul.inner-ul li"):
        link = li.find("a")
        if not link or not link.get("href"):
            continue
        raw_title = clean(link.get_text(" ", strip=True))
        if not raw_title:
            continue
        date_node = li.select_one("span.datetime") or li.find("span")
        published = clean(date_node.get_text(" ", strip=True)) if date_node else ""
        match = re.search(r"(20\d{2})-(\d{2})-(\d{2})", published)
        # 市级列表标题带“[公开]”“[朝阳区]”前缀，剥到 region_hint 里，标题本体保留
        hint = re.match(r"^[\[［]([^\]］]{1,10})[\]］]\s*(.+)$", raw_title)
        items.append({
            "title": hint.group(2) if hint else raw_title,
            "title_prefix": hint.group(1) if hint else "",
            "url": urljoin(base, link["href"]),
            "published_at": f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else "",
            "channel": channel,
            "region_hint": hint.group(1) if hint else channel,
        })
    return items


def _beijing_products(soup: BeautifulSoup) -> list[str]:
    """四、主要标的信息表：供应商 | 商品名称 | 规格型号 | 数量 | 单价 | 总价 | 服务要求。"""
    out: list[str] = []
    for table in soup.select("table"):
        head = clean(table.get_text(" ", strip=True))[:80]
        if "商品名称" not in head:
            continue
        for tr in table.select("tr"):
            cells = [clean(td.get_text(" ", strip=True)) for td in tr.select("td,th")]
            cells = [c for c in cells if c]
            if len(cells) >= 3 and cells[1] and not re.search(r"商品名称|规格型号", cells[1]):
                if not re.fullmatch(r"[\d.]+", cells[1]):
                    out.append(cells[1])
    return list(dict.fromkeys(c for c in out if len(c) <= 40))


def _beijing_brands(soup: BeautifulSoup) -> list[str]:
    out: list[str] = []
    for table in soup.select("table"):
        if "规格型号" not in clean(table.get_text(" ", strip=True))[:80]:
            continue
        for tr in table.select("tr"):
            cells = [clean(td.get_text(" ", strip=True)) for td in tr.select("td,th")]
            cells = [c for c in cells if c]
            if len(cells) >= 3 and not re.fullmatch(r"[\d.]+", cells[2]) and len(cells[2]) <= 20:
                if not re.search(r"规格型号|品牌", cells[2]):
                    out.append(cells[2])
    return list(dict.fromkeys(out))


def parse_beijing_detail(html: str, url: str, fallback: dict | None = None) -> dict:
    fallback = fallback or {}
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one("div.BodyLabel") or soup.select_one("div.content") or soup
    text = node.get_text("\n", strip=True)

    suppliers = re.findall(r"中标成交供应商名称[：:]\s*([^\n]{2,60})", text)
    if not suppliers:
        suppliers = re.findall(r"中标（成交）供应商名称[：:]\s*([^\n]{2,60})", text)
    total_raw = amount_field(text, "总中标成交金额") or amount_field(text, r"中标（成交）金额")
    project = field(text, "项目名称")
    project = re.sub(r"(中标（成交）结果公告|中标结果公告|中标公告|成交公告|成交结果公告)$", "", clean(project)).strip()
    return {
        "公告标题": fallback.get("title", ""),
        "项目名称": project or fallback.get("title", ""),
        "项目编号": field(text, "项目编号", r"[A-Za-z0-9\-\[\]（）()．./]{4,60}"),
        "采购方式": field(text, "采购方式", r"[\u4e00-\u9fa5]{2,12}"),
        "预算金额（万元）": amount_wan(field(text, "预算金额")),
        "招标单位": field(text, r"采购人信息\s*名\s*称") or field(text, r"采购人\s*名\s*称"),
        "采购执行机构": field(text, r"采购代理机构信息\s*名\s*称") or field(text, r"代理机构\s*名\s*称"),
        "中标单位": "；".join(dict.fromkeys(clean(s) for s in suppliers if clean(s))),
        "中标金额原文": total_raw,
        "中标金额（万元）": amount_wan(total_raw),
        "产品": "、".join(_beijing_products(soup)[:4]),
        "品牌": "、".join(_beijing_brands(soup)[:4]),
        "公告链接": url,
        "公告日期": fallback.get("published_at", ""),
        "地域": "北京",
        "公告渠道": fallback.get("channel", ""),
        "区县": fallback.get("region_hint", ""),
    }


# ---------------------------------------------------------------- 雄安


def xiongan_list_url(page: int) -> str:
    return XIONGAN_FIRST if page == 1 else XIONGAN_PAGE.format(page=page)


def is_xiongan_result(url: str) -> bool:
    """jyxxzccj = 政府采购 中标/成交结果；jyxxzccg = 采购公告，不进结果表。"""
    return "/jyxxzccj/" in url


def parse_xiongan_list(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict] = []
    for link in soup.select("a[title]"):
        href = link.get("href") or ""
        title = clean(link.get("title") or link.get_text(" ", strip=True))
        if not href or not title:
            continue
        holder = link.find_parent("li") or link.parent
        block = clean(holder.get_text(" ", strip=True)) if holder else ""
        match = re.search(r"(20\d{2})-(\d{2})-(\d{2})", block)
        prefix = re.match(r"^【([^】]{2,20})】\s*(.+)$", title)
        items.append({
            "title": prefix.group(2) if prefix else title,
            "title_prefix": prefix.group(1) if prefix else "",
            "url": href,
            "published_at": f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else "",
            "channel": "雄安新区公共资源交易服务平台",
            "region_hint": prefix.group(1) if prefix else "",
        })
    return items


def parse_xiongan_detail(html: str, url: str, fallback: dict | None = None) -> dict:
    """雄安详情页只是壳：取“公告来源”指向的河北政采文章地址，正文在那边。"""
    fallback = fallback or {}
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    source = ""
    match = re.search(r"公告来源[：:]\s*(https?://\S+)", text)
    if match:
        source = match.group(1).strip()
    if not source:
        match = re.search(r"https?://www\.ccgp-hebei\.gov\.cn/[^\s\"'<>]+\.html", html)
        source = match.group(0) if match else ""
    return {
        "公告标题": fallback.get("title", ""),
        "公告日期": fallback.get("published_at", ""),
        "公告链接": url,
        "公告来源": source.replace("http://", "https://") if source else "",
        "区县": fallback.get("region_hint", ""),
        "地域": "雄安新区",
    }


def yuan_amount(text: str) -> float | None:
    """河北政采的 gpbudgetamt 只给数字（单位元），没有“元/万元”字样。"""
    body = clean(text).replace(",", "").replace("，", "")
    if not body:
        return None
    if re.search(r"万元|亿元|元", body):
        return amount_wan(body)
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", body):
        return round(float(body) / 10000, 4)
    return amount_wan(body)


def js_string(html: str, key: str) -> str:
    """河北政采正文由内嵌 JS 模板变量渲染，形如 PROJECTNAME: `xxx`。"""
    for match in re.finditer(rf"\b{key}\s*:\s*`([^`]*)`", html):
        value = clean(match.group(1))
        if value:
            return value
    return ""


def parse_hebei_packed(packed: str) -> tuple[list[str], list[float], list[str]]:
    """河北政采把结果明细压成 `#_@_@` 分隔串：A 段依次是 信用代码/供应商/地址/标的/…/金额（元）。"""
    parts = [p.strip() for p in (packed or "").split("#_@_@")]
    suppliers: list[str] = []
    amounts: list[float] = []
    products: list[str] = []
    index = 0
    while index < len(parts):
        if parts[index] == "A":
            block = parts[index + 1:index + 10]
            if len(block) >= 2 and block[1]:
                suppliers.append(block[1])
            if len(block) >= 4 and block[3]:
                products.append(block[3])
            number = next((b for b in block[1:] if re.fullmatch(r"\d+(?:\.\d+)?", b) and len(b) >= 4
                           and b != (block[0] if block else "")), "")
            if number:
                amounts.append(float(number))
            index += 10
            continue
        index += 1
    return list(dict.fromkeys(suppliers)), amounts, list(dict.fromkeys(products))


def parse_hebei_article(html: str, url: str, fallback: dict | None = None) -> dict:
    """河北政采文章页版式（内嵌 JS 变量 + `#_@_@` 打包串）。

    当前链路不再直接取它（该站 robots.txt 返回 403，按 fail-closed 不取），
    保留解析器是为了它恢复可访问时能直接接回，也由离线测试覆盖。
    """
    fallback = fallback or {}
    project = js_string(html, "PROJECTNAME") or js_string(html, "projectname")
    buyer = js_string(html, "PurchaserName") or js_string(html, "PurchaserName2020")
    code = js_string(html, "PROJECTCODE") or js_string(html, "PROJECTCODE")
    title = js_string(html, "DOCTITLE") or js_string(html, "docTitle")
    budget = yuan_amount(js_string(html, "gpbudgetamt") or js_string(html, "limitedprice"))
    suppliers, amounts, products = parse_hebei_packed(js_string(html, "content"))
    total = round(sum(amounts) / 10000, 4) if amounts else None
    return {
        "公告标题": fallback.get("title") or title,
        "项目名称": project or fallback.get("title", ""),
        "项目编号": code,
        "采购方式": js_string(html, "PURCHASEWAY"),
        "预算金额（万元）": budget,
        "招标单位": buyer,
        "采购执行机构": js_string(html, "AGENCYFULLNAME"),
        "中标单位": "；".join(suppliers),
        "中标金额原文": "、".join(f"{a:g}元" for a in amounts),
        "中标金额（万元）": total,
        "产品": "、".join(products[:4]),
        "品牌": "",
        "公告链接": fallback.get("url", ""),
        "公告来源": url,
        "公告日期": fallback.get("published_at", ""),
        "地域": "雄安新区",
        "区县": fallback.get("region_hint", ""),
    }



# ---------------------------------------------------------------- 补窗与正文（中国政府采购网）


def ccgp_search_url(page: int, kw: str, start: str, end: str, zone: str = "") -> str:
    """search.ccgp.gov.cn 检索页：kw 控标题命中，timeType=6 走起止日期，zoneId 控地域。"""
    params = {
        "searchtype": "1", "page_index": str(page), "bidSort": "0", "buyerName": "",
        "projectId": "", "pinMu": "0", "bidType": "0", "dbselect": "bidx", "kw": kw,
        "start_time": start.replace("-", ":"), "end_time": end.replace("-", ":"),
        "timeType": "6", "pppStatus": "0",
    }
    if zone:
        params["zoneId"] = zone
    return f"{CCGP_SEARCH}?{urlencode(params)}"


def _tables_with(soup: BeautifulSoup, words: tuple[str, ...]):
    for table in soup.select("table"):
        body = clean(table.get_text(" ", strip=True))
        if all(word in body for word in words):
            yield table


def _column_values(soup: BeautifulSoup, header_words: tuple[str, ...], column_word: str) -> list[str]:
    """按表头名定位列，取该列非空值。

    地方公告的标的信息表常在表头上方多一行“服务类/货物类”，所以不能假定第一行就是表头，
    要在前几行里找真正含该列名的那一行。
    """
    values: list[str] = []
    for table in _tables_with(soup, header_words):
        rows = [[clean(td.get_text(" ", strip=True)) for td in tr.select("td,th")] for tr in table.select("tr")]
        rows = [row for row in rows if any(row)]
        header_at = next((i for i, row in enumerate(rows[:4]) if column_word in row), None)
        if header_at is None:
            continue
        header = rows[header_at]
        index = header.index(column_word)
        for row in rows[header_at + 1:]:
            if index < len(row) and row[index] and row[index] != column_word:
                values.append(row[index])
    return list(dict.fromkeys(values))


def parse_ccgp_local_detail(html: str, url: str, fallback: dict | None = None) -> dict:
    """地方公告（河北/北京 dfgg）版式：供应商与中标金额都在横表里，没有冒号标签。"""
    fallback = fallback or {}
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one("div.vF_detail_content") or soup
    text = node.get_text("\n", strip=True)

    suppliers = _column_values(soup, ("供应商名称", "供应商地址"), "供应商名称")
    amount_cells = _column_values(soup, ("中标金额",), "中标金额")
    amounts: list[float] = []
    for cell in amount_cells:
        if re.search(r"万元", cell):
            value = amount_wan(cell)
        elif re.search(r"亿元", cell):
            value = amount_wan(cell)
        else:
            value = yuan_amount(cell)
        if value:
            amounts.append(value)
    total = round(sum(amounts), 4) if amounts else None
    if total is None:
        raw = amount_field(text, "(?:中标（成交）金额|中标金额|成交金额|成交价)")
        total = amount_wan(raw)

    project = field(text, "项目名称")
    project = re.sub(r"(中标（成交）结果公告|中标结果公告|中标公告|成交结果公告|成交公告)$", "", clean(project)).strip()
    return {
        "公告标题": fallback.get("title", ""),
        "项目名称": project or fallback.get("title", ""),
        "项目编号": field(text, "项目编号", r"[A-Za-z0-9\-\[\]（）()．./]{4,60}"),
        "采购方式": field(text, "采购方式", r"[\u4e00-\u9fa5]{2,12}"),
        "预算金额（万元）": amount_wan(field(text, "预算金额")),
        "招标单位": field(text, r"采购人信息\s*名?\s*称") or field(text, r"采购人\s*名?\s*称"),
        "采购执行机构": field(text, r"采购代理机构信息[^\n]{0,12}\s*名?\s*称"),
        "中标单位": "；".join(suppliers),
        "中标金额原文": "、".join(f"{a:g}万元" for a in amounts),
        "中标金额（万元）": total,
        "产品": "、".join((_column_values(soup, ("供应商名称", "服务名称"), "服务名称")
                          or _column_values(soup, ("供应商名称", "货物名称"), "货物名称")
                          or _column_values(soup, ("供应商名称", "标的名称"), "标的名称"))[:4]),
        "品牌": "、".join(_column_values(soup, ("供应商名称", "品牌"), "品牌")[:4]),
        "公告链接": url,
        "公告日期": fallback.get("published_at", ""),
        "地域": fallback.get("region", ""),
        "公告渠道": "中国政府采购网",
        "区县": fallback.get("region_hint", ""),
    }


def collect_ccgp_supplement(runner: "Runner", region: str, start: str, end: str, keywords: list[str],
                            zone: str, max_pages: int, path_filter: str = "",
                            title_must: str = "", allow_regions: list[str] | None = None,
                            offline: bool = False) -> tuple[list[dict], dict]:
    """按月切窗检索，补平台列表够不到的那几个月。

    只收 /zbgg/（中标）与 /cjgg/（成交）结果公告；path_filter="/dfgg/" 时只收地方公告，
    避免把中央单位的项目混进北京口径（那批属于央采，另有一条链路）。
    allow_regions 按检索结果行的地域标签再筛一道，只保留本地公告。
    """
    windows = month_windows(start, end)
    notices: list[dict] = []
    seen: set[str] = set()
    stats = {"windows": len(windows), "keywords": keywords, "pages": 0, "stopped": [], "off_region": 0}
    for w_start, w_end in windows:
        for kw in keywords:
            for page in range(1, max_pages + 1):
                url = ccgp_search_url(page, kw, w_start, w_end, zone)
                html = runner.get(url, CCGP_DOMAINS, f"ccgp-{region}-{kw}-{w_start}-{page:02d}", offline)
                if html is None:
                    stats["stopped"].append(f"{w_start}~{w_end} {kw} 第{page}页")
                    break
                stats["pages"] += 1
                items = parse_search_page(html)
                if not items:
                    break
                fresh = 0
                for item in items:
                    link = item["url"]
                    if "/zbgg/" not in link and "/cjgg/" not in link:
                        continue
                    if path_filter and path_filter not in link:
                        continue
                    # 地域标签先判：检索是全文命中，正文提到地名≠本地项目。
                    # 标签为空表示该行没解析出地域，交给后面的标题地名判定，不能当外地丢掉。
                    if allow_regions and item["region"] and item["region"] not in allow_regions:
                        stats["off_region"] += 1
                        continue
                    if title_must and not re.search(title_must, _plain(item["title"])):
                        continue
                    if link in seen:
                        continue
                    seen.add(link)
                    fresh += 1
                    notices.append({
                        "title": item["title"], "url": link,
                        "published_at": item["published_at"], "channel": "中国政府采购网（补窗）",
                        "region_hint": region, "region_label": item["region"],
                    })
                if fresh == 0:
                    break
    runner.log(f"[{region}-补窗] {len(windows)} 个窗口 × {len(keywords)} 个词，取页 {stats['pages']}，"
               f"结果类 {len(notices)} 条，地域不符剔除 {stats['off_region']} 条")
    return notices, stats


# ---------------------------------------------------------------- 采集


class Runner:
    """统一负责取页、落缓存、记失败；被站点拒绝就停下，不重试、不绕过。"""

    def __init__(self, out_dir: Path, delay: float, timeout: int):
        self.dir = out_dir
        self.cache = out_dir / "cache"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.fetcher = Fetcher(timeout=timeout, retries=1, delay=delay)
        self.logs: list[str] = []
        self.failures: list[dict] = []

    def log(self, message: str) -> None:
        print(message, flush=True)
        self.logs.append(message)

    def get(self, url: str, domains: list[str], tag: str, offline: bool = False) -> str | None:
        path = self.cache / cache_name(tag, url)
        raw = read_cache(path)
        if raw is not None:
            return decode_html(raw)
        if offline:
            return None
        result = self.fetcher.fetch(url, domains)
        if result["status"] != "ok":
            self.failures.append({"stage": tag, "code": result["status"], "url": url,
                                  "reason": result.get("error", "")})
            self.log(f"[{tag}] 失败 {result['status']} {url[:90]} {result.get('error','')[:60]}")
            return None
        body = result.get("raw") or b""
        if body:
            path.write_bytes(body)
        return page_html(result)

    def close(self) -> None:
        self.fetcher.close()


def collect_beijing(runner: Runner, start: str, end: str, max_pages: int, limit: int | None,
                    dry_run: bool, offline: bool, supplement: bool = True,
                    supp_pages: int = 20) -> tuple[list[dict], dict]:
    notices: list[dict] = []
    seen: set[str] = set()
    stats = {"channels": {}, "stopped": [], "platform_oldest": ""}
    for channel, tag, template in BEIJING_CHANNELS:
        fetched = 0
        oldest = ""
        for page in range(1, max_pages + 1):
            html = runner.get(beijing_list_url(template, page), BEIJING_DOMAINS,
                              f"bj-{tag}-{page:03d}", offline)
            if html is None:
                stats["stopped"].append(f"{channel} 第{page}页")
                break
            items = parse_beijing_list(html, channel)
            if not items:
                break
            fetched += 1
            dates = [i["published_at"] for i in items if i["published_at"]]
            oldest = min(dates) if dates else oldest
            fresh = 0
            for item in items:
                if item["url"] in seen:
                    continue
                seen.add(item["url"])
                fresh += 1
                notices.append(item)
            runner.log(f"[北京-{channel}] 第{page}页 {len(items)} 条，新增 {fresh}，最早 {oldest}")
            if dates and max(dates) < start:
                break
            if fresh == 0:
                break
        stats["channels"][channel] = {"pages": fetched, "oldest": oldest}
        stats["platform_oldest"] = min([stats["platform_oldest"]] + [oldest]) if stats["platform_oldest"] else oldest

    window = [n for n in notices if (not n["published_at"] or start <= n["published_at"] <= end)]
    runner.log(f"[北京] 平台列表 {len(notices)} 条，窗口内 {len(window)} 条，最早 {stats['platform_oldest'] or '-'}")

    # 平台列表只有 143 页（约 2026-07 起），更早月份用检索站按月补；补窗可能重复，靠标题去重。
    # 离线重出表时同样走补窗，缓存里有的页面照样复用，缺页只记 stopped、不补请求。
    if supplement and stats["platform_oldest"] and stats["platform_oldest"] > start:
        sup, sup_stats = collect_ccgp_supplement(runner, "北京", start, stats["platform_oldest"],
                                                 ["中标", "成交"], BEIJING_ZONE, supp_pages, "/dfgg/",
                                                 "", ["北京"], offline)
        stats["supplement"] = sup_stats
        known = {n["url"] for n in window}
        extra = [n for n in sup if n["url"] not in known]
        window.extend(extra)
        runner.log(f"[北京] 补窗追加 {len(extra)} 条，合计候选池 {len(window)} 条")

    kept, review = _filter_and_fetch(runner, window, limit, dry_run, "bj", offline)
    stats["excluded"] = review
    return kept, stats


def collect_xiongan(runner: Runner, start: str, end: str, max_pages: int, limit: int | None,
                    dry_run: bool, offline: bool, supplement: bool = True,
                    supp_pages: int = 20) -> tuple[list[dict], dict]:
    notices: list[dict] = []
    seen: set[str] = set()
    stats = {"pages": 0, "oldest": ""}
    for page in range(1, max_pages + 1):
        html = runner.get(xiongan_list_url(page), XIONGAN_DOMAINS, f"xa-list-{page:04d}", offline)
        if html is None:
            stats["stopped_at"] = page
            break
        items = parse_xiongan_list(html)
        if not items:
            stats["stopped_at"] = page
            runner.log(f"[雄安] 第{page}页为空页，站点列表深度到顶（{stats['pages']} 页）")
            break
        stats["pages"] = page
        dates = [i["published_at"] for i in items if i["published_at"]]
        stats["oldest"] = min(dates + [stats["oldest"] or "9999-99-99"]) if dates else stats["oldest"]
        fresh = 0
        for item in items:
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            fresh += 1
            notices.append(item)
        runner.log(f"[雄安] 第{page}页 {len(items)} 条，新增 {fresh}，最早 {stats['oldest']}")
        if dates and max(dates) < start:
            break
        if fresh == 0:
            break
    results = [n for n in notices if is_xiongan_result(n["url"])]
    stats["result_notices"] = len(results)
    if stats["oldest"] == "9999-99-99":
        stats["oldest"] = ""
    runner.log(f"[雄安] 列表 {len(notices)} 条，结果类（/jyxxzccj/）{len(results)} 条，最早 {stats['oldest'] or '-'}")

    window = [n for n in results if (not n["published_at"] or start <= n["published_at"] <= end)]
    if supplement and stats["oldest"] and stats["oldest"] > start:
        sup, sup_stats = collect_ccgp_supplement(runner, "雄安", start, stats["oldest"],
                                                 ["雄安", "容城", "安新", "雄县"], "", supp_pages, "",
                                                 XIONGAN_LOCAL_RE, ["河北", "北京", "雄安", "雄安新区"],
                                                 offline)
        stats["supplement"] = sup_stats
        known = {n["url"] for n in window}
        extra = [n for n in sup if n["url"] not in known]
        window.extend(extra)
        runner.log(f"[雄安] 补窗追加 {len(extra)} 条，合计候选池 {len(window)} 条")

    kept, review = _filter_and_fetch(runner, window, limit, dry_run, "xa", offline)
    stats["excluded"] = review
    return kept, stats


def _normalize_title(text: str) -> str:
    body = re.sub(r"[\s　（）()【】\[\]“”\"'、，,。.：:；;]", "", clean(text))
    return re.sub(r"(中标成交结果公告|中标结果公告|中标公告|成交结果公告|成交公告|结果公告)$", "", body)


def find_ccgp_by_title(runner: Runner, title: str, published_at: str, offline: bool = False) -> str:
    """雄安平台详情是壳、河北政采 robots 403，按标题到检索站反查同一公告的 ccgp 页。"""
    core = re.sub(r"[（(][^）)]{0,12}[）)]", "", title)
    core = core[:24] or title[:24]
    window_start = published_at or ""
    window_end = published_at or ""
    if published_at:
        day = datetime.strptime(published_at, "%Y-%m-%d").date()
        window_start = day.replace(day=max(1, day.day - 10)).isoformat()
        window_end = day.replace(day=min(28, day.day + 3)).isoformat()
    for page in (1, 2):
        url = ccgp_search_url(page, core, window_start or "2026-01-01", window_end or "2026-12-31")
        html = runner.get(url, CCGP_DOMAINS, f"ccgp-lookup-{page:02d}", offline)
        if not html:
            return ""
        for item in parse_search_page(html):
            link = item["url"]
            if "/zbgg/" not in link and "/cjgg/" not in link:
                continue
            if _normalize_title(core) in _normalize_title(item["title"]):
                return link
    return ""


def _detail_for(runner: Runner, notice: dict, region: str, offline: bool = False) -> dict:
    url = notice["url"]
    if "ccgp.gov.cn" in url:
        html = runner.get(url, CCGP_DOMAINS, "ccgp-detail", offline)
        return parse_ccgp_local_detail(html, url, {**notice, "region": "北京" if region == "bj" else "雄安新区"}) if html else {}
    if region == "bj":
        html = runner.get(url, BEIJING_DOMAINS, "bj-detail", offline)
        return parse_beijing_detail(html, url, notice) if html else {}
    shell = runner.get(url, XIONGAN_DOMAINS, "xa-detail", offline)
    if not shell:
        return {}
    detail = parse_xiongan_detail(shell, url, notice)
    source = detail.get("公告来源", "")
    if source and "ccgp-hebei.gov.cn" in source:
        # 河北政采 robots.txt 403（fail-closed，不取正文）；改用它自己在检索站的镜像
        mirror = find_ccgp_by_title(runner, notice["title"], notice.get("published_at", ""), offline)
        if mirror:
            html = runner.get(mirror, CCGP_DOMAINS, "ccgp-detail", offline)
            if html:
                parsed = parse_ccgp_local_detail(html, mirror, notice)
                parsed["公告来源"] = source
                return parsed
    return detail


def region_guard(region: str, notice: dict) -> tuple[bool, str]:
    """地域硬校验：平台自身的公告按域名放行，补窗公告要地域标签或标题地名兜底。

    没有这一道，检索站会把云南“镇雄县”的中标公告塞进雄安表（金额还都是 None）。
    """
    url = notice.get("url", "")
    text = _plain(f"{notice.get('title', '')} {notice.get('region_hint', '')}")
    label = notice.get("region_label", "")
    if region == "xa":
        if any(domain in url for domain in XIONGAN_DOMAINS):
            return True, ""
        # 河北是雄安的上级口径，标签对上还要标题自带本地地名（避免石家庄等地市混入）
        if label and label not in XIONGAN_REGION_LABELS:
            return False, f"非雄安本地公告（{label}）"
        if re.search(XIONGAN_LOCAL_RE, text):
            return True, ""
        return False, f"非雄安本地公告（{label or '无地域标签'}）"
    if any(domain in url for domain in BEIJING_DOMAINS):
        return True, ""
    # 检索结果行的地域标签比标题可靠：“辽宁省朝阳市”也带“朝阳”二字
    if label:
        return (True, "") if label == "北京" else (False, f"非北京本地公告（{label}）")
    if re.search(BEIJING_LOCAL_RE, text):
        return True, ""
    return False, "非北京本地公告（无地域标签）"


def _filter_and_fetch(runner: Runner, notices: list[dict], limit: int | None, dry_run: bool,
                      region: str, offline: bool = False) -> tuple[list[dict], list[dict]]:
    kept, review = [], []
    off_region = 0
    for notice in notices:
        in_region, region_reason = region_guard(region, notice)
        if not in_region:
            off_region += 1
            review.append({**notice, "scope_reason": region_reason})
            continue
        ok, reason = classify_scope(notice["title"], notice.get("region_hint", ""))
        (kept if ok else review).append({**notice, "scope_reason": reason})
    runner.log(f"[{region}] 医卫数字化候选 {len(kept)} 条，排除 {len(review)} 条"
               f"（地域不符 {off_region} 条）")
    if limit:
        kept = kept[:limit]

    records: list[dict] = []
    seen_keys: set[str] = set()
    for index, notice in enumerate(kept, 1):
        if dry_run:
            records.append({"notice": notice, "detail": {}, "row": {}})
            continue
        detail = _detail_for(runner, notice, region, offline)
        if not detail:
            continue
        row = build_row(detail)
        if not clean(row["项目名称"]):
            runner.log(f"[{region}] 跳过无项目名记录：{notice['url'][:70]}")
            continue
        key = _normalize_title(row["项目名称"])[:40]
        if key in seen_keys:
            runner.log(f"[{region}] 跳过重复：{row['项目名称'][:26]}")
            continue
        seen_keys.add(key)
        records.append({"row": row, "detail": detail, "notice": notice})
        runner.log(f"[{region}] {index}/{len(kept)} {row['项目名称'][:26]} | "
                   f"{row['中标金额（万元）']} 万元 | {row['场景']}")
    return records, review

def _summarize(records: list[dict]) -> dict:
    rows = [r.get("row") or {} for r in records]
    amounts = [r.get("中标金额（万元）") for r in rows if isinstance(r.get("中标金额（万元）"), (int, float))]
    boundary = collections.Counter(hint for hint in
                                   (boundary_hint(r.get("项目名称", "")) for r in rows) if hint)
    boundary_amount = [r.get("中标金额（万元）") for r in rows
                       if boundary_hint(r.get("项目名称", "")) and
                       isinstance(r.get("中标金额（万元）"), (int, float))]
    total = round(sum(amounts), 2)
    return {
        "records": len(rows),
        "amount_wan": total,
        "missing_amount": sum(1 for r in rows if r.get("中标金额（万元）") in (None, "")),
        "missing_supplier": sum(1 for r in rows if not r.get("中标单位")),
        # 口径边界（设备维保/设备购置/后勤设施/检验委外）：先标出来，不擅自改共享口径
        "boundary_hits": sum(boundary.values()),
        "boundary_detail": dict(boundary),
        "boundary_amount_wan": round(sum(boundary_amount), 2),
        "amount_wan_ex_boundary": round(total - sum(boundary_amount), 2),
    }


def write_boundary_review(records: list[dict], path: Path) -> int:
    """把落在口径边界上的记录单列一份，供人工决定是否剔除。"""
    rows = []
    for record in records:
        row = record.get("row") or {}
        hint = boundary_hint(row.get("项目名称", ""))
        if not hint:
            continue
        rows.append({
            "边界类别": hint,
            "项目名称": row.get("项目名称", ""),
            "招标单位": row.get("招标单位", ""),
            "中标单位": row.get("中标单位", ""),
            "中标金额（万元）": row.get("中标金额（万元）"),
            "公告链接": (record.get("detail") or {}).get("公告链接", ""),
        })
    write_csv(rows, path, ["边界类别", "项目名称", "招标单位", "中标单位", "中标金额（万元）", "公告链接"])
    return len(rows)


def collect(start: str, end: str, out_dir: Path, regions: list[str], max_pages_bj: int,
            max_pages_xa: int, delay: float, timeout: int, limit: int | None, dry_run: bool,
            offline: bool = False, supplement: bool = True, supp_pages: int = 20) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    runner = Runner(out_dir, delay, timeout)
    payload: dict = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "window": {"start": start, "end": end},
        "sources": {
            "北京": "北京市政府采购网 市级/区级「中标公告」静态列表（列表只保留 143 页，第 144 页 404）",
            "雄安": "雄安新区公共资源交易服务平台 政府采购 channelId=273 → 结果类 /jyxxzccj/ → 正文取河北省政府采购网",
        },
    }
    try:
        if "bj" in regions:
            records, stats = collect_beijing(runner, start, end, max_pages_bj, limit, dry_run,
                                             offline, supplement, supp_pages)
            summary = _summarize(records)
            summary["channels"] = stats["channels"]
            summary["stopped"] = stats["stopped"]
            summary["supplement"] = stats.get("supplement")
            payload["beijing"] = {"summary": summary, "records": records,
                                  "excluded": stats.get("excluded", [])}
            if not dry_run:
                write_bid_workbook(records, out_dir / "北京", "北京医卫数字化中标_2026",
                                   "北京医卫数字化中标", BEIJING_DETAIL_COLUMNS)
                written = write_boundary_review(records, out_dir / "北京" / "口径边界复核.csv")
                summary["boundary_csv"] = f"北京/口径边界复核.csv（{written} 条）"
        if "xa" in regions:
            records, stats = collect_xiongan(runner, start, end, max_pages_xa, limit, dry_run,
                                             offline, supplement, supp_pages)
            summary = _summarize(records)
            excluded = stats.pop("excluded", [])
            summary.update(stats)
            summary["supplement"] = stats.get("supplement")
            payload["xiongan"] = {"summary": summary, "records": records, "excluded": excluded}
            if not dry_run:
                write_bid_workbook(records, out_dir / "雄安", "雄安医卫数字化中标_2026",
                                   "雄安医卫数字化中标", XIONGAN_DETAIL_COLUMNS)
                written = write_boundary_review(records, out_dir / "雄安" / "口径边界复核.csv")
                summary["boundary_csv"] = f"雄安/口径边界复核.csv（{written} 条）"
    finally:
        runner.close()

    payload["failures"] = runner.failures
    payload["log"] = runner.logs
    write_json(out_dir / "bjxa_medical_bid.json", payload)

    for key in ("beijing", "xiongan"):
        part = payload.get(key)
        if part:
            s = part["summary"]
            print(f"{key}: {s['records']} 条，{s['amount_wan']} 万元，缺金额 {s['missing_amount']}，"
                  f"缺中标单位 {s['missing_supplier']}，口径边界 {s.get('boundary_hits', 0)} 条"
                  f"/{s.get('boundary_amount_wan', 0)} 万元（剔除后 {s.get('amount_wan_ex_boundary', 0)} 万元）")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="北京、雄安医卫数字化中标采集")
    parser.add_argument("--start", default="2026-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--output", default="outputs/bjxa-medical-2026")
    parser.add_argument("--region", default="bj,xa", help="bj / xa / all")
    parser.add_argument("--max-pages-bj", type=int, default=143, help="北京单频道翻页上限（站点上限 143）")
    parser.add_argument("--max-pages-xa", type=int, default=400, help="雄安列表翻页上限")
    parser.add_argument("--delay", type=float, default=2.5)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="只跑列表与过滤，不取详情")
    parser.add_argument("--from-cache", action="store_true", help="只用已落盘缓存重出表，不请求站点")
    parser.add_argument("--no-supplement", action="store_true", help="不跑 ccgp 按月补窗，只用平台列表")
    parser.add_argument("--supp-pages", type=int, default=20, help="补窗时每个词每月最多翻几页")
    args = parser.parse_args(argv)
    regions = ["bj", "xa"] if args.region == "all" else [r.strip() for r in args.region.split(",") if r.strip()]
    return collect(args.start, args.end, Path(args.output), regions, args.max_pages_bj,
                   args.max_pages_xa, args.delay, args.timeout, args.limit, args.dry_run,
                   args.from_cache, not args.no_supplement, args.supp_pages)


if __name__ == "__main__":
    sys.exit(main())
