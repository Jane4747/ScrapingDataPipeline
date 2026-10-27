"""Source-scoped discovery, durable checkpoints and evidence-based collection."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
from urllib.parse import urlsplit

from .fetch import Fetcher, is_allowed_url, normalize_url
from .relevance import classify


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def link_priority(url, text):
    """Prefer specific equipment/medical links over general section indexes."""
    path = urlsplit(url).path.lower()
    if re.search(r"\.(?:png|jpg|jpeg|gif|svg|webp|ico|css|js|zip|mp4|mp3|woff2?)(?:$)", path):
        return -1
    label = (text or "").lower()
    if re.search(r"招聘|招贤|隐私|联系我们|法律声明|股票|股东|党建|廉洁|人才招聘|privacy|career|login", label):
        return -1
    specific = ("医疗", "医学", "医械", "手术", "机器人", "康复", "外骨骼", "影像", "监护", "诊断", "超声", "导航", "装备", "onehealth", "medical", "surgical", "rehab", "exoskeleton", "ultrasound", "imaging")
    score = sum(20 for term in specific if term in label)
    score += sum(8 for term in specific if term in path)
    if re.search(r"产品|技术|科研|研发|研究|方案|案例|新闻|动态|下载|报告|白皮书|下一页|product|solution|research|technology|news|download|report|next", label):
        score += 7
    if re.search(r"product|solution|research|technology|news|medical|download|report|yanjiu|chanpin|jishu", path):
        score += 3
    if path.endswith(".pdf"):
        score += 5
    return score


def source_fingerprint(source):
    return hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class ResearchCrawler:
    def __init__(self, output_dir, max_pages=12, max_depth=2, workers=3,
                 timeout=25, retries=1, delay=1.0, browser=False,
                 resume=False, retry_failed=False, reprocess=False,
                 max_bytes=12 * 1024 * 1024, fetcher_factory=Fetcher):
        if max_pages < 1 or max_depth < 0 or workers < 1:
            raise ValueError("max_pages/workers 必须大于零，max_depth 不得为负数")
        if delay < 0 or timeout <= 0 or retries < 0 or max_bytes < 1:
            raise ValueError("delay/retries 不得为负数，timeout 必须大于零")
        self.output_dir = Path(output_dir)
        self.max_pages, self.max_depth, self.workers = max_pages, max_depth, workers
        self.fetch_options = dict(timeout=timeout, retries=retries, delay=delay, browser=browser, max_bytes=max_bytes)
        self.resume, self.retry_failed = resume, retry_failed
        self.reprocess = reprocess
        self.fetcher_factory = fetcher_factory
        self._print_lock = threading.Lock()

    def _log(self, message):
        with self._print_lock:
            print(message, flush=True)

    def validate_sources(self, sources):
        """Reject incompatible resumes before any output is replaced."""
        for source in sources:
            path = self.output_dir / "sources" / source["id"] / "state.json"
            if self.reprocess and not path.exists():
                raise ValueError(f"平台 {source['id']} 没有可重新解析的检查点")
            if path.exists():
                if not self.resume:
                    raise ValueError("结果目录已有检查点，请使用 --resume 或新的 --run-id")
                saved = json.loads(path.read_text(encoding="utf-8"))
                if saved.get("fingerprint") != source_fingerprint(source):
                    raise ValueError(f"平台 {source['id']} 来源配置已变化，请使用新的 --run-id")

    def collect(self, sources):
        self.validate_sources(sources)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        results = {}
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            tasks = {executor.submit(self._source, source): source for source in sources}
            for future in as_completed(tasks):
                source = tasks[future]
                try:
                    results[source["id"]] = future.result()
                except Exception as exc:
                    path = self.output_dir / "sources" / source["id"] / "state.json"
                    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
                    results[source["id"]] = {**saved,
                        "source_id": source["id"], "source_name": source["name"],
                        "status": "partial" if saved.get("pages") else "failed",
                        "pages": saved.get("pages", []), "records": saved.get("records", []),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    self._log(f"FAIL {source['name']}: {exc}")
        return [results[source["id"]] for source in sources]

    def _source(self, source):
        folder = self.output_dir / "sources" / source["id"]
        state_path = folder / "state.json"
        fingerprint = source_fingerprint(source)
        if state_path.exists():
            if not self.resume:
                raise ValueError("结果目录已有检查点，请使用 --resume 或新的 --run-id")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if state.get("fingerprint") != fingerprint:
                raise ValueError("来源配置已变化，请使用新的 --run-id，避免混合旧抓取范围")
        else:
            state = {"version": 1, "fingerprint": fingerprint, "source_id": source["id"],
                     "source_name": source["name"], "started_at": now(), "pages": [], "records": []}
        pages = {page["requested_url"]: page for page in state["pages"]}
        records = {record["id"]: record for record in state["records"]}
        if self.reprocess:
            records = {}
        # Reconstruct the frontier from saved links, so raising the depth/page budget works.
        frontier = {}

        def enqueue(url, depth, parent, priority):
            url = normalize_url(url)
            if not url or depth > self.max_depth or not is_allowed_url(url, source["allowed_domains"]):
                return
            old = pages.get(url)
            if old and not self.reprocess and (old["status"] == "ok" or not self.retry_failed):
                return
            if url not in frontier or depth < frontier[url]["depth"]:
                frontier[url] = {"url": url, "depth": depth, "parent": parent, "priority": priority}

        if self.reprocess:
            for page in pages.values():
                frontier[page["requested_url"]] = dict(url=page["requested_url"], depth=page["depth"],
                    parent=page["discovered_from"], priority=10000)
        else:
            for url in source["seeds"]:
                enqueue(url, 0, "", 10000)
        for page in list(pages.values()):
            if self.reprocess:
                continue
            if page["status"] != "ok":
                if self.retry_failed:
                    enqueue(page["requested_url"], page["depth"], page["discovered_from"], 9000)
                continue
            for link in page.get("links", []):
                score = link_priority(link["url"], link.get("text", ""))
                if score > 0:
                    enqueue(link["url"], page["depth"] + 1, page["url"], score)

        fetcher = self.fetcher_factory(**self.fetch_options)
        attempted = set()
        try:
            while frontier:
                candidates = [item for item in frontier.values()
                              if item["url"] not in attempted and
                              (item["url"] in pages or len(pages) < self.max_pages)]
                if not candidates:
                    break
                item = max(candidates, key=lambda value: (value["priority"], -value["depth"]))
                url = item["url"]
                frontier.pop(url)
                attempted.add(url)
                action = "REPROCESS" if self.reprocess else "FETCH"
                self._log(f"{action} {source['name']} [{len(pages) + (url not in pages)}/{self.max_pages}] {url}")
                previous = pages.get(url, {})
                try:
                    if self.reprocess:
                        page = dict(previous)
                        if previous.get("raw_file"):
                            body = (self.output_dir / previous["raw_file"]).read_bytes()
                            parsed = fetcher.extract_cached(body, page, source["allowed_domains"])
                            if previous["status"] == "ok" and parsed["status"] != "ok":
                                raise ValueError(parsed.get("error") or "原成功页面重新解析失败")
                            page.update(parsed)
                        elif previous.get("text_file"):
                            page["text"] = (self.output_dir / previous["text_file"]).read_text(encoding="utf-8")
                    else:
                        page = fetcher.fetch(url, source["allowed_domains"])
                except Exception as exc:
                    if self.reprocess:
                        raise ValueError(f"缓存重新解析失败，保留该平台原检查点：{url}: {exc}") from exc
                    page = {"requested_url": url, "url": url, "status": "error",
                            "error": f"{type(exc).__name__}: {exc}", "text": "", "links": []}
                raw = page.pop("raw", None)
                page.update(requested_url=url, depth=item["depth"], discovered_from=item["parent"])
                if self.reprocess:
                    page["reprocessed_at"] = now()
                    page.pop("duplicate_of", None)
                else:
                    page["fetched_at"] = now()
                page.setdefault("url", url)
                page.setdefault("links", [])
                text = page.pop("text", "")
                digest = hashlib.sha256(page["url"].encode()).hexdigest()[:20]
                record_id = f"{source['id']}:{digest}"
                # A retry must replace its old classification, not leave stale evidence.
                if previous.get("record_id"):
                    records.pop(previous["record_id"], None)
                page["record_id"] = record_id
                if raw and not (self.reprocess and page.get("raw_file")):
                    folder.mkdir(parents=True, exist_ok=True)
                    extension = ".pdf" if "pdf" in page.get("content_type", "").lower() else ".html"
                    raw_path = folder / f"{digest}{extension}"
                    raw_path.write_bytes(raw)
                    page["raw_file"] = raw_path.relative_to(self.output_dir).as_posix()
                if page["status"] == "ok":
                    folder.mkdir(parents=True, exist_ok=True)
                    text_hash = hashlib.sha256(text.encode()).hexdigest()
                    text_name = f"{digest}-{text_hash[:12]}.txt" if self.reprocess else f"{digest}.txt"
                    text_path = folder / text_name
                    text_path.write_text(text, encoding="utf-8")
                    page["text_file"] = text_path.relative_to(self.output_dir).as_posix()
                    page["content_sha256"] = text_hash
                    match = classify(page.get("title", ""), text)
                    page["relevance"] = match["relevance"]
                    duplicate = next((old for old in pages.values()
                                      if old.get("requested_url") != url and old.get("record_id") != record_id
                                      and old.get("content_sha256") == page["content_sha256"]
                                      and old.get("record_id") in records), None)
                    if duplicate:
                        page["duplicate_of"] = duplicate["record_id"]
                    if match["relevant"] and not duplicate:
                        records[record_id] = dict(
                            id=record_id, source_id=source["id"], source_name=source["name"],
                            title=page.get("title", ""), url=page["url"], requested_url=url,
                            published_at=page.get("published_at", ""), collected_at=page["fetched_at"],
                            content_type=page.get("content_type", ""), method=page.get("method", ""),
                            discovered_from=item["parent"], text_file=page["text_file"],
                            raw_file=page.get("raw_file", ""), content_sha256=page["content_sha256"], **match)
                    for link in ([] if self.reprocess else page["links"]):
                        score = link_priority(link["url"], link.get("text", ""))
                        if score > 0:
                            enqueue(link["url"], item["depth"] + 1, page["url"], score)
                pages[url] = page
                state.update(pages=list(pages.values()), records=list(records.values()), updated_at=now())
                if not self.reprocess:
                    write_json(state_path, state)
        finally:
            fetcher.close()
        failures = sum(page["status"] != "ok" for page in pages.values())
        successes = len(pages) - failures
        eligible = [item for item in frontier.values() if item["url"] not in pages]
        remaining = state.get("remaining_candidates", 0) if self.reprocess else len(eligible)
        state.update(
            status="failed" if not successes else ("partial" if failures or remaining else "completed"),
            updated_at=now(), pages=list(pages.values()), records=list(records.values()),
            attempted_pages=len(pages), successful_pages=successes, failed_pages=failures,
            remaining_candidates=remaining,
            max_pages=state.get("max_pages", self.max_pages) if self.reprocess else self.max_pages,
            max_depth=state.get("max_depth", self.max_depth) if self.reprocess else self.max_depth,
            stop_reason=state.get("stop_reason", "reprocessed") if self.reprocess else (
                "page_budget" if eligible and len(pages) >= self.max_pages else "frontier_exhausted"),
        )
        write_json(state_path, state)
        self._log(f"DONE {source['name']}: {successes} pages, {len(records)} relevant, {failures} failed")
        return state
