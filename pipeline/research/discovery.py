"""Create reproducible search plans and import scoped candidate article URLs.

Search results are leads, not verified deployment facts. The default provider
does not access the network. Optional Brave search uses its documented API,
with a separate per-run budget, and never requests search-engine HTML pages.
"""
from __future__ import annotations

import copy
import csv
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time
from urllib.parse import urlencode

import requests

from pipeline.catalog import OUTPUTS
from .config import load_config, validate_seed_url
from .fetch import is_allowed_url, normalize_url


BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
MAX_API_BUDGET = 30
MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
CANDIDATE_NOTICE = "搜索结果仅为候选链接；正文、发布日期、部署状态及应用效果尚待原文核实。"
QUERY_TOPICS = (
    ("部署与试点", '医疗 (部署 OR 试点 OR 上线)'),
    ("医院应用案例", '医院 (智能 OR 智慧) 案例'),
    ("智能装备", '(医疗装备 OR 医疗机器人) 应用'),
    ("健康与康养", '(智慧健康 OR 智慧康养) 项目'),
    ("合作与验收", '医疗 (合作 OR 中标 OR 验收)'),
    ("战略与年度披露", '医疗 (年报 OR 战略 OR 布局)'),
)
# Registry display labels may include explanatory words absent from articles.
SEARCH_NAMES = {
    "genertec_health": "通用技术",
    "china_mobile": "中国移动",
    "china_telecom": "中国电信",
    "china_unicom": "中国联通",
    "yunnan_investment_health": "云投",
}


def build_query_plan(sources: list[dict], max_queries: int = 6,
                     query_topics: list[dict] | None = None) -> list[dict]:
    """Round-robin source order makes a small API budget explicit and balanced.

    Each query has one site restriction. Query-only domain deduplication removes
    a subdomain when its parent is already allowed. Cover each topic once before
    adding its other domain variants; leave the source allowlist untouched.
    """
    if type(max_queries) is not int or not 1 <= max_queries <= 30:
        raise ValueError("--max-queries 必须在 1..30 之间（每个来源）")
    topics = QUERY_TOPICS
    if query_topics is not None:
        if (not isinstance(query_topics, list) or not 1 <= len(query_topics) <= 30
                or any(not isinstance(topic, dict)
                       or any(not isinstance(topic.get(key), str) or not topic[key].strip()
                              for key in ("purpose", "terms")) for topic in query_topics)):
            raise ValueError("query_topics 必须是 1..30 条含非空 purpose、terms 的对象列表")
        topics = tuple((topic["purpose"].strip(), topic["terms"].strip()) for topic in query_topics)
    by_source = []
    for source in sources:
        queries = []
        search_name = SEARCH_NAMES.get(source["id"], source["name"])
        domains = [domain for domain in dict.fromkeys(source["allowed_domains"])
                   if not any(domain != parent and domain.endswith("." + parent)
                              for parent in source["allowed_domains"])]
        for offset in range(len(domains)):
            for topic_index, (label, terms) in enumerate(topics):
                domain = domains[(topic_index + offset) % len(domains)]
                query = f'"{search_name}" {terms} site:{domain}'
                queries.append({
                    "query_id": f'{source["id"]}-{len(queries) + 1:02d}',
                    "source_id": source["id"], "source_name": source["name"],
                    "purpose": label, "domain": domain, "query": query,
                    "bing_url": "https://www.bing.com/search?" + urlencode({"q": query}),
                    "baidu_url": "https://www.baidu.com/s?" + urlencode({"wd": query}),
                })
                if len(queries) >= max_queries:
                    break
            if len(queries) >= max_queries:
                break
        by_source.append(queries)
    return [queries[index] for index in range(max_queries)
            for queries in by_source if index < len(queries)]


def load_import(path: Path) -> list:
    if path.stat().st_size > MAX_IMPORT_BYTES:
        raise ValueError("导入文件超过 5 MiB，请拆分后导入")
    try:
        items = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"导入文件不是有效 JSON：{exc.msg}") from exc
    if not isinstance(items, list) or len(items) > 10000:
        raise ValueError("导入文件必须是最多 10000 条记录的 JSON 数组")
    return items


