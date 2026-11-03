"""Exercise browser-use's real local browser without invoking a language model."""
import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from common import ROOT, child_environment, now, settings, write_json

os.environ.update(child_environment())


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'<html><head><title>Browser Use Local Smoke</title></head><body><h1>Local browser ready</h1><a href="/next">Next</a></body></html>'
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


async def check(url):
    from browser_use import Agent, Browser, ChatOpenAI
    browser = Browser(headless=True, use_cloud=False, enable_default_extensions=False, viewport={"width": 1280, "height": 720}, executable_path=settings()["CHROME_EXECUTABLE"], user_data_dir=str(ROOT / "profiles" / "browser-use-smoke"))
    try:
        await browser.start()
        page = await browser.get_current_page()
        await page.goto(url)
        for _ in range(30):
            title = await page.evaluate("() => document.title")
            if title == "Browser Use Local Smoke":
                break
            await asyncio.sleep(0.5)
        assert title == "Browser Use Local Smoke", title
        body = await page.evaluate("() => document.body.innerText")
        assert "Local browser ready" in body and "Next" in body, body
        state = await browser.get_browser_state_summary(include_screenshot=False)
        assert state.dom_state is not None
        result = {"engine": "browser-use", "core_imports": "passed", "local_browser_launch": "passed", "navigation_and_dom_reading": "passed", "model_called": False, "verified_at": now()}
        write_json(ROOT / "browser-use-verification.json", result)
        print(json.dumps(result))
    finally:
        await browser.kill()


if __name__ == "__main__":
    fixture = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    try:
        asyncio.run(check(f"http://127.0.0.1:{fixture.server_port}/"))
    finally:
        fixture.shutdown()
        fixture.server_close()
