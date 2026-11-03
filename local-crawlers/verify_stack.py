"""Integration checks: real MCP handshake, HTML extraction, and JS browser rendering."""
from __future__ import annotations

import argparse
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from common import ROOT, child_environment, interpreter, now, write_json


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'<!doctype html><html><head><title>Local crawler integration fixture</title></head><body><h1>Fixture page</h1><p id="message">static-only</p><a href="/next">Next page</a><script>document.getElementById("message").innerText="rendered-only";</script></body></html>'
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def unpack(result):
    data = result.model_dump(by_alias=True)
    if data.get("isError"):
        raise RuntimeError(str(data.get("content")))
    if isinstance(data.get("structuredContent"), dict):
        return data["structuredContent"]
    texts = [item["text"] for item in data.get("content", []) if item.get("type") == "text"]
    return json.loads("\n".join(texts))


async def verify(url: str, render: bool):
    params = StdioServerParameters(command=str(interpreter("firecrawl")), args=[str(ROOT / "gateway.py")], cwd=str(ROOT), env=child_environment())
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=120) as session:
            await session.initialize()
            listing = await session.list_tools()
            names = {tool.name for tool in listing.tools}
            assert {"crawler_status", "fetch_page", "render_page", "start_crawl", "job_status", "firecrawl_map"} <= names, names
            status = unpack(await session.call_tool("crawler_status", {}))
            fetched = unpack(await session.call_tool("fetch_page", {"url": url}))
            assert fetched["title"] == "Local crawler integration fixture", fetched
            assert "static-only" in fetched["text"] and "rendered-only" not in fetched["text"], fetched
            assert fetched["links"] == [url + "next"], fetched
            result = {"verified_at": now(), "mcp_handshake": "passed", "tool_discovery": sorted(names), "html_extraction": "passed", "status": status}
            if not status["model_credentials_configured"]:
                rejected = await session.call_tool("start_crawl", {"engine": "browser-use", "task": "Read the fixture", "urls": [url]})
                assert rejected.model_dump(by_alias=True).get("isError"), rejected
                assert "Model configuration is pending" in str(rejected.model_dump()), rejected
                result["unconfigured_model_reported"] = "passed"
            if render:
                started = unpack(await session.call_tool("render_page", {"url": url, "timeout_seconds": 120}))
                deadline = asyncio.get_running_loop().time() + 140
                while True:
                    job = unpack(await session.call_tool("job_status", {"job_id": started["job_id"]}))
                    if job["status"] in {"completed", "failed"}:
                        break
                    if asyncio.get_running_loop().time() > deadline:
                        raise TimeoutError(str(job))
                    await asyncio.sleep(1)
                assert job["status"] == "completed", job
                page = job["result"]["data"]
                assert "rendered-only" in page["text"] and "static-only" not in page["text"], page
                result["javascript_rendering"] = "passed"
                result["render_job_id"] = started["job_id"]
            write_json(ROOT / "verification.json", result)
            print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-render", action="store_true")
    args = parser.parse_args()
    fixture = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    thread.start()
    try:
        asyncio.run(verify(f"http://127.0.0.1:{fixture.server_port}/", not args.skip_render))
    finally:
        fixture.shutdown()
        fixture.server_close()