def merge_candidates(config: dict, items: list, source_ids: set[str] | None = None,
                     origin: str = "manual_import") -> tuple[dict, list[dict], list[dict]]:
    """Return a copied config plus accepted/rejected provenance records.

    Preserve all original domains and seeds. Additional URLs must satisfy the
    source allowlist and the seed URL constraints enforced by load_config.
    """
    merged = copy.deepcopy(config)
    sources = {source["id"]: source for source in merged["sources"]}
    allowed_ids = source_ids if source_ids is not None else set(sources)
    seen = {sid: {normalize_url(url) for url in source["seeds"]}
            for sid, source in sources.items()}
    accepted, rejected = [], []
    for index, item in enumerate(items):
        record = {"origin": origin, "input_index": index, "candidate_only": True}
        if not isinstance(item, dict):
            rejected.append({**record, "reason": "record_must_be_object"})
            continue
        # Copy only declared data fields, never arbitrary provider data/headers.
        for key in ("source_id", "url", "title", "query", "query_id", "description"):
            value = item.get(key, "")
            if isinstance(value, str):
                record[key] = value
        sid, raw_url = item.get("source_id"), item.get("url")
        if not isinstance(sid, str) or sid not in sources:
            rejected.append({**record, "reason": "unknown_source_id"})
            continue
        if sid not in allowed_ids:
            rejected.append({**record, "reason": "source_not_selected"})
            continue
        if (not isinstance(raw_url, str) or not raw_url or
                any(char.isspace() for char in raw_url) or "\\" in raw_url):
            rejected.append({**record, "reason": "invalid_url"})
            continue
        url = normalize_url(raw_url)
        try:
            validate_seed_url(url)
        except ValueError:
            rejected.append({**record, "reason": "invalid_url"})
            continue
        try:
            validate_seed_url(url, sources[sid]["allowed_domains"])
        except ValueError:
            rejected.append({**record, "reason": "outside_source_allowlist"})
            continue
        if not is_allowed_url(url, sources[sid]["allowed_domains"]):
            rejected.append({**record, "reason": "outside_source_allowlist"})
            continue
        record["normalized_url"] = url
        if url in seen[sid]:
            record["outcome"] = "already_present"
        else:
            sources[sid]["seeds"].append(url)
            seen[sid].add(url)
            record["outcome"] = "added_candidate_seed"
        accepted.append(record)
    return merged, accepted, rejected


