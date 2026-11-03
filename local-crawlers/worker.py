"""Adapters use installed upstream libraries, never a hosted crawler substitution."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from common import child_environment, configure_tls, firecrawl_url, model_settings, now, settings, write_json


def plain(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def prompt(request: dict) -> str:
    text = request["task"] + "\nSource URLs:\n" + "\n".join(request["urls"])
    if request.get("output_schema"):
        text += "\nReturn JSON conforming to this schema:\n" + json.dumps(request["output_schema"], ensure_ascii=False)
    return text


@asynccontextmanager
async def managed_chrome(folder: Path):
    """Start a dedicated system Chrome with a loopback-only, ephemeral CDP port."""
    from playwright.async_api import async_playwright
    profile = folder / "chrome-profile"
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile), headless=True,
            executable_path=settings().get("CHROME_EXECUTABLE") or None,
            args=["--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1"],
        )
        try:
            for _ in range(100):
                port_file = profile / "DevToolsActivePort"
                if port_file.exists():
                    port = int(port_file.read_text(encoding="utf-8").splitlines()[0])
                    yield context, f"http://127.0.0.1:{port}"
                    return
                await asyncio.sleep(0.1)
            raise TimeoutError("Chrome did not publish a local debugging port")
        finally:
            await context.close()


async def browser_use_task(request: dict, folder: Path):
    from browser_use import Agent, Browser, ChatOpenAI
    values = model_settings()
    browser = Browser(headless=True, use_cloud=False, enable_default_extensions=False, executable_path=values.get("CHROME_EXECUTABLE") or None, user_data_dir=str(folder / "browser-profile"), downloads_path=str(folder / "downloads"))
    model = ChatOpenAI(model=values["MODEL_ID"], api_key=values["MODEL_API_KEY"], base_url=values["MODEL_BASE_URL"])
    agent = Agent(task=prompt(request), llm=model, browser=browser, use_vision=values.get("MODEL_SUPPORTS_VISION", "false").lower() == "true")
    try:
        history = await agent.run(max_steps=request["max_steps"])
        agent.save_history(str(folder / "browser-history.json"))
        if not history.is_successful():
            raise RuntimeError("Browser agent did not report task success; see browser-history.json")
        return plain(history.final_result())
    finally:
        await browser.kill()


async def skyvern_task(request: dict, folder: Path):
    from skyvern import Skyvern
    from skyvern.schemas.llm import LLMConfig
    values = model_settings()
    model = LLMConfig(model_name="openai/" + values["MODEL_ID"], required_env_vars=[], supports_vision=values.get("MODEL_SUPPORTS_VISION", "false").lower() == "true", add_assistant_prefix=False, litellm_params={"api_key": values["MODEL_API_KEY"], "api_base": values["MODEL_BASE_URL"]})
    async with managed_chrome(folder) as (_, address):
        skyvern = Skyvern.local(llm_config=model, use_in_memory_db=True, settings={"BROWSER_TYPE": "cdp-connect", "BROWSER_REMOTE_DEBUGGING_URL": address, "MAX_STEPS_PER_RUN": request["max_steps"], "ARTIFACT_STORAGE_PATH": str(folder / "artifacts")})
        try:
            result = await skyvern.run_task(prompt=prompt(request), url=request["urls"][0], browser_address=address, max_steps=request["max_steps"], data_extraction_schema=request.get("output_schema"), wait_for_completion=True, timeout=max(20, request["timeout_seconds"] - 15))
            write_json(folder / "skyvern-run.json", plain(result))
            if str(result.status).lower().split(".")[-1] != "completed":
                raise RuntimeError("Skyvern did not complete successfully; see skyvern-run.json")
            return plain(result.output)
        finally:
            await skyvern.aclose()


def scrapegraph_task(request: dict, folder: Path):
    from scrapegraphai.graphs import SmartScraperGraph, SmartScraperMultiGraph
    values = model_settings()
    config = {"llm": {"model": "openai/" + values["MODEL_ID"], "api_key": values["MODEL_API_KEY"], "base_url": values["MODEL_BASE_URL"], "model_tokens": 16000}, "verbose": False, "headless": True, "loader_kwargs": {"executable_path": values.get("CHROME_EXECUTABLE") or None}}
    if len(request["urls"]) == 1:
        graph = SmartScraperGraph(prompt=prompt(request), source=request["urls"][0], config=config)
    else:
        graph = SmartScraperMultiGraph(prompt=prompt(request), source=request["urls"], config=config)
    return graph.run()


async def render_task(request: dict, folder: Path):
    from playwright.async_api import async_playwright
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, executable_path=settings().get("CHROME_EXECUTABLE") or None)
        try:
            page = await browser.new_page()
            response = await page.goto(request["urls"][0], wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1500)
            (folder / "page.html").write_text(await page.content(), encoding="utf-8")
            await page.screenshot(path=str(folder / "screenshot.png"), full_page=True)
            return {"source_url": page.url, "http_status": response.status if response else None, "title": await page.title(), "text": await page.locator("body").inner_text(), "links": await page.locator("a[href]").evaluate_all("elements => elements.map(a => ({text:a.innerText,url:a.href}))"), "screenshot": str(folder / "screenshot.png"), "html": str(folder / "page.html")}
        finally:
            await browser.close()


async def firecrawl_task(request: dict, folder: Path):
    import httpx
    values = settings()
    headers = {"Authorization": "Bearer " + values["FIRECRAWL_API_KEY"]} if values.get("FIRECRAWL_API_KEY") else {}
    async with httpx.AsyncClient(timeout=90, trust_env=False, headers=headers) as client:
        response = await client.post(firecrawl_url() + "/v2/crawl", json={"url": request["urls"][0], "limit": request["max_pages"], "scrapeOptions": {"formats": ["markdown"]}})
        response.raise_for_status()
        job = response.json()
        if not job.get("success") or not job.get("id"):
            raise RuntimeError("Firecrawl did not accept the crawl job: " + str(job))
        write_json(folder / "firecrawl-job.json", job)
        while True:
            response = await client.get(firecrawl_url() + "/v2/crawl/" + job["id"])
            response.raise_for_status()
            status = response.json()
            if status.get("status") in {"failed", "cancelled"}:
                raise RuntimeError("Firecrawl crawl failed: " + str(status))
            if status.get("status") == "completed":
                pages = list(status.get("data", []))
                next_url = status.get("next")
                while next_url:
                    # Do not follow a service-provided URL to a hosted endpoint.
                    from urllib.parse import urlsplit
                    parts = urlsplit(next_url)
                    response = await client.get(firecrawl_url() + parts.path + ("?" + parts.query if parts.query else ""))
                    response.raise_for_status()
                    following = response.json()
                    pages.extend(following.get("data", []))
                    next_url = following.get("next")
                return {**status, "data": pages, "next": None}
            await asyncio.sleep(3)


def main():
    folder = Path(sys.argv[1]).resolve()
    request = json.loads((folder / "input.json").read_text(encoding="utf-8"))
    os.environ.update(child_environment())
    configure_tls()
    engine = request["engine"]
    if engine == "scrapegraphai":
        data = scrapegraph_task(request, folder)
    else:
        function = {"browser-use": browser_use_task, "skyvern": skyvern_task, "firecrawl": firecrawl_task, "render": render_task}[engine]
        data = asyncio.run(function(request, folder))
    schema = request.get("output_schema")
    if schema:
        from jsonschema import validate
        validate(data, schema)
    write_json(folder / "result.json", {"engine": engine, "source_urls": request["urls"], "completed_at": now(), "schema_validated": bool(schema), "data": data})


if __name__ == "__main__":
    main()
