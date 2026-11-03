"""Write a durable, credential-free deployment handoff."""
import json
import tomllib
from pathlib import Path

from common import ROOT, now, write_json
from gateway import crawler_status

status = crawler_status()
checks = {}
for engine in ("browser-use", "skyvern", "scrapegraphai"):
    file = ROOT / (engine + "-verification.json")
    checks[engine] = json.loads(file.read_text(encoding="utf-8")) if file.exists() else {"status": "not_verified"}
config = tomllib.loads((Path.home() / ".codex" / "config.toml").read_text(encoding="utf-8-sig"))
entry = config.get("mcp_servers", {}).get("local_crawlers", {})
report = {
    "updated_at": now(), "deployment_directory": str(ROOT),
    "codex_mcp": {"name": "local_crawlers", "registered": bool(entry), "enabled": entry.get("enabled", True)},
    "runtime_status": status,
    "non_model_checks": checks,
    "model_configuration": {"requested_model": "DeepSeek V4.1 Flash", "state": "deferred_by_user", "end_to_end_ai_tasks_tested": False},
    "firecrawl": {"state": "waiting_for_manual_windows_restart", "running": False, "windows_automatically_restarted": False, "resume_script": str(ROOT / "Complete-FirecrawlWSL.ps1"), "linux_data_directory": "D:/CodexLocalCrawlers"},
}
write_json(ROOT / "deployment-status.json", report)
print(json.dumps({"codex_registered": report["codex_mcp"]["registered"], "installed": {name: value["version"] for name, value in status["engines"].items() if name != "firecrawl"}, "browser_checks": {name: value.get("model_called") is False for name, value in checks.items()}, "firecrawl": report["firecrawl"]["state"], "model": report["model_configuration"]["state"]}, ensure_ascii=False))