def search_brave(plan: list[dict], results_per_query: int = 5, budget: int = 6,
                 delay: float = 1.1, session=None) -> tuple[list[dict], list[dict]]:
    """Search with one fixed authenticated origin; return hits and query status.

    No redirects, retries, raw error bodies or exception text are emitted, so a
    server error cannot accidentally expose the subscription header. All HTTP
    errors stop this run, including authentication failure and rate limiting.
    """
    if not 1 <= budget <= MAX_API_BUDGET:
        raise ValueError(f"--api-budget 必须在 1..{MAX_API_BUDGET} 之间")
    if not 1 <= results_per_query <= 20:
        raise ValueError("--results-per-query 必须在 1..20 之间")
    if delay < 1.0:
        raise ValueError("Brave 查询间隔不得小于 1 秒")
    key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if not key:
        raise ValueError("Brave 模式需要环境变量 BRAVE_SEARCH_API_KEY；也可使用默认 plan 模式")
    own_session = session is None
    session = session or requests.Session()
    hits, statuses = [], []
    stop_reason = ""
    attempted = 0
    try:
        for item in plan:
            status = {"query_id": item["query_id"], "source_id": item["source_id"],
                      "query": item["query"]}
            if stop_reason or attempted >= budget:
                statuses.append({**status, "status": "not_requested",
                                 "reason": stop_reason or "api_budget_exhausted"})
                continue
            if attempted:
                time.sleep(delay)
            attempted += 1
            response = None
            try:
                response = session.get(
                    BRAVE_ENDPOINT,
                    headers={"Accept": "application/json", "X-Subscription-Token": key},
                    params={"q": item["query"], "count": results_per_query, "search_lang": "zh-hans"},
                    timeout=25, allow_redirects=False, stream=True)
                if response.status_code != 200:
                    reasons = {401: "authentication_failed", 403: "access_denied",
                               429: "rate_limited"}
                    stop_reason = reasons.get(response.status_code, "http_error")
                    statuses.append({**status, "status": "error", "reason": stop_reason,
                                     "http_status": response.status_code})
                    continue
                chunks, length = [], 0
                for chunk in response.iter_content(chunk_size=65536):
                    length += len(chunk)
                    if length > MAX_RESPONSE_BYTES:
                        raise ValueError("response_too_large")
                    chunks.append(chunk)
                payload = json.loads(b"".join(chunks))
                web = payload.get("web", {}) if isinstance(payload, dict) else None
                results = web.get("results", []) if isinstance(web, dict) else None
                if not isinstance(results, list):
                    raise ValueError("invalid_response")
                valid_count = 0
                for result in results[:results_per_query]:
                    if not isinstance(result, dict):
                        continue
                    hit = {"source_id": item["source_id"], "query_id": item["query_id"],
                           "query": item["query"], "url": result.get("url", ""),
                           "title": result.get("title", ""),
                           "description": result.get("description", "")}
                    hits.append(hit)
                    valid_count += 1
                statuses.append({**status, "status": "ok", "result_count": valid_count})
            except requests.RequestException:
                stop_reason = "network_error"
                statuses.append({**status, "status": "error", "reason": stop_reason})
            except (ValueError, UnicodeError):
                stop_reason = "invalid_or_oversized_response"
                statuses.append({**status, "status": "error", "reason": stop_reason})
            finally:
                if response is not None:
                    response.close()
    finally:
        if own_session:
            session.close()
    return hits, statuses


def _json_exclusive(path: Path, content):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(content, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _csv_cell(value):
    # Keep search plans safe to open directly in Excel.
    return "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value


def register(sub):
    parser = sub.add_parser("discover", help="生成企业检索计划或导入候选链接，默认不联网")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--source", action="append", default=[], help="来源 ID，可重复")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--provider", choices=("plan", "brave"), default="plan")
    parser.add_argument("--max-queries", type=int, default=6, help="每个来源最多查询条数，默认 6")
    parser.add_argument("--results-per-query", type=int, default=5)
    parser.add_argument("--api-budget", type=int, default=6, help="整次 Brave 搜索请求上限，默认 6，最多 30")
    parser.add_argument("--import-results", type=Path, help="手动收集的 JSON 数组，含 source_id、url、title、query")
    parser.set_defaults(func=run)


