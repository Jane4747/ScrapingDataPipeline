"""Beijing's documented public full-text search; monthly historical checkpoints."""
from datetime import datetime, timedelta, date
import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from pipeline.research.fetch import Fetcher
from pipeline.research.national_ggzy import in_scope, parse_article
from pipeline.research.tender_fields import add_fields
from pipeline.research.tenders import decode_html
from pipeline.research.zycg import month_windows

BASE = "https://ggzyfw.beijing.gov.cn"
SEARCH = BASE + "/elasticsearch/search"
WORDS = ("医院", "医疗", "卫生", "疾病预防控制", "妇幼", "血站", "急救", "医保")
KINDS = {"126": "采购公告", "127": "更正事项", "128": "成交结果公告"}


def write(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def parse_response(payload):
    if not isinstance(payload, dict) or "result" not in payload or "total" not in payload:
        raise ValueError("Unexpected Beijing search schema")
    result = payload["result"]
    if isinstance(result, str):
        result = json.loads(result)
    if not isinstance(result, list) or int(payload["total"]) < 0:
        raise ValueError("Invalid Beijing search rows/total")
    return result, int(payload["total"])


def form_for(first, last, word, page):
    # Field names and channel values come from elasticsearch/index.jsp.
    return {"searchword": word, "scope": "title", "channel_first": "jyxx", "channel_second": "jyxxzfcg",
            "channel_third": "", "channel_fourth": "", "legislationType": "", "ext": "", "ext8": "",
            "starttime": first, "endtime": last, "sort": "", "page": str(page), "size": "20"}


def collect(request, folder, report):
    folder = Path(folder)
    state_file = folder / "state.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {
        "pending": [{"start": a, "end": b, "word": w, "page": 1} for a, b in month_windows(request["start"], request["end"]) for w in WORDS],
        "completed": [], "notices": {}, "records": {}, "failures": [], "list_pages": 0}
    if state.get("query_revision", 1) < 2:
        state["previous_query_coverage"] = {"completed": state["completed"], "pending": state["pending"], "reason": "Use the official title scope and full medical tokens; original raw pages and valid records retained"}
        state["pending"] = [{"start":a,"end":b,"word":w,"page":1} for a,b in month_windows(request["start"],request["end"]) for w in WORDS]
        state["completed"] = []
        state["query_revision"] = 2
    for name in ("lists", "raw"):
        (folder / name).mkdir(exist_ok=True)
    fetcher = Fetcher(timeout=35, retries=0, delay=request["delay"], transport="system_tls")
    new_calls, stop_reason = 0, None
    try:
        while state["pending"]:
            task = state["pending"][0]
            if task["page"] > request["max_pages"] or new_calls >= request["max_api_calls"]:
                stop_reason = "List/API budget reached; pending windows retained"
                break
            form = form_for(task["start"], task["end"], task["word"], task["page"])
            key = hashlib.sha256(json.dumps(form, sort_keys=True).encode()).hexdigest()[:20]
            cache = folder / "lists" / (key + ".json")
            if cache.exists():
                payload = json.loads(cache.read_text(encoding="utf-8"))["response"]
            else:
                response = fetcher.post_json(SEARCH, form, ["ggzyfw.beijing.gov.cn"])
                new_calls += 1
                if response["status"] != "ok":
                    stop_reason = response.get("error") or response["status"]
                    state["failures"].append({"form": form, "status": response["status"], "error": stop_reason})
                    if response.get("raw"):
                        (folder / "lists" / (key + ".failed.bin")).write_bytes(response["raw"])
                    break
                payload = response["data"]
                parse_response(payload)
                write(cache, {"requested_at": datetime.now().astimezone().isoformat(), "form": form, "response": payload})
            items, total = parse_response(payload)
            if not items and total:
                raise ValueError("Nonzero search total with empty page; coverage is incomplete")
            dates = [str(n.get("releaseDate", ""))[:10] for n in items if n.get("releaseDate")]
            if dates and not all(task["start"] <= d <= task["end"] for d in dates):
                raise ValueError("The platform did not apply the requested date window")
            if items and task["page"] > 1 and hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest() == state.get("last_page_hash"):
                raise ValueError("Repeated search page; stopping without marking historical coverage complete")
            state["last_page_hash"] = hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()
            for item in items:
                title = item.get("title", "")
                if not in_scope(title):
                    continue
                url = urljoin(BASE, item.get("link", ""))
                if urlsplit(url).hostname != "ggzyfw.beijing.gov.cn":
                    continue
                nid = hashlib.sha256(url.encode()).hexdigest()[:20]
                state["notices"].setdefault(nid, {**item, "url": url})
            state["list_pages"] += 1
            # Retrieve details after each page, so outputs are useful before the crawl ends.
            for nid, notice in state["notices"].items():
                if nid in state["records"]:
                    continue
                if len(state["records"]) >= request["max_details"]:
                    stop_reason = "Detail budget reached; pending notices retained"
                    break
                path = folder / "raw" / (nid + ".html")
                if path.exists():
                    html = decode_html(path.read_bytes())
                else:
                    response = fetcher.fetch(notice["url"], ["ggzyfw.beijing.gov.cn"])
                    if response["status"] != "ok":
                        stop_reason = response.get("error") or response["status"]
                        state["failures"].append({"url": notice["url"], "status": response["status"], "error": stop_reason})
                        break
                    path.write_bytes(response["raw"])
                    html = decode_html(response["raw"])
                published = str(notice.get("releaseDate", ""))[:10]
                kind = KINDS.get(str(notice.get("channelId", "")), "采购公告")
                meta = {"title": notice["title"], "url": notice["url"], "publishTime": published,
                        "informationType": "0202" if kind == "成交结果公告" else "0201",
                        "informationTypeText": kind, "provinceText": "北京", "tenderProjectCode": notice.get("projectCode", "")}
                row = parse_article(html, meta)
                add_fields(row, html, notice["title"], notice["url"])
                row.pop("_text", None)
                row.update(来源="北京公共资源交易平台", 原文文件=str(path), 日期依据="官方历史检索发布日期")
                state["records"][nid] = row
                write(folder / "records.json", list(state["records"].values()))
            if stop_reason:
                break
            if task["page"] * int(payload.get("size") or 20) >= total:
                state["completed"].append(dict(task, total=total))
                state["pending"].pop(0)
            else:
                task["page"] += 1
            write(state_file, state)
            report(status="running", records=len(state["records"]), list_pages=state["list_pages"],
                   complete_windows=len(state["completed"]), pending_search_windows=len(state["pending"]), current_window=dict(task))
    finally:
        fetcher.close()
        write(state_file, state)
        write(folder / "records.json", list(state["records"].values()))
    status = "partial" if state["pending"] or stop_reason else "completed"
    report(status=status, records=len(state["records"]), list_pages=state["list_pages"], complete_windows=len(state["completed"]),
           pending_search_windows=len(state["pending"]), failures=state["failures"], stop_reason=stop_reason)
    return 0 if status == "completed" else 3
