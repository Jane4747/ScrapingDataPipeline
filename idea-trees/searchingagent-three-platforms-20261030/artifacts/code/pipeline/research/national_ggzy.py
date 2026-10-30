"""Bounded/resumable GGZY browser collector; reuses local Playwright and bid parsers.

Normal public search forms only. Stops on CAPTCHA/rate limiting. Original JSON,
HTML, failures and coverage stay on disk. Spreadsheet authoring is a separate step.
"""
from __future__ import annotations

import argparse
import asyncio
import calendar
import csv
import hashlib
import json
import os
import re
import sys
import time
import truststore
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from pipeline.research.bid_common import amount_wan, carrier_type, customer_tag, scene_of, STAGE_WORDS
from pipeline.research.zycg import parse_detail as common_detail
from pipeline.research.tender_fields import add_fields
from scripts.thirdparty_goverment_spider.site_fetch import fetch as fetch_text

BASE = "https://www.ggzy.gov.cn"
PARSER_VERSION = 7
COLS = ["项目名称", "产品", "招标单位", "客户标签", "中标单位", "运营商类型", "中标金额（万元）", "场景", "相关网页", "公告类型", "公告日期", "省份", "项目编号", "中标金额原文", "信息缺口", "标签依据"]
HEALTH = re.compile(r"医院|医疗|卫生|疾控|妇幼|医保|医学|血站|血液中心|急救中心|保健院|社区卫生|中医|康复中心")
STRONG = re.compile(r"信息化|智能化|弱电|综合布线|信息系统|信息平台|信息管理|信息服务|信息安全|数字化|数智|智慧|软件|数据库|数据治理|大数据|数据平台|数据集成|服务器|云计算|云平台|云服务|算力|超融合|虚拟化|机房|数据中心|网络|专线|交换机|路由器|防火墙|等保|密码测评|商用密码|存储|备份|容灾|HIS\b|PACS\b|LIS\b|EMR\b|DRG\b|DIP\b|电子病历|电子健康|电子档案|病案|电子签名|互联网医院|互联网诊疗|远程医疗|远程会诊|人工智能|大模型|智能辅助诊断|计算机|自助服务|叫号|排队|电子票据", re.I)
PHYSICAL = re.compile(r"空调|暖通|内窥镜|内镜|手术机器人|超声|CT扫描|断层扫描|发射计算机|X射线|X线|数字减影|核磁|磁共振|手术床|监护仪|消毒|试剂|耗材|药品采购|电梯|污水|医用气体|物业|食堂|保洁|安保|医疗废物")
SOFTWARE = re.compile(r"信息化|智能化|弱电|综合布线|软件|信息系统|信息平台|数据|PACS|HIS|LIS|EMR|电子病历|电子票据|智能辅助|网络|服务器|存储|机房|算力|数据库", re.I)


def now():
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def months(start, end):
    current, end = date.fromisoformat(start), date.fromisoformat(end)
    while current <= end:
        last = min(end, date(current.year, current.month, calendar.monthrange(current.year, current.month)[1]))
        yield current.isoformat(), last.isoformat()
        current = last + timedelta(days=1)