def run(args):
    config = load_config(args.config)
    known_ids = {source["id"] for source in config["sources"]}
    selected_ids = set(args.source) if args.source else known_ids
    if selected_ids - known_ids:
        raise ValueError("未知来源 ID：" + ", ".join(sorted(selected_ids - known_ids)))
    sources = [source for source in config["sources"] if source["id"] in selected_ids]
    if not 1 <= args.results_per_query <= 20:
        raise ValueError("--results-per-query 必须在 1..20 之间")
    if not 1 <= args.api_budget <= MAX_API_BUDGET:
        raise ValueError(f"--api-budget 必须在 1..{MAX_API_BUDGET} 之间")
    plan = build_query_plan(sources, args.max_queries, getattr(args, "query_topics", None))
    imported = load_import(args.import_results) if args.import_results else []
    if args.provider == "brave" and not os.environ.get("BRAVE_SEARCH_API_KEY", "").strip():
        raise ValueError("Brave 模式需要环境变量 BRAVE_SEARCH_API_KEY；默认 plan 模式不需要密钥")
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("discovery-%Y%m%d-%H%M%S-%f")
    output_dir = args.output_dir.resolve() if args.output_dir else OUTPUTS / stamp
    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise ValueError("输出目录已有文件；请指定新的 --output-dir，不覆盖已有结果")
    output_dir.mkdir(parents=True, exist_ok=True)
    # Exclusive file writes plus the lock prevent concurrent runs from merging
    # unrelated outputs or replacing a user's existing documents.
    lock = output_dir / "discovery.lock"
    with lock.open("x", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    try:
        metadata = {"generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
                    "provider": args.provider, "topic": config["topic"],
                    "source_ids": [source["id"] for source in sources],
                    "max_queries_per_source": args.max_queries,
                    "query_count": len(plan), "api_budget": args.api_budget,
                    "results_per_query": args.results_per_query,
                    "notice": CANDIDATE_NOTICE, "queries": plan}
        _json_exclusive(output_dir / "query_plan.json", metadata)
        with (output_dir / "query_plan.csv").open("x", encoding="utf-8-sig", newline="") as handle:
            fields = ("source_id", "source_name", "query_id", "purpose", "domain", "query", "bing_url", "baidu_url")
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows({key: _csv_cell(item[key]) for key in fields} for item in plan)
        with (output_dir / "query_plan.md").open("x", encoding="utf-8") as handle:
            handle.write("# 企业部署资料检索计划\n\n" + CANDIDATE_NOTICE + "\n\n")
            handle.write("先搜索企业官网，再在原文中核对项目、医院、时间、部署阶段与效果。搜索范围受原配置域名白名单限制。\n\n")
            handle.write(f"共 {len(sources)} 个来源、{len(plan)} 条查询；每来源最多 {args.max_queries} 条。")
            handle.write(f" Brave 模式整次最多调用 {args.api_budget} 次；默认 plan 模式不会发起请求。\n\n")
            handle.write("可逐次删除限定词放宽搜索；跨域的医院、政府或公告网站需另行核实并手动配置来源。\n\n")
            handle.write("| 来源 | 检索目的 | 查询词 | 搜索入口 |\n| --- | --- | --- | --- |\n")
            for item in plan:
                handle.write(f"| {_cell(item['source_name'])} | {_cell(item['purpose'])} | {_cell(item['query'])} | "
                             f"[Bing]({item['bing_url']}) / [百度]({item['baidu_url']}) |\n")
        merged, accepted, rejected = merge_candidates(
            config, imported, selected_ids,
            str(args.import_results.resolve()) if args.import_results else "manual_import")
        statuses = []
        if args.provider == "brave":
            hits, statuses = search_brave(plan, args.results_per_query, args.api_budget)
            merged, api_accepted, api_rejected = merge_candidates(merged, hits, selected_ids, "brave_search_api")
            accepted.extend(api_accepted)
            rejected.extend(api_rejected)
        else:
            statuses = [{"query_id": item["query_id"], "source_id": item["source_id"],
                         "query": item["query"], "status": "not_requested", "reason": "plan_only"}
                        for item in plan]
        _json_exclusive(output_dir / "search_results.json", accepted)
        _json_exclusive(output_dir / "rejected_results.json", rejected)
        _json_exclusive(output_dir / "query_status.json", statuses)
        _json_exclusive(output_dir / "config.discovered.json", merged)
        summary = {"output_dir": str(output_dir), "query_count": len(plan),
                   "api_requests": sum(item["status"] != "not_requested" for item in statuses),
                   "accepted_candidates": len(accepted), "rejected_candidates": len(rejected),
                   "added_seeds": sum(item["outcome"] == "added_candidate_seed" for item in accepted),
                   "search_errors": sum(item["status"] == "error" for item in statuses),
                   "notice": CANDIDATE_NOTICE}
        _json_exclusive(output_dir / "discovery_summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 2 if summary["search_errors"] else 0
    finally:
        lock.unlink(missing_ok=True)
