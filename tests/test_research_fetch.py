"""Offline fetcher contracts: no test may send a real HTTP request."""
from __future__ import annotations

import builtins
import json
import socket
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

import requests

from pipeline.research.fetch import Fetcher, extract_cached, is_allowed_url, normalize_url


class Response:
    def __init__(self, status=200, body=b"", headers=None, chunks=None):
        self.status_code = status
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = headers or {}
        self.chunks = chunks
        self.closed = False

    def iter_content(self, chunk_size):
        return iter(self.chunks if self.chunks is not None else [self.body])

    def close(self):
        self.closed = True


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("Unexpected network request: " + url)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        self.closed = True


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.dns = patch("pipeline.research.fetch.socket.getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
        self.dns.start()
        self.addCleanup(self.dns.stop)
        self.sleep = patch("pipeline.research.fetch.time.sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def fetcher(self, responses, **kwargs):
        fetcher = Fetcher(delay=0, **kwargs)
        fetcher.session.close()
        fetcher.session = Session(responses)
        self.addCleanup(fetcher.close)
        return fetcher

    def test_normalization_preserves_business_query(self):
        self.assertEqual(normalize_url("HTTPS://EXAMPLE.COM:443/a?id=3&utm_source=x&category=7&empty=#more"),
                         "https://example.com/a?id=3&category=7&empty=")
        self.assertEqual(normalize_url("javascript:alert(1)"), "")
        self.assertEqual(normalize_url("https://user:secret@example.com/"), "")
        self.assertEqual(normalize_url("https://example.com/?q=a%20b&token=x%2fy&flag&utm_campaign=x"),
                         "https://example.com/?q=a%20b&token=x%2fy&flag")

    def test_domain_boundary_and_private_literals(self):
        self.assertTrue(is_allowed_url("https://news.example.com/a", ["example.com"]))
        self.assertTrue(is_allowed_url("https://abc.de/a", ["abc.de"]))
        self.assertFalse(is_allowed_url("https://example.com.evil.org/a", ["example.com"]))
        for url in ["http://localhost/a", "http://127.0.0.1/", "http://127.1/", "http://0x7f000001/", "http://[::1]/", "http://10.0.0.1/"]:
            self.assertFalse(is_allowed_url(url, [url]))

    def test_public_hostname_resolving_private_is_not_requested(self):
        fetcher = self.fetcher([])
        with patch("pipeline.research.fetch.socket.getaddrinfo", return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.2", 443))]):
            result = fetcher.fetch("https://example.com/a", ["example.com"])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(fetcher.session.calls, [])

    def test_redirect_escape_rejected_before_request(self):
        response = Response(302, headers={"Location": "https://evil.org/data"})
        fetcher = self.fetcher([Response(404), response])
        result = fetcher.fetch("https://example.com/a", ["example.com"])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual([call[0] for call in fetcher.session.calls],
                         ["https://example.com/robots.txt", "https://example.com/a"])
        self.assertTrue(response.closed)

    def test_redirect_subdomain_gets_own_robots_check(self):
        fetcher = self.fetcher([Response(404), Response(302, headers={"Location": "https://news.example.com/a#top"}),
                                Response(404), Response(body="<article>医疗机器人研究</article>")])
        result = fetcher.fetch("https://example.com/a", ["example.com"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["url"], "https://news.example.com/a")
        self.assertEqual(fetcher.session.calls[2][0], "https://news.example.com/robots.txt")
        for _, kwargs in fetcher.session.calls:
            self.assertFalse(kwargs["allow_redirects"])
            self.assertTrue(kwargs["verify"])
            self.assertTrue(kwargs["stream"])

    def test_robots_disallow_cached(self):
        fetcher = self.fetcher([Response(body="User-agent: *\nDisallow: /private\n")])
        for path in ("/private/one", "/private/two"):
            self.assertEqual(fetcher.fetch("https://example.com" + path, ["example.com"])["status"], "robots_denied")
        self.assertEqual(len(fetcher.session.calls), 1)

    def test_robots_crawl_delay_and_host_rate_limit(self):
        fetcher = self.fetcher([Response(body="User-agent: *\nCrawl-delay: 3\n"), Response(body="<p>技术</p>")])
        with patch("pipeline.research.fetch.time.monotonic", return_value=100), patch("pipeline.research.fetch.time.sleep") as sleep:
            result = fetcher.fetch("https://example.com/a", ["example.com"])
        self.assertEqual(result["status"], "ok")
        sleep.assert_called_once_with(3)

    def test_redirect_loop_stops_and_closes_responses(self):
        response = Response(302, headers={"Location": "/a"})
        fetcher = self.fetcher([Response(404), response])
        result = fetcher.fetch("https://example.com/a", ["example.com"])
        self.assertEqual(result["status"], "error")
        self.assertIn("loop", result["error"])
        self.assertTrue(response.closed)

    def test_robots_unavailable_is_distinct_and_fail_closed(self):
        fetcher = self.fetcher([requests.Timeout("no response")], retries=0)
        result = fetcher.fetch("https://example.com/a", ["example.com"])
        self.assertEqual(result["status"], "robots_unavailable")
        self.assertEqual(len(fetcher.session.calls), 1)

    def test_html_in_robots_is_not_silently_allowed(self):
        fetcher = self.fetcher([Response(body="<!DOCTYPE html><html>Not found</html>")])
        self.assertEqual(fetcher.fetch("https://example.com/a", ["example.com"])["status"], "robots_unavailable")

    def test_access_denial_never_retried_or_rendered(self):
        for status in (401, 403, 429):
            with self.subTest(status=status):
                fetcher = self.fetcher([Response(404), Response(status)], browser=True, retries=3)
                with patch.object(fetcher, "_render_browser", side_effect=AssertionError("must not render")):
                    result = fetcher.fetch("https://example.com/a", ["example.com"])
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["http_status"], status)
                self.assertEqual(len(fetcher.session.calls), 2)

    def test_temporary_http_error_retried(self):
        retry_response = Response(503)
        fetcher = self.fetcher([Response(404), retry_response, Response(body="<p>医学影像设备</p>")])
        result = fetcher.fetch("https://example.com/a", ["example.com"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(fetcher.session.calls), 3)
        self.assertTrue(retry_response.closed)

    def test_permanent_http_and_tls_errors_not_retried(self):
        for response in [Response(404), requests.exceptions.SSLError("certificate")]:
            fetcher = self.fetcher([Response(404), response], retries=3)
            result = fetcher.fetch("https://example.com/a", ["example.com"])
            self.assertEqual(result["status"], "error")
            self.assertEqual(len(fetcher.session.calls), 2)

    def test_streamed_body_size_limit_and_close(self):
        response = Response(chunks=[b"123456", b"789012"])
        fetcher = self.fetcher([Response(404), response], max_bytes=10)
        result = fetcher.fetch("https://example.com/a", ["example.com"])
        self.assertEqual(result["status"], "error")
        self.assertIn("byte limit", result["error"])
        self.assertTrue(response.closed)

    def test_content_length_rejected_before_iteration(self):
        response = Response(headers={"Content-Length": "999"})
        response.iter_content = Mock(side_effect=AssertionError("must not read"))
        fetcher = self.fetcher([Response(404), response], max_bytes=100)
        self.assertEqual(fetcher.fetch("https://example.com/a", ["example.com"])["status"], "error")
        response.iter_content.assert_not_called()

    def test_html_paragraphs_metadata_full_links_and_no_boilerplate(self):
        body = '''<!doctype html><html><head><title>官网</title>
        <meta property="article:published_time" content="2026-10-15T12:00:00+08:00"></head>
        <body><nav><a href="/list?category=7&utm_source=nav">列表</a>无关导航</nav>
        <article><h1>智能医疗装备技术</h1><p>第一段<span>与行内文字</span>。</p>
        <p>第二段<a href="/report.pdf#page=1">技术白皮书</a>。</p>
        <a href="https://outside.org/a">外站</a><script>malicious()</script></article>
        <footer>2026 年版权</footer></body></html>'''
        fetcher = self.fetcher([Response(404), Response(body=body, headers={"Content-Type": "text/html; charset=utf-8"})])
        result = fetcher.fetch("https://example.com/a", ["example.com"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["title"], "智能医疗装备技术")
        self.assertEqual(result["published_at"], "2026-10-15")
        self.assertIn("第一段与行内文字。\n第二段", result["text"])
        self.assertNotIn("无关导航", result["text"])
        self.assertNotIn("malicious", result["text"])
        self.assertNotIn("版权", result["text"])
        self.assertEqual(result["links"], [{"url": "https://example.com/list?category=7", "text": "列表"},
                                           {"url": "https://example.com/report.pdf", "text": "技术白皮书"}])
        self.assertEqual(result.pop("raw"), body.encode("utf-8"))
        json.dumps(result, ensure_ascii=False)

    def test_no_date_invented_from_url_or_copyright(self):
        fetcher = self.fetcher([Response(404), Response(body="<article>设备研究</article><footer>2025-01-01</footer>")])
        result = fetcher.fetch("https://example.com/2026/10/22/article", ["example.com"])
        self.assertEqual(result["published_at"], "")

    def test_cached_delayed_static_template_and_cookie_cleanup_without_network(self):
        # Regression: a real Mindray page put the whole technical article into
        # mr-delayed-js-html-code; dropping all templates lost the article.
        body = '''<html><head><meta charset="utf-8"></head><body>
        <h1>数字医学影像整体解决方案</h1>
        <p class="mr-innovation-detail-kv-date"><i class="mr-innovation-detail-kv-date-text">2026/10/12</i></p>
        <div class="mr-html-code-consent-root"><template class="mr-delayed-js-html-code">
        <style>.article { color: red }</style><section class="innovation-artical"><p>
        医院利用数字化技术建设医学影像平台，整合超声设备、影像诊断和临床工作流程，
        为科研、远程教学和质量控制提供数据。通过设备集成和自主研发的信息化产品，
        平台支持跨地域协作、智能分析和临床研究，提升医学影像技术的应用能力。</p>
        <a href="/paper.pdf">研究论文</a></section></template></div>
        <section class="cookies-section"><div>Mindray and Cookies</div></section>
        <div id="chooseCookies" class="mr-cookies-modal">Cookie consent advertising</div>
        <template><p>{{ unresolved_product_name }}</p></template></body></html>'''.encode("utf-8")
        with patch("requests.Session", side_effect=AssertionError("no network client")), patch("socket.getaddrinfo", side_effect=AssertionError("no DNS")):
            result = extract_cached(body, {"url": "https://example.com/a", "http_status": 200, "content_type": "text/html"}, ["example.com"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["published_at"], "2026-10-12")
        self.assertIn("整合超声设备", result["text"])
        self.assertNotIn("Cookies", result["text"])
        self.assertNotIn("unresolved", result["text"])
        self.assertEqual(result["links"], [{"url": "https://example.com/paper.pdf", "text": "研究论文"}])
        self.assertIs(result["raw"], body)

    def test_cached_shell_does_not_attempt_browser(self):
        fetcher = self.fetcher([], browser=True)
        with patch.object(fetcher, "_render_browser", side_effect=AssertionError("pure parser")):
            result = fetcher.extract_cached(b'<div id="app"></div><script></script>',
                                           {"url": "https://example.com/a", "content_type": "text/html"}, ["example.com"])
        self.assertEqual(result["status"], "empty")
        self.assertEqual(fetcher.session.calls, [])

    def test_javascript_shell_records_need_for_browser(self):
        fetcher = self.fetcher([Response(404), Response(body='<div id="app"></div><script src="app.js"></script>')])
        result = fetcher.fetch("https://example.com/a", ["example.com"])
        self.assertEqual(result["status"], "empty")
        self.assertIn("JavaScript", result["error"])

    def test_challenge_does_not_trigger_browser(self):
        fetcher = self.fetcher([Response(404), Response(body='<title>Just a moment...</title><div id="app"></div><script></script>')], browser=True)
        with patch.object(fetcher, "_render_browser", side_effect=AssertionError("must not render")):
            result = fetcher.fetch("https://example.com/a", ["example.com"])
        self.assertEqual(result["status"], "blocked")

    def test_browser_requested_only_for_successful_shell(self):
        fetcher = self.fetcher([Response(404), Response(body='<div id="root"></div><script></script>')], browser=True)
        with patch.object(fetcher, "_render_browser", return_value={"status": "test-rendered"}) as render:
            self.assertEqual(fetcher.fetch("https://example.com/a", ["example.com"])["status"], "test-rendered")
        render.assert_called_once()

    def fake_browser(self, resource_url, rendered_html="<main><h1>设备报告</h1><p>机器人技术研究正文</p></main>"):
        context = types.SimpleNamespace(route_web_socket=AsyncMock(), add_init_script=AsyncMock())
        async def register(pattern, handler):
            context.handler = handler
        context.route = register
        route = types.SimpleNamespace(request=types.SimpleNamespace(
            url=resource_url, method="GET", is_navigation_request=lambda: True),
            abort=AsyncMock(), fulfill=AsyncMock())
        class FakeCrawler:
            def __init__(self, config):
                self.crawler_strategy = self
            def set_hook(self, name, callback):
                self.hook_name, self.callback = name, callback
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def arun(self, url, config):
                if self.hook_name != "on_page_context_created":
                    raise AssertionError("wrong hook")
                await self.callback(object(), context, config=config)
                await context.handler(route)
                return types.SimpleNamespace(success=True, html=rendered_html,
                                             url=url, redirected_url=None)
        module = types.ModuleType("crawl4ai")
        module.AsyncWebCrawler = FakeCrawler
        module.BrowserConfig = types.SimpleNamespace
        module.CrawlerRunConfig = types.SimpleNamespace
        module.CacheMode = types.SimpleNamespace(BYPASS="bypass")
        return module, context, route

    def test_browser_hook_fulfills_with_bounded_http_and_keeps_original(self):
        module, context, route = self.fake_browser("https://example.com/a")
        fetcher = self.fetcher([Response(404), Response(body='<div id="root"></div><script></script>'),
                                Response(body='<html><div id="root"></div></html>')], browser=True)
        with patch.dict(sys.modules, {"crawl4ai": module}):
            result = fetcher.fetch("https://example.com/a", ["example.com"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["method"], "browser")
        self.assertIn("机器人技术研究", result["text"])
        self.assertIn("机器人技术研究", result["raw"].decode("utf-8"))
        route.fulfill.assert_awaited_once()
        route.abort.assert_not_awaited()
        context.route_web_socket.assert_awaited_once()
        context.add_init_script.assert_awaited_once()

    def test_browser_hook_rejects_cross_domain_before_network(self):
        module, _, route = self.fake_browser("https://outside.org/a")
        fetcher = self.fetcher([Response(404), Response(body='<div id="root"></div><script></script>')], browser=True)
        with patch.dict(sys.modules, {"crawl4ai": module}):
            result = fetcher.fetch("https://example.com/a", ["example.com"])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(len(fetcher.session.calls), 2)
        route.abort.assert_awaited_once()
        route.fulfill.assert_not_awaited()

    def test_browser_hook_rejects_cross_domain_redirect(self):
        module, _, route = self.fake_browser("https://example.com/a")
        fetcher = self.fetcher([Response(404), Response(body='<div id="root"></div><script></script>'),
                                Response(302, headers={"Location": "https://outside.org/a"})], browser=True)
        with patch.dict(sys.modules, {"crawl4ai": module}):
            result = fetcher.fetch("https://example.com/a", ["example.com"])
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(all(call[0].startswith("https://example.com/") for call in fetcher.session.calls))
        route.abort.assert_awaited_once()
        route.fulfill.assert_not_awaited()

    def test_pdf_missing_optional_dependency(self):
        original_import = builtins.__import__
        def without_pypdf(name, *args, **kwargs):
            if name == "pypdf":
                raise ImportError("not installed")
            return original_import(name, *args, **kwargs)
        fetcher = self.fetcher([Response(404), Response(body=b"%PDF-1.4\n")])
        with patch("builtins.__import__", side_effect=without_pypdf):
            result = fetcher.fetch("https://example.com/a.pdf", ["example.com"])
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["method"], "pdf")
        self.assertIn("pypdf", result["error"])

    def test_pdf_pages_and_scanned_document(self):
        for texts, expected_status in [(["设备技术正文", "第二页"], "ok"), (["", None], "empty"), (["正文", ""], "ok")]:
            with self.subTest(texts=texts):
                fake_reader = types.SimpleNamespace(is_encrypted=False,
                    pages=[types.SimpleNamespace(extract_text=lambda text=text: text) for text in texts], metadata={"/Title": "技术报告"})
                module = types.ModuleType("pypdf")
                module.PdfReader = Mock(return_value=fake_reader)
                fetcher = self.fetcher([Response(404), Response(body=b"%PDF-1.4\n")])
                with patch.dict(sys.modules, {"pypdf": module}):
                    result = fetcher.fetch("https://example.com/a.pdf", ["example.com"])
                self.assertEqual(result["status"], expected_status)
                self.assertEqual(result["title"], "技术报告")
                self.assertEqual(result["published_at"], "")
                self.assertEqual(result["ocr_required"], not all(texts))
                if expected_status == "ok":
                    self.assertIn("[第 1 页]", result["text"])
                    self.assertIn("[第 2 页]", result["text"])

    def test_empty_and_unsupported_responses(self):
        for response, status in [(Response(body=b""), "empty"),
                                 (Response(body=b"binary", headers={"Content-Type": "image/png"}), "unsupported")]:
            fetcher = self.fetcher([Response(404), response])
            self.assertEqual(fetcher.fetch("https://example.com/a", ["example.com"])["status"], status)

    def test_close_closes_session(self):
        fetcher = self.fetcher([])
        fetcher.close()
        self.assertTrue(fetcher.session.closed)


if __name__ == "__main__":
    unittest.main()