def split_window(start, end):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first >= last:
        return []
    mid = first + timedelta(days=(last-first).days // 2)
    return [(first.isoformat(), mid.isoformat()), ((mid+timedelta(days=1)).isoformat(), last.isoformat())]


def archive_windows(start, end):
    """The official UI separates one-year-old records at the /his endpoint."""
    boundary = date.today() - timedelta(days=366)
    for first, last in months(start, end):
        a, b = date.fromisoformat(first), date.fromisoformat(last)
        if a <= boundary < b:
            yield first, boundary.isoformat(), "history"
            yield (boundary + timedelta(days=1)).isoformat(), last, "current"
        else:
            yield first, last, "history" if b <= boundary else "current"


def timeout_parts(task, error):
    if not re.search(r"AbortError|Timeout|timed out|timeout", str(error), re.I):
        return []
    return split_window(task["start"], task["end"])


def in_scope(title):
    title = BeautifulSoup(title or "", "html.parser").get_text("", strip=True) if "<" in (title or "") else title or ""
    if not HEALTH.search(title) or not STRONG.search(title):
        return False
    if PHYSICAL.search(title) and not SOFTWARE.search(title):
        return False
    if re.search(r"土建|土方|主体工程|结构工程|门诊楼建设|病房楼建设|建筑施工|医院.*施工总承包",title) and not SOFTWARE.search(title):
        return False
    return True


def plain(value):
    return re.sub(r"\s+", " ", value or "").strip()


def label_value(text, labels, limit=120):
    for label in labels:
        pattern = rf"(?:{label})\s*[：:]\s*([^\n]{{2,{limit}}})"
        match = re.search(pattern, text, re.I)
        if match:
            value = plain(match.group(1))
            value = re.split(r"(?:地址|联系方式|联系电话|联系人|统一社会信用代码|中标金额|成交金额)\s*[：:]", value)[0]
            return value.strip("；; ")
    return ""


def classify_scene(title, products):
    patterns = [("云与算力", r"云计算|云平台|云服务|云存储|云桌面|云资源|云租赁|算力|虚拟化|超融合|GPU|服务器|资源池")]+STAGE_WORDS[1:]
    for text in (title, products):
        for name, pattern in patterns:
            if re.search(pattern,text or "",re.I):return name
    return "信息化建设" if "信息化" in title else "其他数字化"


def carrier_label(supplier):
    labels=[]
    for name in re.split(r"[；;\n]",supplier or ""):
        if name.strip():
            labels.append("中国电信" if re.search(r"中国电信|中电信|天翼",name) else carrier_type(name))
    return "；".join(dict.fromkeys(labels))


def clean_product(value, parties=()):
    value=plain(value)
    if not value or len(value)>500 or value in parties:
        return ""
    if re.search(r"代理服务收费|公告期限|采购人信息|联系方式|项目联系人|采购代理机构",value):
        return ""
    if re.fullmatch(r"品目号|采购标的|标项名称|序号|名称|供应商(?:名称)?|数量|货物类|服务类|类型|包号|服务范围|主要标的名称|标的名称|[A-Za-z\d]+(?:[-—]\d+)?",value):
        return ""
    return value


def extract_tables(content):
    awards, products = [], []
    for table in content.find_all("table"):
        # A page may be wrapped in a layout table. Never interpret nested rows
        # using the outer table's unrelated supplier/product column positions.
        rows=[]
        for tr in table.find_all("tr"):
            if tr.find_parent("table") is not table:continue
            cells=tr.find_all(["td","th"],recursive=False)
            if not cells or any(c.find("table") for c in cells):continue
            rows.append([plain(c.get_text(" ",strip=True)) for c in cells])
        for i, headers in enumerate(rows[:4]):
            if not headers:continue
            normalized = [re.sub(r"\s+","",x) for x in headers]
            supplier_idx = next((j for j,x in enumerate(normalized) if re.search(r"供应商名称|中标人名称|中标单位|成交人名称",x)),None)
            amount_idx = next((j for j,x in enumerate(normalized) if re.search(r"(?:中标|成交).*(?:金额|总价)",x) and "单价" not in x),None)
            if supplier_idx is not None and amount_idx is not None:
                unit_match = re.search(r"亿元|万元|元",normalized[amount_idx])
                for row in rows[i+1:]:
                    if len(row)<=max(supplier_idx,amount_idx):continue
                    supplier = row[supplier_idx]
                    raw = re.sub(r"[\s（）()]","",row[amount_idx])
                    if not supplier or re.search(r"供应商名称|中标供应商地址",supplier):continue
                    if re.search(r"%|折扣|费率|单价",raw):value=None
                    else:
                        if not re.search(r"亿元|万元|元",raw) and unit_match:raw+=unit_match.group()
                        value=amount_wan(raw)
                    awards.append({"supplier":supplier,"amount_raw":raw,"amount_wan":value})
                break
            preferred = [j for j,x in enumerate(normalized) if re.search(r"标的名称|货物名称|服务名称|产品名称",x)]
            if not preferred and any(re.search(r"品牌|规格|型号|数量",x) for x in normalized):
                preferred = [j for j,x in enumerate(normalized) if x=="名称"]
            if preferred:
                j=preferred[0]
                products.extend(clean_product(row[j]) for row in rows[i+1:] if len(row)>j and row[j] and row[j] not in headers)
                break
        if rows and any("服务类" in x or "货物类" in x for x in rows[0]):
            value=label_value(table.get_text("\n",strip=True),["名称","标的名称","服务名称"],300)
            if value:products.append(clean_product(value))
    return awards,list(dict.fromkeys(x for x in products if x))


def parse_article(html, notice):
    """Reuse existing detail/table parser; keep missing facts blank, never use budget as award."""
    url = urljoin(BASE, notice.get("url", ""))
    title = notice.get("title", "")
    if "<" in title:title=BeautifulSoup(title,"html.parser").get_text("",strip=True)
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    content = soup.select_one("#mycontent") or soup.select_one(".detail_content") or soup
    text = content.get_text("\n", strip=True)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    parsed = common_detail(str(content), url, {"title": title, "published_at": notice.get("publishTime", ""), "region": notice.get("provinceText", "")})
    is_award = notice.get("informationType") == "0202" or re.search(r"中标|成交|结果公示", notice.get("informationTypeText", "")) is not None or re.search(r"中标[（(]?成交[）)]?(?:结果)?公告|中标(?:结果)?公告|成交(?:结果)?公告|中标结果公示",title) is not None
    if re.search(r"招标公告|采购公告|磋商公告|谈判公告",title) and not re.search(r"中标|成交结果",title):is_award=False
    if re.search(r"候选|评标结果|评审结果|资格预审结果|流标|废标|终止|更正",title):is_award=False
    project = label_value(text, [r"项目名称", r"采购项目名称", r"招标项目名称"]) or parsed.get("项目名称") or title
    project = re.sub(r"(?:的)?(?:中标[（(]成交[）)](?:结果)?公告|中标结果公告|成交结果公告|中标公告|成交公告|公开招标公告|竞争性磋商公告|采购公告)$", "", project).strip()
    buyer = parsed.get("招标单位", "")
    if not buyer:
        section = re.search(r"(?:1[.、．]?\s*)?(?:采购人|招标人)信息([\s\S]{0,800})", text)
        buyer = label_value(section.group(1), [r"名\s*称", "名称"]) if section else ""
    buyer = buyer or label_value(text, ["采购人", "招标人", "采购单位名称", "采购单位", "建设单位"])
    supplier = parsed.get("中标单位", "") if is_award else ""
    supplier = supplier or (label_value(text, ["供应商名称", "中标人名称", "成交供应商名称", "中标供应商名称", "中标单位", "中标人"]) if is_award else "")
    table_awards, table_products = extract_tables(content)
    if is_award and table_awards:
        supplier = "；".join(dict.fromkeys(a["supplier"] for a in table_awards))
    # Only explicitly labelled monetary award values, never tender budgets/percent rates.
    amounts = []
    if is_award:
        for match in re.finditer(r"(?:中标[（(]成交[）)](?:总)?金额|中标(?:总)?金额|成交(?:总)?金额|中标价)\s*[：:]?\s*(?:人民币)?\s*([\d,，]+(?:\.\d+)?\s*(?:亿元|万元|元))", text):
            raw = plain(match.group(1))
            value = amount_wan(raw)
            if value is not None:
                amounts.append((value, raw))
    unique_amounts = list(dict.fromkeys(amounts))
    award = unique_amounts[0][0] if len(amounts) == 1 else None
    raw_amount = "；".join(x[1] for x in unique_amounts)
    if is_award and not amounts and len(table_awards)==1:
        award = table_awards[0]["amount_wan"]
        raw_amount = table_awards[0]["amount_raw"]
    elif is_award and len(table_awards)>1 and not amounts:
        raw_amount = "；".join(a["amount_raw"] for a in table_awards)
    if len(table_awards)>1 and not re.search(r"(?:中标|成交).{0,8}总金额|合计中标金额",text):
        award=None
    products = "、".join(table_products) or parsed.get("产品", "")
    if not products:
        products = label_value(text, ["服务名称", "主要标的名称", "货物名称", "采购标的", "采购内容"], 250)
    parties=[buyer,*re.split(r"[；;]",supplier)]
    product_items=list(dict.fromkeys(clean_product(x,parties) for x in products.split("、")))
    product_items=[x for x in product_items if x]
    products="、".join(product_items)
    table_products=[x for x in table_products if clean_product(x,parties)]
    missing = []
    if not buyer: missing.append("采购人未提取")
    if not products: missing.append("产品待核实")
    elif products==buyer:missing.append("产品名称与采购人相同，待复核")
    if is_award and not supplier: missing.append("中标单位待核实")
    if is_award and award is None: missing.append("多金额未合计" if len(unique_amounts)>1 or len(table_awards)>1 else "中标金额未提取")
    if not is_award: missing.append("非最终中标结果，未填写中标事实")
    if len(text) < 300: missing.append("正文过短或需加载来源正文")
    return {"项目名称": project, "产品": products, "招标单位": buyer, "客户标签": customer_tag(buyer, title) if buyer else "", "中标单位": supplier,
            "运营商类型": carrier_label(supplier) if supplier else "", "中标金额（万元）": award, "场景": classify_scene(title,products), "相关网页": url,
            "公告类型": notice.get("informationTypeText", ""), "公告日期": notice.get("publishTime", ""), "省份": notice.get("provinceText", ""),
            "项目编号": label_value(text, ["项目编号", "采购项目编号"]) or parsed.get("项目编号", "") or notice.get("tenderProjectCode") or "", "中标金额原文": raw_amount,
            "信息缺口": "；".join(missing), "标签依据": "客户/运营商/场景为名称与标题规则标签；其余字段取公告原文", "_source": notice, "_body_chars": len(text), "_text": text, "_parser_version":PARSER_VERSION,"_award_rows":table_awards if is_award else [],"_products":table_products,"_body_hash":hashlib.sha256(plain(text).encode()).hexdigest(),"_is_final_award":bool(is_award)}


class StopCollection(Exception):
    pass


class Collector:
    def __init__(self, args):
        self.args = args
        self.out = Path(args.output).resolve()
        self.state_file = self.out / "state.json"
        self.calls = 0
        self.last_request = 0
        self.state = None
        self.tls_failures = 0

    def prepare(self):
        config = {"start": self.args.start, "end": self.args.end, "keywords": self.args.keywords.split(","), "sources": self.args.sources.split(","), "notice_types": self.args.notice_types.split(","), "business": self.args.business, "delay_seconds": self.args.delay}
        if self.state_file.exists():
            if not self.args.resume:
                raise ValueError("Output already has a task; use --resume with identical scope")
            self.state = json.loads(self.state_file.read_text(encoding="utf-8"))
            if self.state["config"] != config:
                raise ValueError("Scope changed; create a new task/output directory")
            if self.state.get("routing_revision", 1) < 2:
                repaired = []
                for task in self.state["pending"]:
                    parts = list(archive_windows(task["start"], task["end"]))
                    if len(parts) == 1 and task.get("endpoint", "current") == parts[0][2]:
                        repaired.append(task)
                    else:
                        repaired.extend({**task, "start": a, "end": b, "endpoint": endpoint, "page": 1} for a,b,endpoint in parts)
                self.state["pending"] = repaired
                for failure in self.state["failures"]:
                    if "结束时间错误" in failure.get("error", "") and failure.get("task", {}).get("end") == (date.today()-timedelta(days=365)).isoformat():
                        failure["resolved_at"] = now()
                        failure["resolution"] = "Corrected official history/current cutoff; raw response retained"
                self.state["routing_revision"] = 2
        else:
            self.state = {"created_at": now(), "status": "running", "config": config, "pending": [], "completed_windows": [], "split_windows": [], "notices": {}, "records": {}, "excluded_count": 0, "failures": [], "api_calls_total": 0, "detail_calls_total": 0}
            # Results before tenders. Within each stage, cover all months before the next keyword.
            for stage in config["notice_types"]:
                for source in config["sources"]:
                    for word in config["keywords"]:
                        for start, end, endpoint in archive_windows(config["start"], config["end"]):
                            self.state["pending"].append({"start":start,"end":end,"word":word,"source":source,"stage":stage,"page":1,"endpoint":endpoint})
        self.out.mkdir(parents=True, exist_ok=True)
        temp_dir=self.out/"temp"
        temp_dir.mkdir(exist_ok=True)
        os.environ["TEMP"]=str(temp_dir)
        os.environ["TMP"]=str(temp_dir)
        truststore.inject_into_ssl()
        for folder in ("lists", "articles", "texts"):
            (self.out / folder).mkdir(exist_ok=True)
        self.state["status"] = "running"
        for failure in self.state["failures"]:
            if failure.get("error","").startswith(("Pause requested","API request budget reached")) and not failure.get("resolved_at"):
                failure["resolved_at"]=now()
        self.state.setdefault("cache_index",{})
        for key, notice in self.state["notices"].items():
            if not in_scope(notice.get("title","")):
                notice["_scope_rejected"] = "纯设备/后勤类，未发现明确数字化标的"
            if self.args.retry_failed:
                notice.pop("_detail_failed",None)
        self.checkpoint()

    def checkpoint(self):
        self.state["updated_at"] = now()
        write_json(self.state_file, self.state)
        counts = {"status": self.state["status"], "updated_at": self.state["updated_at"], "api_calls_total": self.state["api_calls_total"], "detail_calls_total": self.state["detail_calls_total"], "medical_digital_candidates": sum(not v.get("_scope_rejected") for v in self.state["notices"].values()), "records":len(self.state["records"]), "pending_search_windows":len(self.state["pending"]), "complete_windows":len(self.state["completed_windows"]), "failures":len(self.state["failures"]), "last_search": self.state.get("last_search")}
        write_json(self.out / "progress.json", counts)
        with (self.out / "公告明细.csv").open("w",encoding="utf-8-sig",newline="") as f:
            writer = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.state["records"].values())
        print(json.dumps(counts, ensure_ascii=True), flush=True)

    async def pause(self):
        await asyncio.sleep(max(0, self.args.delay - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()

    async def query(self, page, task):
        form = {"DEAL_CLASSIFY":self.args.business, "DEAL_STAGE":task["stage"], "SOURCE_TYPE":task["source"], "DEAL_TIME":"06", "TIMEBEGIN":task["start"], "TIMEEND":task["end"], "FINDTXT":task["word"], "PAGENUMBER":str(task["page"])}
        endpoint = task.get("endpoint", "current")
        endpoint_path = "/his/information/pubTradingInfo/getTradList" if endpoint == "history" else "/information/pubTradingInfo/getTradList"
        key = hashlib.sha256((("history\n" if endpoint == "history" else "") + json.dumps(form,sort_keys=True)).encode()).hexdigest()[:20]
        cache = self.out / "lists" / self.state.get("cache_index",{}).get(key,key+".json")
        if cache.exists():
            record = json.loads(cache.read_text(encoding="utf-8"))
            if record.get("response",{}).get("code") == 200:
                return record["response"]
        if self.calls >= self.args.max_api_calls:
            raise StopCollection("API request budget reached; pending windows retained")
        await self.pause()
        self.calls += 1
        self.state["api_calls_total"] += 1
        response = await page.evaluate("""async ({form,path})=>{let c=new AbortController();let timer=setTimeout(()=>c.abort(),45000);try{let r=await fetch(path,{method:'POST',signal:c.signal,headers:{'Content-Type':'application/x-www-form-urlencoded','X-Pass-Token':''},body:new URLSearchParams(form)});return {http:r.status,text:await r.text()}}finally{clearTimeout(timer)}}""", {"form":form,"path":endpoint_path})
        try:
            body = json.loads(response["text"])
        except ValueError:
            body = {"code":None,"non_json":response["text"]}
        if cache.exists():
            cache=self.out/"lists"/(key+"-attempt-"+str(time.time_ns())+".json")
        write_json(cache, {"requested_at":now(),"form":form,"endpoint":endpoint,"http":response["http"],"response":body})
        self.state["cache_index"][key]=cache.name
        if response["http"] in (401,403,429) or body.get("code") in (829,800):
            raise StopCollection(f"Challenge/rate limit: HTTP {response['http']}, code {body.get('code')}; no bypass/retry")
        if response["http"] != 200 or body.get("code") != 200:
            raise StopCollection(f"Search failed: HTTP {response['http']}, code {body.get('code')}, {body.get('message','')}")
        if not isinstance(body.get("data"), dict) or not isinstance(body["data"].get("records"),list):
            raise StopCollection("Unexpected list response schema")
        return body

    async def details(self, context, count):
        pending = [(k,v) for k,v in self.state["notices"].items() if (k not in self.state["records"] or self.state["records"][k].get("_parser_version")!=PARSER_VERSION) and not v.get("_detail_failed") and not v.get("_scope_rejected")]
        for index, (key, notice) in enumerate(pending[:count],1):
            if self.state["detail_calls_total"] >= self.args.max_details:
                return
            url = urljoin(BASE, notice.get("url", ""))
            if urlsplit(url).hostname != "www.ggzy.gov.cn":
                self.state["failures"].append({"stage":"detail","url":url,"error":"Not a national platform URL; requires separate source review"})
                notice["_detail_failed"] = True
                continue
            path = self.out / "articles" / (key + ".html")
            body_path = self.out / "articles" / (key + "-body.html")
            try:
                if body_path.exists():
                    html = body_path.read_text(encoding="utf-8")
                else:
                    await self.pause()
                    body_url = url.replace("/html/a/","/html/b/",1)
                    self.state["detail_calls_total"] += 1
                    status, html = await asyncio.to_thread(fetch_text,body_url,25,0)
                    if status in (401,403,429):
                        raise StopCollection(f"Detail HTTP {status}")
                    if status != 200:
                        raise RuntimeError("HTTP " + str(status))
                    body_path.write_text(html,encoding="utf-8")
                row = parse_article(html,notice)
                add_fields(row, html, notice.get("title", ""), url)
                (self.out/"texts"/(key+".txt")).write_text(row.pop("_text"),encoding="utf-8")
                row["_evidence_html"] = str(body_path)
                row["_body_url"] = url.replace("/html/a/","/html/b/",1)
                row["_parsed_at"] = now()
                row["_fetched_at"] = datetime.fromtimestamp(body_path.stat().st_mtime).astimezone().replace(microsecond=0).isoformat()
                self.state["records"][key] = row
                self.tls_failures = 0
                for failure in self.state["failures"]:
                    if failure.get("stage")=="detail" and failure.get("url")==url and not failure.get("resolved_at"):
                        failure["resolved_at"]=now()
            except StopCollection:
                raise
            except Exception as exc:
                self.state["failures"].append({"stage":"detail","url":url,"error":str(exc)[:300]})
                notice["_detail_failed"] = True
                if re.search(r"TLS|SSL|证书",str(exc),re.I):self.tls_failures+=1
                if self.tls_failures>=3:raise StopCollection("Repeated TLS verification failures; stopped without disabling verification")
            if index % 5 == 0:
                self.checkpoint()
        self.checkpoint()

    async def run(self):
        self.prepare()
        if self.args.stage == "reparse":
            for key, notice in self.state["notices"].items():
                path=self.out/"articles"/(key+"-body.html")
                if not path.exists() or notice.get("_scope_rejected"):continue
                row=parse_article(path.read_text(encoding="utf-8"),notice)
                (self.out/"texts"/(key+".txt")).write_text(row.pop("_text"),encoding="utf-8")
                row["_evidence_html"]=str(path)
                row["_fetched_at"]=datetime.fromtimestamp(path.stat().st_mtime).astimezone().replace(microsecond=0).isoformat()
                row["_parsed_at"]=now()
                row["_body_url"]=urljoin(BASE,notice["url"]).replace("/html/a/","/html/b/",1)
                self.state["records"][key]=row
            self.state["status"]="partial" if self.state["pending"] else "completed"
            self.checkpoint()
            return
        from playwright.async_api import async_playwright
        chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        stop_reason = None
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True,executable_path=str(chrome))
            context = await browser.new_context(ignore_https_errors=False)
            page = await context.new_page()
            try:
                await page.goto(BASE+"/deal/dealList.html",wait_until="domcontentloaded",timeout=60000)
                await page.wait_for_timeout(3500)
                if self.args.stage in ("all","discover"):
                    iterations=0
                    while self.state["pending"]:
                        if (self.out/"pause.request").exists():
                            raise StopCollection("Pause requested; checkpoints retained")
                        task = self.state["pending"][0]
                        self.state["last_search"] = dict(task)
                        before=self.calls
                        try:
                            body = await self.query(page,task)
                        except Exception as exc:
                            pieces = timeout_parts(task, exc)
                            if not pieces:
                                raise
                            self.state["split_windows"].append(dict(task, reason="network_timeout", error=str(exc)[:250]))
                            self.state["pending"].pop(0)
                            self.state["pending"].extend({**task,"start":a,"end":b,"page":1} for a,b in pieces)
                            for failure in self.state["failures"]:
                                if failure.get("task") == task and timeout_parts(task, failure.get("error", "")):
                                    failure["excluded_from_active_scope"] = True
                                    failure["resolution"] = "Parent query replaced by smaller pending date windows; original failure retained"
                            self.checkpoint()
                            continue
                        for failure in self.state["failures"]:
                            if failure.get("task") == task and timeout_parts(task, failure.get("error", "")):
                                failure["resolved_at"] = now()
                        iterations+=1
                        data = body["data"]
                        total = int(data.get("total") or 0)
                        pages = int(data.get("pages") or 0)
                        for notice in data["records"]:
                            published = (notice.get("publishTime") or "")[:10]
                            if not (self.args.start <= published <= self.args.end):
                                continue
                            if not in_scope(notice.get("title", "")):
                                self.state["excluded_count"] += 1
                                continue
                            url = urljoin(BASE,notice.get("url", ""))
                            key = hashlib.sha256(url.encode()).hexdigest()[:20]
                            self.state["notices"].setdefault(key, {**notice,"_discovered_by":dict(task)})
                        if task["page"] == 1 and total >= 1000:
                            pieces = split_window(task["start"],task["end"])
                            if not pieces:
                                raise StopCollection("A single day reaches the 1000-record cap; source subdivision required")
                            self.state["split_windows"].append(dict(task,total_capped=total))
                            self.state["pending"].pop(0)
                            for first,last in pieces:
                                self.state["pending"].append({**task,"start":first,"end":last,"page":1})
                        elif task["page"] >= pages or not data["records"]:
                            self.state["completed_windows"].append(dict(task,reported_total=total,pages=pages))
                            self.state["pending"].pop(0)
                        else:
                            task["page"] += 1
                            self.state["pending"].append(self.state["pending"].pop(0))
                        self.checkpoint()
                        if self.args.stage == "all" and self.calls>before and self.calls % 25 == 0:
                            await self.details(context,30)
                if self.args.stage in ("all","details"):
                    await self.details(context,self.args.max_details)
            except (StopCollection,Exception) as exc:
                stop_reason = str(exc)
                self.state["failures"].append({"stage":self.args.stage,"at":now(),"task":self.state.get("last_search"),"error":stop_reason})
            finally:
                await browser.close()
        pending_details = sum(k not in self.state["records"] and not v.get("_scope_rejected") for k,v in self.state["notices"].items())
        unresolved=[f for f in self.state["failures"] if not f.get("resolved_at") and not f.get("excluded_from_active_scope")]
        self.state["status"] = "partial" if self.state["pending"] or pending_details or stop_reason or unresolved else "completed"
        self.state["stop_reason"] = stop_reason
        self.state["pending_details"] = pending_details
        self.checkpoint()
        write_json(self.out/"collection-summary.json",{k:v for k,v in self.state.items() if k not in ("records","notices")})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start",default="2024-01-01")
    parser.add_argument("--end",default=date.today().isoformat())
    parser.add_argument("--output",required=True)
    parser.add_argument("--keywords",default="医,卫生,疾控,妇幼,血站,急救")
    parser.add_argument("--sources",default="1,3")
    parser.add_argument("--business",choices=["01","02","23","90"],default="02")
    parser.add_argument("--notice-types",default="0202,0201")
    parser.add_argument("--delay",type=float,default=3.2)
    parser.add_argument("--max-api-calls",type=int,default=2000)
    parser.add_argument("--max-details",type=int,default=3000)
    parser.add_argument("--stage",choices=["all","discover","details","reparse"],default="all")
    parser.add_argument("--resume",action="store_true")
    parser.add_argument("--retry-failed",action="store_true")
    parser.add_argument("--dry-run",action="store_true")
    args = parser.parse_args(argv)
    if date.fromisoformat(args.start)>date.fromisoformat(args.end) or args.delay<3 or args.max_api_calls<1 or args.max_details<1:
        parser.error("Invalid dates/budget; minimum request delay is 3 seconds")
    if args.dry_run:
        print(json.dumps({"status":"valid","start":args.start,"end":args.end,"source_types":args.sources,"notice_types":args.notice_types,"initial_search_windows":len(list(months(args.start,args.end)))*len(args.keywords.split(','))*len(args.sources.split(','))*len(args.notice_types.split(',')),"allow_network_when_executed":True,"max_api_calls":args.max_api_calls,"max_details":args.max_details,"output":str(Path(args.output).resolve())},ensure_ascii=True))
        return 0
    collector = Collector(args)
    asyncio.run(collector.run())
    return 0 if collector.state["status"] == "completed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
