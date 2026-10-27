"""Bounded, robots-aware retrieval of public research sources.

This module never disables TLS validation or retries access denials.  A Fetcher
is intended for sequential use; tests may replace its public ``session`` with a
requests-compatible fake.  Successful responses include ``raw`` bytes for the
caller to archive and remove before serializing the remaining result.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from io import BytesIO
import ipaddress
import re
import socket
import time
from urllib.parse import unquote_plus, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

USER_AGENT = "CAICTMedicalResearchBot/1.0 (public-source research; Python requests)"
ROBOT_AGENT = "CAICTMedicalResearchBot"
_TRACKERS = {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "_ga", "spm"}
_REDIRECTS = {301, 302, 303, 307, 308}
_TRANSIENT = {408, 500, 502, 503, 504}


def normalize_url(url: str) -> str:
    """Normalize public HTTP URLs without discarding business query parameters."""
    try:
        parts = urlsplit(str(url).strip())
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return ""
        if parts.username is not None or parts.password is not None:
            return ""
        host = parts.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        port = parts.port
        netloc = f"[{host}]" if ":" in host else host
        if port is not None and port != (443 if parts.scheme.lower() == "https" else 80):
            netloc += f":{port}"
        query = []
        for component in parts.query.split("&"):
            key = unquote_plus(component.split("=", 1)[0]).lower()
            if not key.startswith("utm_") and key not in _TRACKERS:
                query.append(component)
        return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", "&".join(query), ""))
    except (ValueError, UnicodeError):
        return ""


def _public_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # Reject alternate numeric IP spellings (127.1, 2130706433, 0x7f000001).
        return "." in host and not re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*", host, re.I)
    return address.is_global and not address.is_multicast


def is_allowed_url(url: str, allowed_domains) -> bool:
    """Check scheme, hostname and domain scope; DNS is checked before requests."""
    normalized = normalize_url(url)
    if not normalized:
        return False
    host = urlsplit(normalized).hostname or ""
    if not _public_host(host):
        return False
    for domain in allowed_domains or ():
        domain = str(domain).strip().lower().lstrip(".")
        if "://" in domain:
            domain = urlsplit(domain).hostname or ""
        domain = domain.rstrip(".")
        try:
            domain = domain.encode("idna").decode("ascii")
        except UnicodeError:
            continue
        if domain and (host == domain or host.endswith("." + domain)):
            return True
    return False


class _FetchFailure(Exception):
    def __init__(self, status, message, http_status=None, url=None):
        super().__init__(message)
        self.status, self.http_status, self.url = status, http_status, url


def _result(requested_url, url=None, **updates):
    result = {"requested_url": requested_url, "url": url or requested_url,
              "title": "", "text": "", "published_at": "", "content_type": "",
              "links": [], "status": "error", "error": "", "http_status": None,
              "method": "http"}
    result.update(updates)
    return result


class Fetcher:
    def __init__(self, timeout=25, retries=1, delay=1.0, browser=False,
                 max_bytes=12 * 1024 * 1024):
        if timeout <= 0 or retries < 0 or delay < 0 or max_bytes <= 0:
            raise ValueError("timeout/max_bytes must be positive; retries/delay cannot be negative")
        self.timeout, self.retries, self.delay = timeout, int(retries), delay
        self.browser, self.max_bytes = browser, int(max_bytes)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT,
                                     "Accept": "text/html,application/pdf,text/plain;q=0.8,*/*;q=0.2"})
        self._robots = {}
        self._last_request = {}
        self._crawl_delay = {}

    def close(self):
        self.session.close()

    def _validate_url(self, url, allowed_domains):
        if not is_allowed_url(url, allowed_domains):
            raise _FetchFailure("blocked", "URL outside allowed public domains", url=url)
        host = urlsplit(url).hostname
        try:
            addresses = socket.getaddrinfo(host, urlsplit(url).port or
                                           (443 if urlsplit(url).scheme == "https" else 80),
                                           type=socket.SOCK_STREAM)
        except OSError as exc:
            raise _FetchFailure("error", f"DNS resolution failed: {exc}", url=url) from exc
        if not addresses or any(not _public_host(item[4][0]) for item in addresses):
            raise _FetchFailure("blocked", "Hostname resolves to a non-public IP address", url=url)

    def _throttle(self, url):
        host = urlsplit(url).hostname
        interval = max(self.delay, self._crawl_delay.get(host, 0))
        remaining = interval - (time.monotonic() - self._last_request.get(host, 0))
        if remaining > 0:
            time.sleep(remaining)
        self._last_request[host] = time.monotonic()

    def _request(self, url):
        for attempt in range(self.retries + 1):
            self._throttle(url)
            try:
                response = self.session.get(url, timeout=self.timeout, stream=True,
                                            allow_redirects=False, verify=True)
            except requests.exceptions.SSLError as exc:
                raise _FetchFailure("error", f"TLS verification failed: {exc}", url=url) from exc
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt < self.retries:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise _FetchFailure("error", f"Request failed: {exc}", url=url) from exc
            except requests.RequestException as exc:
                raise _FetchFailure("error", f"Request failed: {exc}", url=url) from exc
            if response.status_code in _TRANSIENT and attempt < self.retries:
                response.close()
                time.sleep(min(2 ** attempt, 8))
                continue
            return response
        raise AssertionError("retry loop did not return")

    def _read_body(self, response, limit):
        length = response.headers.get("Content-Length", "")
        if str(length).isdigit() and int(length) > limit:
            raise _FetchFailure("error", f"Response exceeds {limit} byte limit", response.status_code)
        body, total = [], 0
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > limit:
                    raise _FetchFailure("error", f"Response exceeds {limit} byte limit", response.status_code)
                body.append(chunk)
        except requests.RequestException as exc:
            raise _FetchFailure("error", f"Response body interrupted: {exc}", response.status_code) from exc
        return b"".join(body)

    def _download(self, url, allowed_domains, check_robots=True, limit=None):
        seen = set()
        for _ in range(9):
            self._validate_url(url, allowed_domains)
            if url in seen:
                raise _FetchFailure("error", "Redirect loop", url=url)
            seen.add(url)
            if check_robots:
                self._check_robots(url, allowed_domains)
            response = self._request(url)
            try:
                status = response.status_code
                if status in _REDIRECTS:
                    location = response.headers.get("Location")
                    if not location:
                        raise _FetchFailure("error", "Redirect has no Location", status, url)
                    destination = normalize_url(urljoin(url, location))
                    if not destination:
                        raise _FetchFailure("blocked", "Invalid redirect destination", status, url)
                    url = destination
                    continue
                headers = dict(response.headers)
                body = self._read_body(response, self.max_bytes if limit is None else limit) if 200 <= status < 300 else b""
                return url, status, headers, body
            finally:
                response.close()
        raise _FetchFailure("error", "Too many redirects (maximum 8)", url=url)

    def _check_robots(self, url, allowed_domains):
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            robot_url = origin + "/robots.txt"
            try:
                final, status, headers, body = self._download(
                    robot_url, allowed_domains, check_robots=False,
                    limit=min(self.max_bytes, 512 * 1024))
                if status in {404, 410}:
                    self._robots[origin] = (None, "", "")
                elif status in {401, 403}:
                    self._robots[origin] = (None, "robots_denied", f"robots.txt returned HTTP {status}")
                elif status == 429:
                    self._robots[origin] = (None, "blocked", "robots.txt returned HTTP 429; no retry")
                elif not 200 <= status < 300:
                    self._robots[origin] = (None, "robots_unavailable", f"robots.txt returned HTTP {status}")
                elif b"<html" in body[:1024].lower() or b"<!doctype html" in body[:1024].lower():
                    self._robots[origin] = (None, "robots_unavailable", "robots.txt returned HTML instead of rules")
                else:
                    parser = RobotFileParser(robot_url)
                    parser.parse(body.decode("utf-8-sig", errors="replace").splitlines())
                    self._robots[origin] = (parser, "", "")
                    delay = parser.crawl_delay(ROBOT_AGENT)
                    if delay is not None:
                        self._crawl_delay[parts.hostname] = max(self.delay, delay)
            except _FetchFailure as exc:
                self._robots[origin] = (None, "robots_unavailable", f"robots.txt check failed: {exc}")
        parser, status, error = self._robots[origin]
        if status:
            raise _FetchFailure(status, error, url=url)
        if parser is not None and not parser.can_fetch(ROBOT_AGENT, url):
            raise _FetchFailure("robots_denied", "Disallowed by robots.txt", url=url)

    def fetch(self, url, allowed_domains):
        requested_url = str(url)
        normalized = normalize_url(url)
        if not normalized:
            return _result(requested_url, status="blocked", error="Invalid HTTP(S) URL")
        try:
            final, status, headers, body = self._download(normalized, allowed_domains)
        except _FetchFailure as exc:
            return _result(requested_url, exc.url or normalized, status=exc.status,
                           error=str(exc), http_status=exc.http_status)
        result = _result(requested_url, final, http_status=status)
        content_type = next((v for k, v in headers.items() if k.lower() == "content-type"), "")
        result["content_type"] = content_type
        result = self.extract_cached(body, result, allowed_domains)
        if self.browser and result["status"] == "empty" and result["error"].startswith("JavaScript shell"):
            return self._render_browser(result, allowed_domains)
        return result

    @classmethod
    def extract_cached(cls, body, metadata, allowed_domains):
        """Parse archived bytes only; no HTTP, DNS, robots or browser activity.

        ``metadata`` supplies requested_url, url, http_status and content_type.
        Missing HTTP status is treated as 200 for an already archived body.
        """
        status = metadata.get("http_status") or 200
        result = _result(metadata.get("requested_url", metadata.get("url", "")),
                         metadata.get("url"), http_status=status,
                         method=metadata.get("method", "http"))
        content_type = metadata.get("content_type") or ""
        result["content_type"] = content_type.split(";", 1)[0].strip().lower()
        if status in {401, 403, 429}:
            return dict(result, status="blocked", error=f"HTTP {status}; access denial is not retried or bypassed")
        if not 200 <= status < 300:
            return dict(result, status="error", error=f"HTTP {status}")
        result["raw"] = body
        if not body.strip():
            return dict(result, status="empty", error="Empty response body")
        if body.lstrip().startswith(b"%PDF-") or result["content_type"] == "application/pdf":
            return cls._extract_pdf(body, result)
        if result["content_type"] not in {"", "text/html", "application/xhtml+xml", "text/plain"}:
            return dict(result, status="unsupported", error=f"Unsupported content type: {result['content_type']}")
        if result["content_type"] == "text/plain" and b"<html" not in body[:1024].lower():
            return dict(result, status="ok", text=body.decode("utf-8-sig", errors="replace").strip())
        result = cls._extract_html(body, result, allowed_domains, content_type)
        if result["status"] == "blocked":
            return result
        if cls._is_js_shell(body, result["text"]):
            return dict(result, status="empty", error="JavaScript shell; enable browser rendering to extract content")
        return result

    @staticmethod
    def _is_js_shell(body, text):
        if len(text) >= 160:
            return False
        html = body.decode("utf-8", errors="ignore").lower()
        return (bool(re.search(r'id=[\"\'](?:app|root|__next)[\"\']', html)) and "<script" in html
                or any(term in html for term in ("enable javascript", "请开启javascript", "请启用javascript")))

    @staticmethod
    def _date(soup):
        candidates = []
        for name in ("article:published_time", "datepublished", "pubdate", "publishdate", "date", "dc.date.issued"):
            for meta in soup.find_all("meta"):
                if (meta.get("property") or meta.get("name") or "").lower() == name:
                    candidates.append(meta.get("content", ""))
        for node in soup.select("time[datetime], [itemprop='datePublished']"):
            candidates.append(node.get("datetime") or node.get("content") or node.get_text(" ", strip=True))
        for node in soup.select(".publish-time,.publish-date,.article-date,.news-date,.mr-innovation-detail-kv-date-text"):
            candidates.append(node.get_text(" ", strip=True))
        # A date in a URL, a footer copyright or a generic number is not evidence.
        for text in soup.find_all(string=re.compile(r"发布时间|发布日期|发稿时间|Published\s*(?:on|:)", re.I)):
            candidates.append(text.parent.get_text(" ", strip=True)[:300])
        for candidate in candidates:
            match = re.search(r"(?<!\d)(20\d{2}|19\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})(?:日)?", candidate)
            if match:
                try:
                    return datetime(*map(int, match.groups())).date().isoformat()
                except ValueError:
                    pass
        return ""

    @classmethod
    def _extract_html(cls, body, result, allowed_domains, content_type=""):
        charset = re.search(r"charset\s*=\s*[\"']?([^;\s\"']+)", content_type, re.I)
        encoding = charset.group(1) if charset else None
        # Python's gb18030 decoder covers modern and older Chinese encodings.
        if encoding and encoding.lower() in {"gb2312", "gbk"}:
            encoding = "gb18030"
        soup = BeautifulSoup(body, "html.parser", from_encoding=encoding)
        # Some CMSs ship real, static article paragraphs inside delayed templates
        # (e.g. Mindray consent-controlled components). Reparse those paragraphs
        # as ordinary nodes; unresolved client-side templates remain excluded.
        for template in soup.find_all("template"):
            if template.parent is None:
                continue
            fragment = BeautifulSoup(template.decode_contents(), "html.parser")
            for node in fragment.select("script,style,noscript"):
                node.decompose()
            static_text = fragment.get_text(" ", strip=True)
            if fragment.find(["p", "article", "section"]) and len(static_text) >= 80 and "{{" not in static_text:
                for child in list(fragment.contents):
                    template.insert_before(child)
            template.decompose()
        title_node = soup.find("h1") or soup.find("title")
        title = title_node.get_text(" ", strip=True) if title_node else ""
        evidence_text = soup.get_text(" ", strip=True)
        challenge_terms = ("just a moment", "checking your browser", "verify you are human", "access denied", "人机验证", "访问验证", "访问过于频繁")
        if len(evidence_text) < 1500 and any(term in (title + " " + evidence_text).lower() for term in challenge_terms):
            return dict(result, title=title, status="blocked", error="Access challenge detected; no bypass attempted")
        published_at = cls._date(soup)
        links, seen = [], set()
        for anchor in soup.find_all("a", href=True):
            target = normalize_url(urljoin(result["url"], anchor["href"]))
            if target and target not in seen and is_allowed_url(target, allowed_domains):
                seen.add(target)
                links.append({"url": target, "text": anchor.get_text(" ", strip=True)})
        for node in soup.select("script,style,noscript,nav,footer,header,aside,form,iframe,svg,canvas,template,[hidden],[aria-hidden='true'],.cookies-section,.cookie-banner,.cookie-consent,.cookie-notice,.mr-cookies-modal,#chooseCookies,#cookieErrorModal,[id^='onetrust-']"):
            node.decompose()
        candidates = soup.select("article,main,[role='main'],#article,#content,.article-content,.article_content,.article-body,.news-content,.news_content,.detail-content,.TRS_Editor")
        content = max(candidates, key=lambda node: len(node.get_text(" ", strip=True)), default=soup.body or soup)
        # Preserve paragraph/heading/list boundaries while keeping inline spans joined.
        for node in content.find_all("br"):
            node.replace_with("\n")
        for node in content.find_all(["p", "div", "section", "h1", "h2", "h3", "h4", "li", "tr"]):
            node.insert_before("\n")
            node.insert_after("\n")
        lines = [re.sub(r"[\t\r\f\v ]+", " ", line).strip() for line in content.get_text().splitlines()]
        text = "\n".join(line for line in lines if line)
        return dict(result, title=title, text=text, published_at=published_at, links=links,
                    status="ok" if text else "empty", error="" if text else "No extractable HTML text")

    @staticmethod
    def _extract_pdf(body, result):
        result = dict(result, method="pdf", content_type="application/pdf")
        try:
            from pypdf import PdfReader
        except ImportError:
            return dict(result, status="unsupported", error="PDF extraction requires optional dependency pypdf")
        try:
            reader = PdfReader(BytesIO(body), strict=False)
            if reader.is_encrypted and not reader.decrypt(""):
                return dict(result, status="unsupported", error="Encrypted PDF requires a password")
            if len(reader.pages) > 500:
                return dict(result, status="unsupported", error="PDF exceeds 500-page extraction limit")
            pages, empty_pages = [], []
            for number, page in enumerate(reader.pages, 1):
                text = (page.extract_text() or "").strip()
                if not text:
                    empty_pages.append(number)
                pages.append(f"[第 {number} 页]\n{text}")
            metadata = reader.metadata or {}
            title = str(metadata.get("/Title", "") or "").strip()
            if len(empty_pages) == len(pages):
                return dict(result, title=title, status="empty", error="PDF has no text layer; OCR required", ocr_required=True)
            return dict(result, title=title, text="\n\n".join(pages), status="ok",
                        ocr_required=bool(empty_pages),
                        error=(f"Some PDF pages have no text layer; OCR may be required: {empty_pages}" if empty_pages else ""))
        except Exception as exc:
            return dict(result, status="error", error=f"PDF extraction failed: {exc}")

    def _render_browser(self, result, allowed_domains):
        """Optional rendering with all HTTP traffic mediated by this fetcher.

        Browser redirect interception is not reliable across Playwright versions.
        Consequently route handlers never allow native HTTP requests to proceed:
        a bounded requests download checks every redirect and fulfills the route.
        WebSockets are disabled, and no non-GET browser action is permitted.
        """
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
        except ImportError as exc:
            return dict(result, status="unsupported", error=f"Browser rendering unavailable: {exc}")

        async def render():
            blocked = []
            lock = asyncio.Lock()

            async def setup(page, context, **kwargs):
                if not hasattr(context, "route_web_socket"):
                    raise RuntimeError("Playwright lacks WebSocket interception; safe rendering unavailable")
                await context.route_web_socket("**/*", lambda socket_route: socket_route.close())
                await context.add_init_script(
                    "Object.defineProperty(Navigator.prototype, 'serviceWorker', "
                    "{get: () => undefined, configurable: false});")

                async def mediate(route):
                    request = route.request
                    if request.method != "GET":
                        await route.abort()
                        return
                    async with lock:
                        try:
                            target = normalize_url(request.url)
                            final, status, headers, body = await asyncio.to_thread(self._download, target, allowed_domains)
                            if not 200 <= status < 300:
                                if request.is_navigation_request():
                                    blocked.append(f"Browser resource returned HTTP {status}")
                                await route.abort()
                                return
                            if request.is_navigation_request():
                                checked = self._extract_html(body, _result(target, final), allowed_domains)
                                if checked["status"] == "blocked":
                                    blocked.append(checked["error"])
                                    await route.abort()
                                    return
                            # Never forward encoded-body/length headers for decoded bytes.
                            safe_headers = {k: v for k, v in headers.items()
                                            if k.lower() in {"content-type", "cache-control", "content-language",
                                                             "content-security-policy", "x-content-type-options",
                                                             "referrer-policy", "permissions-policy"}}
                            await route.fulfill(status=status, headers=safe_headers, body=body)
                        except _FetchFailure as exc:
                            if request.is_navigation_request():
                                blocked.append(str(exc))
                            await route.abort()
                await context.route("**/*", mediate)
                return page

            config = BrowserConfig(headless=True, user_agent=USER_AGENT,
                                   ignore_https_errors=False, enable_stealth=False,
                                   accept_downloads=False, verbose=False)
            async with AsyncWebCrawler(config=config) as crawler:
                crawler.crawler_strategy.set_hook("on_page_context_created", setup)
                crawled = await crawler.arun(result["url"], config=CrawlerRunConfig(
                    cache_mode=CacheMode.BYPASS, page_timeout=int(self.timeout * 1000),
                    wait_until="domcontentloaded", verbose=False))
                if blocked:
                    raise _FetchFailure("blocked", "; ".join(blocked))
                final_url = getattr(crawled, "redirected_url", None) or crawled.url
                self._validate_url(final_url, allowed_domains)
                self._check_robots(final_url, allowed_domains)
                if not crawled.success:
                    raise RuntimeError(crawled.error_message or "Browser rendering failed")
                html = (crawled.html or "").encode("utf-8")
                if len(html) > self.max_bytes:
                    raise RuntimeError("Rendered HTML exceeds byte limit")
                return html, final_url

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            return dict(result, status="error", error="Synchronous Fetcher cannot render inside an active event loop")
        try:
            html, final_url = asyncio.run(render())
            rendered = self._extract_html(html, dict(result, url=final_url, method="browser", raw=html), allowed_domains, "charset=utf-8")
            if rendered["status"] == "ok" and self._is_js_shell(html, rendered["text"]):
                return dict(rendered, status="empty", error="JavaScript shell still empty after rendering")
            return rendered
        except _FetchFailure as exc:
            return dict(result, method="browser", status=exc.status, error=str(exc))
        except Exception as exc:
            return dict(result, method="browser", status="error", error=f"Browser rendering failed: {exc}")


def extract_cached(body, metadata, allowed_domains):
    """Module-level pure parsing convenience; see :meth:`Fetcher.extract_cached`."""
    return Fetcher.extract_cached(body, metadata, allowed_domains)
