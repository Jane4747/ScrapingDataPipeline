"""Exercise ScrapeGraphAI's actual browser loader without an extraction model."""
import json
import os

from common import ROOT, child_environment, configure_tls, now, settings, write_json

os.environ.update(child_environment())
configure_tls()

from scrapegraphai.graphs import SmartScraperGraph, SmartScraperMultiGraph
from scrapegraphai.docloaders.chromium import ChromiumLoader

loader = ChromiumLoader(["https://example.com"], headless=True, executable_path=settings()["CHROME_EXECUTABLE"], timeout=45)
documents = loader.load()
assert documents and "Example Domain" in documents[0].page_content
result = {"engine": "scrapegraphai", "core_imports": "passed", "upstream_chromium_loader": "passed", "model_called": False, "source_url": "https://example.com", "verified_at": now()}
write_json(ROOT / "scrapegraphai-verification.json", result)
print(json.dumps(result))
