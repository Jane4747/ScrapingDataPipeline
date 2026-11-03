"""Check deep local-runtime imports and Skyvern's browser API, without a model or API service."""
import asyncio
import json
import os

from common import ROOT, child_environment, configure_tls, now, write_json

os.environ.update(child_environment())
configure_tls()


async def check():
    from skyvern import Skyvern
    from skyvern.library.embedded_server_factory import create_embedded_server
    from worker import managed_chrome
    # The deliberately unused API endpoint guarantees this check cannot call a hosted service.
    client = Skyvern(api_key="", base_url="http://127.0.0.1:1")
    folder = ROOT / "runs" / "skyvern-browser-smoke"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        async with managed_chrome(folder) as (_, address):
            browser = await client.connect_to_browser_over_cdp(address)
            page = await browser.get_working_page()
            await page.goto("https://example.com", timeout=45000, wait_until="domcontentloaded")
            title = await page.title()
            body = await page.evaluate("() => document.body.innerText")
            html = await page.content()
            write_json(ROOT / "logs" / "skyvern-page-diagnostic.json", {"title": title, "body": body, "html": html[:6000]})
            assert title == "Example Domain", title
            assert len(body.strip()) > 30, {"body": body, "html": html[:2000]}
        result = {"engine": "skyvern", "embedded_runtime_imports": "passed", "local_chrome_connection": "passed", "browser_navigation_and_reading": "passed", "source_url": "https://example.com", "model_called": False, "verified_at": now()}
        write_json(ROOT / "skyvern-verification.json", result)
        print(json.dumps(result))
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(check())
