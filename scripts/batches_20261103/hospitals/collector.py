"""Bounded hospital refresh using the existing pipeline Fetcher and saved evidence.

Each hospital is independently resumable; missing coverage remains partial.
No model calls, browser bypasses, disabled TLS, or guessed publication dates.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date, datetime, timezone
import hashlib
import html as html_lib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

REPO = Path(__file__).resolve().parents[3]
sys.dont_write_bytecode = True
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from bs4 import BeautifulSoup
from pipeline.research.fetch import Fetcher, is_allowed_url, normalize_url
from hospital_batch_crawl import digital_hits

ARCHIVE = Path(os.environ.get("HOSPITAL_LEGACY_ARCHIVE", str(REPO / "outputs/hospital-site-crawl-90-20261028")))
ANNOUNCE = re.compile(r"采购|招标|中标|成交|比选|比价|遴选|谈判|询价|磋商|征集|公告|公示|招采|资格预审|论证|竞价|议价")
DATE = re.compile(r"(?<!\d)(20\d{2})[-/.年]\s*(\d{1,2})[-/.月]\s*(\d{1,2})(?:日)?(?!\d)")
ATTACHMENT = re.compile(r"\.(?:pdf|docx?|xlsx?|zip|rar)(?:$|[?#])", re.I)


def lp(path):
    value = str(Path(path).absolute())
    return Path(value if os.name != "nt" or value.startswith("\\\\?\\") else "\\\\?\\" + value)


def read_json(path):
    return json.loads(lp(path).read_text(encoding="utf-8-sig"))


def write_json(path, data):
    path = lp(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    # Windows readers/antivirus may briefly open the destination without
    # FILE_SHARE_DELETE. Keep atomic replacement and retry only access conflicts;
    # persistent permission failures remain fatal and must never look complete.
    delays = (0.05, 0.1, 0.2, 0.4, 0.8)
    for attempt in range(len(delays) + 1):
        try:
            temporary.write_text(payload, encoding="utf-8")
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == len(delays):
                raise
            time.sleep(delays[attempt])


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def url_failure_counts(failures):
    """Count saved failed attempts by the exact discovered URL, not by domain."""
    return Counter(item['url'] for item in failures if item.get('url')
                   and item.get('status') != 'ok' and (item.get('status') or item.get('error')))


def detail_skip_reason(record, failures=0):
    status=(record or {}).get('status')
    if status in {'ok','blocked','unsupported'}:
        return status
    return 'retry_limit' if failures >= 2 else ''


def access_challenge(result):
    raw=result.get('raw',b'')
    return bool(re.search(rb"(?:var\s+)?arg1\s*=\s*['\"][0-9a-fA-F]{20,}",raw)
                and len(re.findall(r'[\u4e00-\u9fff]',result.get('text','')))<30)


def exact_dates(text):
    result = []
    for match in DATE.finditer(text):
        try:
            value = date(*map(int, match.groups())).isoformat()
        except ValueError:
            continue
        if value not in result:
            result.append(value)
    return result


def publication_date(raw):
    """Only explicit publication evidence, never deadlines or copyright dates."""
    soup = BeautifulSoup(raw, "html.parser")
    names = {"article:published_time", "datepublished", "pubdate", "publishdate", "dc.date.issued", "publish_time"}
    for meta in soup.find_all("meta"):
        if (meta.get("property") or meta.get("name") or "").lower() in names:
            found = exact_dates(meta.get("content", ""))
            if len(found) == 1:
                return found[0]
    for node in soup.select("time[datetime], [itemprop='datePublished']"):
        found = exact_dates(node.get("datetime") or node.get("content") or node.get_text(" ", strip=True))
        if len(found) == 1:
            return found[0]
    for string in soup.find_all(string=re.compile(r"发布日期|发布时间|发稿时间")):
        text = string.parent.get_text(" ", strip=True)
        match = re.search(r"(?:发布日期|发布时间|发稿时间)\s*[:：]?\s*([\d年月日 ./:-]{8,35})", text)
        if match:
            found = exact_dates(match.group(1))
            if len(found) == 1:
                return found[0]
    for node in soup.select(".publish-time,.publish-date,.article-date,.news-date,.pubdate,.pubtime,.article-head .info,.cont-tit.wl"):
        found = exact_dates(node.get_text(" ", strip=True))
        if len(found) == 1:
            return found[0]
    return ""


def canonical(url, base="", keep_fragment=False):
    original = urljoin(base, html_lib.unescape(str(url).strip()))
    normalized = normalize_url(original)
    if normalized and keep_fragment and urlsplit(original).fragment:
        return normalized + "#" + urlsplit(original).fragment
    return normalized


def same_site_host(first, second):
    """Accept only the observed bare-host/www spelling of the same site."""
    def bare(value):
        value=(value or '').lower()
        return value[4:] if value.startswith('www.') else value
    return bool(first and second and bare(first)==bare(second))


def extract_listing(raw, page_url):
    """Associate a date only with a single-announcement DOM row."""
    soup = BeautifulSoup(raw, "html.parser")
    host = urlsplit(page_url).hostname
    page_title = soup.title.get_text(' ',strip=True) if soup.title else ''
    procurement_context = bool(re.search(r'招标|招采|采购|zhaobiao|zbcg|caigou',page_title+' '+urlsplit(page_url).path,re.I))
    found = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "").strip()
        if href.startswith(("#", "javascript:", "mailto:")):
            continue
        target = canonical(href, page_url)
        if not target or not same_site_host(urlsplit(target).hostname,host) or target == canonical(page_url):
            continue
        title = (anchor.get("title") or anchor.get_text(" ", strip=True)).strip()
        stamp = anchor.select_one('time,.time,.date,.news_time,.news-date,.publish-date')
        anchor_date = ''
        if stamp:
            dates = exact_dates(stamp.get('datetime') or stamp.get_text(' ',strip=True))
            if len(dates)==1:
                anchor_date=dates[0]
                if not anchor.get('title'):
                    title=title.replace(stamp.get_text(' ',strip=True),'').strip()
        if not title:
            row = anchor.find_parent(["li", "article"])
            heading = row.find(["h2", "h3", "h4"]) if row else None
            title = heading.get_text(" ", strip=True) if heading else ""
        if len(title) < 6:
            continue
        row_date = anchor_date
        for parent in ([] if row_date else list(anchor.parents)[:5]):
            if parent.name not in {"li", "tr", "article", "div"}:
                continue
            row_text = parent.get_text(" ", strip=True)
            if len(row_text) > 1600:
                break
            row_urls = {canonical(a.get("href"), page_url) for a in parent.find_all("a", href=True)
                        if ANNOUNCE.search(a.get("title") or a.get_text(" ", strip=True))
                        or (procurement_context and len(a.get("title") or a.get_text(" ",strip=True))>=6)}
            if row_urls == {target}:
                dates = exact_dates(row_text)
                if len(dates) == 1:
                    row_date = dates[0]
                # A row with several dates cannot borrow one from a larger parent.
                if dates:
                    break
            if len(row_urls) > 1:
                break
        item = {"title": title[:1000], "url": target, "date": row_date,
                "date_basis": "exact_listing_row" if row_date else "unknown",
                "listing_url": page_url, "procurement_context":procurement_context}
        if not ANNOUNCE.search(title) and not (procurement_context and row_date and anchor.find_parent(['li','tr'])):
            continue
        if target not in found or (row_date and not found[target]["date"]):
            found[target] = item
    return list(found.values())


def next_pages(raw, page_url):
    """Only observed next-page links; never a last-page jump or URL guessing."""
    soup = BeautifulSoup(raw, "html.parser")
    host = urlsplit(page_url).hostname
    result = []
    for anchor in soup.find_all("a"):
        title = anchor.get_text(" ", strip=True).lower()
        label = (anchor.get("aria-label") or anchor.get("title") or "").lower()
        rel = anchor.get("rel", [])
        is_next = title in {"下一页", "下页", "后一页", "next", "next page", ">", "›", "»"} or label in {"下一页", "next", "next page"} or "next" in rel
        if not is_next or "disabled" in " ".join(anchor.get("class", [])).lower() or anchor.get("aria-disabled", "").lower() == "true":
            continue
        href = anchor.get("href", "")
        if not href or href.startswith(("#", "javascript:")):
            # A constant path in this observed pager function is an HTML link;
            # extract the literal only, never execute script expressions.
            onclick=anchor.get('onclick','').strip()
            literal=re.fullmatch(r"queryArticleByCondition\(\s*this\s*,\s*(['\"])([^'\"]+)\1\s*\)\s*;?",onclick)
            href=literal.group(2) if literal else ''
        if not href or href.startswith(("#", "javascript:")):
            continue
        target = canonical(href, page_url)
        if target and target != canonical(page_url) and same_site_host(urlsplit(target).hostname,host) and target not in result:
            result.append(target)
    return result


def normalize_title(value):
    return re.sub(r"[^\w\u4e00-\u9fff]", "", html_lib.unescape(value)).lower()


def cache_title_matches(expected, raw):
    """Old filenames truncated paths; verify content to reject collisions."""
    expected = re.sub(r"^[\d\s.年月日/-]+", "", expected)
    target = normalize_title(expected)
    if len(target) < 10:
        return False
    soup = BeautifulSoup(raw, "html.parser")
    headings = [node.get_text(" ", strip=True) for node in soup.select("h1,h2,.article-title,.news-title,.detail-title,title")]
    for heading in headings:
        candidate = normalize_title(heading)
        if len(candidate) >= 10 and (target in candidate or candidate in target):
            return True
        if len(target) >= 20 and target[:30] in candidate:
            return True
    # Some pages have generic HTML titles. Require the full announcement title
    # near the start of the visible body, not a short shared keyword prefix.
    body = normalize_title((soup.body or soup).get_text(" ", strip=True))[:1200]
    return len(target) >= 15 and len(target) <= 200 and target in body


def legacy_items(site):
    paths = []
    for batch in ("batch-20261028", "try3", "try4", "try5"):
        directory = ARCHIVE / batch / site
        if directory.exists():
            paths.extend(directory.rglob("items.csv"))
    if site == "C0057":
        paths.append(ARCHIVE / "pilot-puh3-v4/list_items.csv")
    result = {}
    for path in paths:
        if not path.is_file():
            continue
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for item in csv.DictReader(handle):
                url = canonical(item.get("url", ""), keep_fragment=True)
                title = item.get("title", "")
                if not url or not title:
                    continue
                source = None
                if path.name == "list_items.csv":
                    segment = urlsplit(url).path.rsplit("/", 1)[-1].replace(".htm", "")
                    candidate = path.parent / "detail" / (segment + "_htm")
                    if candidate.is_file():
                        source = candidate
                else:
                    safe = re.sub(r"[^0-9A-Za-z]", "", urlsplit(url).path)[-24:]
                    candidate = path.parent / "details" / (safe + ".html")
                    if urlsplit(url).fragment.startswith("details_"):
                        candidate = path.parent / "details" / (urlsplit(url).fragment + ".html")
                    if candidate.is_file():
                        source = candidate
                existing = result.get(url)
                if existing and existing.get("cache_path") and not source:
                    continue
                result[url] = {"title": title, "url": url, "date": "", "date_basis": "legacy_listing_unverified",
                               "legacy_date_unverified": item.get("date", ""), "legacy_index": str(path),
                               "cache_path": str(source) if source else ""}
    return result


class Collector:
    def __init__(self, entry, args):
        self.entry, self.args = entry, args
        self.directory = lp(Path(args.output) / "sites" / entry["task_id"])
        self.directory.mkdir(parents=True, exist_ok=True)
        self.raw_dir = self.directory / "raw"
        self.raw_dir.mkdir(exist_ok=True)
        host=urlsplit(entry['url']).hostname
        bare=host[4:] if host.startswith('www.') else host
        self.domains = [bare,'www.'+bare]
        self.fetcher = Fetcher(timeout=10, retries=0, delay=1, max_bytes=3 * 1024 * 1024, transport="auto")
        self.records = {}
        if (self.directory / "pages.json").exists():
            self.records = {p["url"]: p for p in read_json(self.directory / "pages.json")}
        self.pages_log = read_json(self.directory/'list_pages.json') if (self.directory/'list_pages.json').exists() else []
        previous = read_json(self.directory/'summary.json') if (self.directory/'summary.json').exists() else {}
        self.failures = list(previous.get('failures',[]))
        self.failure_counts = url_failure_counts(self.failures)
        self.gaps = set()
        self.started = time.monotonic()
        self.new_details = 0
        self.list_requests = 0
        self.cache_hits = 0
        self.attachments_requested = 0
        self.skipped_details = Counter()
        self.unfetched_non_digital_titles = 0
        self.pending_list_urls = 0

    def log(self, message):
        print(f"[{now()}] {self.entry['task_id']} {message}", flush=True)

    def expired(self):
        if time.monotonic() - self.started >= self.args.max_site_seconds:
            self.gaps.add("site_time_budget_reached")
            return True
        return False

    def checkpoint(self):
        write_json(self.directory / "pages.json", list(self.records.values()))
        write_json(self.directory / "progress.json", {"task_id": self.entry["task_id"], "updated_at": now(),
                   "status": "running", "list_requests": self.list_requests, "new_details": self.new_details,
                   "cache_hits": self.cache_hits, "records": len(self.records), "gaps": sorted(self.gaps),
                   "details_only":getattr(self.args,'details_only',False),
                   "digital_titles_only":getattr(self.args,'digital_titles_only',False),
                   "pending_list_urls":self.pending_list_urls,
                   "unfetched_non_digital_titles":self.unfetched_non_digital_titles,
                   "skipped_details":dict(self.skipped_details)})

    def save_raw(self, url, raw, text="", suffix="html"):
        key = hashlib.sha256(url.encode()).hexdigest()[:24]
        path = self.raw_dir / (key + "." + suffix)
        path.write_bytes(raw)
        text_path = self.raw_dir / (key + ".txt")
        text_path.write_text(text or "", encoding="utf-8")
        return str(path), str(text_path), hashlib.sha256(raw).hexdigest()

    def record(self, item, result, provenance):
        raw = result.get("raw", b"")
        text = result.get("text", "")
        pubdate = publication_date(raw) if raw and not raw.startswith(b"%PDF") else ""
        listing_date = item.get("date", "") if item.get("date_basis") == "exact_listing_row" else ""
        actual_date = pubdate or listing_date
        basis = "detail_publication" if pubdate else "exact_listing_row" if listing_date else "unknown"
        old = self.records.get(item["url"], {})
        raw_path, text_path, digest = self.save_raw(item["url"], raw, text) if raw else (old.get("raw_path", ""), old.get("text_path", ""), old.get("sha256", ""))
        association = False  # The extractor must establish the actual purchasing entity.
        hospital = self.entry["hospital"]
        record = {"task_id": self.entry["task_id"], "hospital": hospital,
                  "hospital_ids": self.entry.get("hospital_ids", ""), "title": item["title"], "url": item["url"],
                  "date": actual_date, "date_basis": basis, "raw_path": raw_path, "text_path": text_path,
                  "status": result.get("status", "error"), "error": result.get("error", ""),
                  "provenance": provenance, "fetched_at": now() if provenance.get("kind") == "live_http" else "",
                  "processed_at": now(), "sha256": digest,
                  "association_verified": association,
                  "hospital_region": self.entry.get("province", ""),
                  "province": self.entry.get("province", ""),
                  "hospital_entities": self.entry.get("hospital_entities", []),
                  "entrance_verified": self.entry.get("entrance_verified", False),
                  "procurement_context": item.get("procurement_context", False),
                  "attachments": old.get("attachments", []), "listing_url": item.get("listing_url", ""),
                  "legacy_date_unverified": item.get("legacy_date_unverified", ""),
                  "in_date_range": self.args.since <= actual_date <= self.args.until if actual_date else None}
        if listing_date:
            record.update(listing_date=listing_date,
                          listing_date_source_path=item.get('listing_raw_path') or item.get('date_source_path',''),
                          listing_date_source_sha256=item.get('listing_sha256') or item.get('date_source_sha256',''))
        if basis=='exact_listing_row':
            record.update(date_source_path=record.get('listing_date_source_path',''),
                          date_source_sha256=record.get('listing_date_source_sha256',''),
                          date_evidence=item.get('date_evidence',''))
        if not actual_date:
            self.gaps.add("undated_announcements_require_review")
        self.records[item["url"]] = record
        self.checkpoint()
        return record

    def attachments(self, record, raw):
        if not raw or raw.startswith(b"%PDF"):
            return
        soup = BeautifulSoup(raw, "html.parser")
        found = []
        for a in soup.find_all("a", href=True):
            url = canonical(a["href"], record["url"])
            label = a.get_text(" ", strip=True)
            if not url or not (ATTACHMENT.search(url) or re.search(r"附件|下载.*文件|资格预审文件|采购文件下载", label)):
                continue
            if url in {x["url"] for x in found}:
                continue
            item = {"url": url, "title": label, "status": "not_fetched", "raw_path": "", "text_path": ""}
            if not is_allowed_url(url, self.domains):
                item["status"] = "external_domain_not_fetched"
            elif len(found) >= 3 or self.expired():
                item["status"] = "attachment_budget_reached"
            else:
                self.log("attachment " + url)
                result = self.fetcher.fetch(url, self.domains)
                self.attachments_requested += 1
                item.update(status=result["status"], error=result.get("error", ""))
                if result.get("raw"):
                    suffix = "pdf" if result["raw"].startswith(b"%PDF") else "bin"
                    raw_path, text_path, digest = self.save_raw(url, result["raw"], result.get("text", ""), suffix)
                    item.update(raw_path=raw_path, text_path=text_path, sha256=digest)
            if item["status"] != "ok":
                self.gaps.add("attachments_incomplete_or_need_OCR")
            found.append(item)
        record["attachments"] = found
        self.checkpoint()

    def run(self):
        contract = {"task_id": self.entry["task_id"], "entry_url": self.entry["url"],
                    "since": self.args.since, "until": self.args.until, "scope": self.args.scope, "schema_version": 1}
        contract_file = self.directory / "contract.json"
        if contract_file.exists() and read_json(contract_file) != contract:
            raise ValueError("Site contract changed; use a new output run directory")
        write_json(contract_file, contract)
        prior_items = self.directory / "discovered_items.json"
        candidates = {x["url"]: x for x in read_json(prior_items)} if prior_items.exists() else {}
        self.log(f"resume {len(candidates)} previously discovered announcements")
        # Reparse the preserved lists after parser improvements, without another
        # network request or discarding their original evidence.
        logs = self.directory/'list_pages.json'
        if logs.exists() and not getattr(self.args,'details_only',False):
            for row in read_json(logs):
                if row.get('status')=='ok' and row.get('raw_path') and lp(row['raw_path']).exists():
                    for item in extract_listing(lp(row['raw_path']).read_bytes(),row['url']):
                        item.update(listing_raw_path=row['raw_path'],listing_sha256=row.get('sha256',''))
                        candidates[item['url']]={**candidates.get(item['url'],{}),**item}
                        existing=self.records.get(item['url'])
                        if existing:
                            existing['procurement_context']=existing.get('procurement_context',False) or item.get('procurement_context',False)
                            if item.get('date_basis')=='exact_listing_row' and existing.get('date_basis')!='detail_publication':
                                existing.update(date=item['date'],date_basis='exact_listing_row',listing_url=item['listing_url'],
                                                date_source_path=row['raw_path'],date_source_sha256=row.get('sha256',''),
                                                in_date_range=self.args.since<=item['date']<=self.args.until)
        # Import immutable saved detail evidence before spending the network budget.
        for url, item in candidates.items():
            existing = self.records.get(url)
            if detail_skip_reason(existing,self.failure_counts[url]):
                continue
            if getattr(self.args,'digital_titles_only',False) and not digital_hits(item.get('title','')):
                continue
            if not item.get("cache_path"):
                continue
            raw = lp(item["cache_path"]).read_bytes()
            if not cache_title_matches(item["title"], raw):
                self.gaps.add("legacy_filename_collision_or_title_mismatch")
                continue
            parsed = Fetcher.extract_cached(raw, {"url": url, "content_type": "text/html", "http_status": 200}, self.domains)
            self.record(item, parsed, {"kind": "historical_cache", "source": item["cache_path"], "source_sha256": hashlib.sha256(raw).hexdigest(),
                                      "legacy_index": item["legacy_index"], "current_network_verified": False})
            self.cache_hits += 1
            self.log(f"cache accepted {self.cache_hits}: {item['title'][:70]}")
        state_file = self.directory / "listing_state.json"
        state = read_json(state_file) if state_file.exists() else {}
        queue = list(state.get("pending", [])) if state else [canonical(self.entry["url"])]
        visited = set(state.get("visited", []))
        while queue and not getattr(self.args,'details_only',False) and self.list_requests < self.args.max_list_pages and not self.expired():
            # Leave most of each pass available for full texts and attachments.
            if time.monotonic() - self.started >= self.args.max_site_seconds * 0.32:
                break
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            self.log(f"list {self.list_requests + 1}: {url}")
            result = self.fetcher.fetch(url, self.domains)
            if access_challenge(result):
                result.update(status='blocked',error='访问挑战页；未执行挑战或绕过访问控制')
            self.list_requests += 1
            log = {"url": url, "status": result["status"], "error": result.get("error", ""), "fetched_at": now(),"content_chars":len(result.get('text',''))}
            if result.get("raw"):
                log["raw_path"], log["text_path"], log["sha256"] = self.save_raw(url, result["raw"], result.get("text", ""))
            self.pages_log.append(log)
            write_json(self.directory / "list_pages.json", self.pages_log)
            if result["status"] != "ok":
                self.failures.append(log)
                self.gaps.add("entry_or_pagination_" + result["status"])
                continue
            doc = BeautifulSoup(result.get('raw',b''),'html.parser')
            doc_title = doc.title.get_text(' ',strip=True) if doc.title else ''
            if re.search(r'影院|影视大全|电影在线观看|小说.*阅读|娱乐城|博彩|色情',doc_title) and not re.search(r'医院|卫生|医疗|采购|招标',doc_title):
                self.gaps.add('hospital_identity_mismatch')
                self.failures.append({'url':url,'status':'identity_mismatch','error':'旧入口内容已非医院或采购网站：'+doc_title})
                queue=[]
                break
            items = extract_listing(result.get("raw", b""), result["url"])
            self.log(f"list contains {len(items)} announcement links")
            for item in items:
                old = candidates.get(item["url"], {})
                candidates[item["url"]] = {**old, **item}
                if item["date"] and item["url"] in self.records:
                    record = self.records[item["url"]]
                    if record["date_basis"] != "detail_publication":
                        record.update(date=item["date"], date_basis="exact_listing_row", listing_url=item["listing_url"],
                                      in_date_range=self.args.since <= item["date"] <= self.args.until)
            following = next_pages(result.get("raw", b""), result["url"])
            exact_row_dates = [x['date'] for x in items if x.get('date_basis')=='exact_listing_row' and x.get('date')]
            if len(exact_row_dates)>=5 and len(exact_row_dates)==len(items) and max(exact_row_dates)<self.args.since:
                # All explicitly dated rows on this page precede the requested
                # interval. This is a stopping boundary, not a completeness claim.
                following=[]
                self.gaps.add('listing_reached_before_since')
            if self.list_requests == 1 and not state:
                for link in result.get("links", []):
                    label = re.sub(r"\s+", "", link.get("text", ""))
                    nav_pattern = r"招标|招采|采购|中标|成交" if self.entry.get('entry_kind')=='procurement_column' else r"招标|招采|采购|中标|成交|院务公开|信息公开|通知公告"
                    if 2 <= len(label) <= 14 and re.search(nav_pattern, label):
                        target = canonical(link.get("url", ""), result["url"])
                        if target and is_allowed_url(target, self.domains) and not ATTACHMENT.search(target):
                            following.append(target)
            for nxt in following:
                if nxt not in visited and nxt not in queue:
                    queue.append(nxt)
            if not items and self.list_requests == 1:
                self.gaps.add("no_static_listing_or_JS_required")
                for link in result.get("links", []):
                    if len(link.get("text", "")) <= 14 and ANNOUNCE.search(link.get("text", "")) and link["url"] not in visited:
                        queue.append(link["url"])
                        if len(queue) >= 3:
                            break
            self.checkpoint()
            write_json(prior_items, list(candidates.values()))
            write_json(state_file, {"pending": queue, "visited": sorted(visited)})
        if queue:
            self.gaps.add("pending_lists_not_visited_in_details_only_pass" if getattr(self.args,'details_only',False)
                          else "list_page_or_time_budget_reached")
        self.pending_list_urls=len(queue)
        write_json(state_file, {"pending": queue, "visited": sorted(visited)})
        write_json(self.directory / "discovered_items.json", list(candidates.values()))
        # Normally titles only prioritize the network budget. The explicitly
        # requested final targeted pass retains non-IT-title omissions as gaps.
        pending = sorted(candidates.values(), key=lambda x: (
            bool(digital_hits(x["title"])) if self.args.scope == "digital" else True,
            x.get("date") or "0000"), reverse=True)
        eligible=[]
        for item in pending:
            if item.get("date_basis") == "exact_listing_row" and item.get("date") and not self.args.since <= item["date"] <= self.args.until:
                continue
            reason=detail_skip_reason(self.records.get(item['url']),self.failure_counts[item['url']])
            if reason:
                self.skipped_details[reason]+=1
                if reason!='ok':self.gaps.add('detail_retry_limit_reached' if reason=='retry_limit' else 'detail_previously_'+reason)
                continue
            if getattr(self.args,'digital_titles_only',False) and not digital_hits(item.get('title','')):
                self.unfetched_non_digital_titles+=1
                continue
            eligible.append(item)
        if self.unfetched_non_digital_titles:
            self.gaps.add('non_digital_titles_not_fetched_in_targeted_pass')
        for item in eligible:
            if self.expired() or self.new_details >= self.args.max_new_details:
                self.gaps.add("detail_or_time_budget_reached")
                break
            if "#" in item["url"]:
                self.record(item, {"status": "needs_rendering", "error": "Legacy inline/API detail requires site adapter"}, {"kind": "not_fetched"})
                self.gaps.add("inline_or_API_detail_requires_adapter")
                continue
            if not is_allowed_url(item["url"], self.domains):
                self.record(item, {"status": "blocked", "error": "Announcement outside hospital domain"}, {"kind": "not_fetched"})
                continue
            self.log(f"detail {self.new_details + 1}: {item['url']}")
            result = self.fetcher.fetch(item["url"], self.domains)
            challenged=access_challenge(result)
            if challenged:result.update(status='blocked',error='访问挑战页；停止本站后续详情请求，保留未访问线索')
            self.new_details += 1
            record = self.record(item, result, {"kind": "live_http", "requested_url": item["url"], "current_network_verified": result["status"] == "ok"})
            if result["status"] == "ok":
                self.attachments(record, result.get("raw", b""))
            else:
                self.failures.append({"url": item["url"], "status": result["status"], "error": result.get("error", "")})
                self.failure_counts[item['url']]+=1
                self.gaps.add("detail_fetch_failures")
                if self.failure_counts[item['url']]>=2:self.gaps.add('detail_retry_limit_reached')
                if challenged:
                    self.gaps.add('detail_access_challenge')
                    break
        # Cached details may contain qualification documents that were never saved.
        for record in self.records.values():
            if getattr(self.args,'digital_titles_only',False) and not digital_hits(record.get('title','')):
                continue
            if self.expired():
                break
            if record.get("status") == "ok" and record.get("raw_path") and not record.get("attachments"):
                self.attachments(record, lp(record["raw_path"]).read_bytes())
        self.gaps.add("historical_coverage_not_proven")
        if self.args.scope == "digital":
            self.gaps.add("digital_scope_requires_full_text_extractor")
        self.checkpoint()
        return self.finish()

    def finish(self, fatal=None):
        records = list(self.records.values())
        if fatal:
            self.gaps.add("collector_exception")
            self.failures.append({"error": str(fatal)})
        usable = any(p.get('status')=='ok' for p in records) or any(p.get('status')=='ok' and p.get('content_chars',0)>60 for p in self.pages_log)
        summary = {"task_id": self.entry["task_id"], "hospital": self.entry["hospital"],
                   "hospital_ids": self.entry.get("hospital_ids", ""), "entry_url": self.entry["url"],
                   "since": self.args.since, "until": self.args.until, "scope": self.args.scope,
                   "status": "entry_pending" if 'hospital_identity_mismatch' in self.gaps else "partial" if usable else "failed", "coverage_complete": False,
                   "updated_at": now(), "list_requests": len(self.pages_log), "list_requests_this_pass":self.list_requests,"new_details": self.new_details,
                   "attachments_requested": self.attachments_requested, "cache_hits": self.cache_hits,
                   "details_only":getattr(self.args,'details_only',False),
                   "digital_titles_only":getattr(self.args,'digital_titles_only',False),
                   "pending_list_urls":self.pending_list_urls,
                   "unfetched_non_digital_titles":self.unfetched_non_digital_titles,
                   "skipped_details":dict(self.skipped_details),
                   "records": len(records), "successful_details": sum(p["status"] == "ok" for p in records),
                   "dated_in_range": sum(p.get("in_date_range") is True for p in records),
                   "unknown_dates": sum(not p.get("date") for p in records),
                   "gaps": sorted(self.gaps), "failures": self.failures, "elapsed_seconds": round(time.monotonic() - self.started, 2),
                   "note": "已保存内容可交付；日期未知单列。入口访问或预算完成不代表2024年以来全量覆盖。"}
        write_json(self.directory / "pages.json", records)
        write_json(self.directory / "summary.json", summary)
        write_json(self.directory / "progress.json", summary)
        self.log("finished " + json.dumps({k: summary[k] for k in ("status", "records", "dated_in_range", "unknown_dates", "gaps")}, ensure_ascii=False))
        return 3 if summary["status"] == "partial" else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True)
    parser.add_argument("--entrances", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--since", default="2024-01-01")
    parser.add_argument("--until", default="2026-11-03")
    parser.add_argument("--scope", choices=("all", "digital"), default="all")
    parser.add_argument("--max-list-pages", type=int, default=80)
    parser.add_argument("--max-new-details", type=int, default=300)
    parser.add_argument("--max-site-seconds", type=int, default=180)
    parser.add_argument("--details-only",action="store_true",help="Use discovered details only; preserve pending lists and skip list reparsing")
    parser.add_argument("--digital-titles-only",action="store_true",help="Fetch only discovered titles with digital keywords; record omitted-title gaps")
    parser.add_argument("--dry-run", action="store_true", help="Validate input only; no network calls or file writes")
    args = parser.parse_args()
    if not re.fullmatch(r"(?:S\d{5}|N[0-9a-f]{12})", args.site):
        parser.error("Invalid site id")
    try:
        if date.fromisoformat(args.since) > date.fromisoformat(args.until):
            raise ValueError("Invalid date interval")
    except ValueError as exc:
        parser.error(str(exc))
    if min(args.max_list_pages, args.max_new_details, args.max_site_seconds) < 1:
        parser.error("All budgets must be positive")
    data = read_json(args.entrances)
    entries = data.get("entrances", []) if isinstance(data, dict) else data
    matches = [e for e in entries if e.get("task_id") == args.site]
    if len(matches) != 1 or not matches[0].get("hospital"):
        parser.error("Expected exactly one named hospital entrance for site")
    entry = matches[0]
    # A verified homepage is a discovery entry, not a known historical archive.
    # Give its first pass a smaller budget; saved procurement queues can then
    # receive a dedicated continuation with the normal budget.
    if entry.get('entry_kind') == 'verified_homepage' and not (Path(args.output)/'sites'/args.site/'contract.json').exists():
        args.max_site_seconds = min(args.max_site_seconds, 70)
        args.max_list_pages = min(args.max_list_pages, 8)
    entry_url = canonical(entry.get("url", ""))
    if not entry_url or not urlsplit(entry_url).hostname:
        parser.error("Invalid HTTP(S) entrance URL")
    if args.dry_run:
        print(json.dumps({"valid": True, "task_id": args.site, "hospital": entry["hospital"],
                          "entry_url": entry_url, "since": args.since, "until": args.until, "scope": args.scope,
                          "output": str(Path(args.output).absolute() / "sites" / args.site),
                          "details_only":args.details_only,"digital_titles_only":args.digital_titles_only,
                          "budgets": {"max_list_pages": args.max_list_pages, "max_new_details": args.max_new_details,
                                      "max_site_seconds": args.max_site_seconds},
                          "network_calls": 0, "files_written": 0}, ensure_ascii=False))
        return 0
    collector = Collector(entry, args)
    lock = collector.directory / "collector.lock"
    try:
        with lock.open("x", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "started_at": now()}, handle)
    except FileExistsError:
        print("Site already locked; inspect the running task before resuming", file=sys.stderr)
        return 2
    try:
        return collector.run()
    except Exception as exc:
        return collector.finish(f"{type(exc).__name__}: {exc}")
    finally:
        collector.fetcher.close()
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
