"""Configuration and result files shared by isolated local crawler processes."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
ENGINES = {"browser-use": "browser-use", "skyvern": "skyvern", "scrapegraphai": "scrapegraphai", "firecrawl": "gateway", "render": "scrapegraphai"}


def settings() -> dict[str, str]:
    values: dict[str, str] = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    for key in values:
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def configure_tls() -> None:
    """Use Windows' trusted CA store as well as public roots; keep TLS verification enabled."""
    import truststore
    truststore.inject_into_ssl()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temp.replace(path)


def interpreter(engine: str) -> Path:
    path = ROOT / "envs" / ENGINES[engine] / "Scripts" / "python.exe"
    return path


def validate_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Use an HTTP(S) URL without embedded credentials.")
    return url


def firecrawl_url() -> str:
    url = settings().get("FIRECRAWL_API_URL", "http://127.0.0.1:3002").rstrip("/")
    validate_url(url)
    if urlsplit(url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("This stack uses a local Firecrawl endpoint only; no hosted fallback is configured.")
    return url


def model_settings() -> dict[str, str]:
    values = settings()
    missing = [key for key in ("MODEL_BASE_URL", "MODEL_ID", "MODEL_API_KEY") if not values.get(key)]
    if missing:
        raise ValueError("Model configuration is pending (" + ", ".join(missing) + "). Requested model: " + values.get("REQUESTED_MODEL_NAME", "DeepSeek V4.1 Flash"))
    validate_url(values["MODEL_BASE_URL"])
    return values


def child_environment() -> dict[str, str]:
    env = dict(os.environ)
    values = settings()
    for key in ("ANONYMIZED_TELEMETRY", "SCRAPEGRAPHAI_TELEMETRY_ENABLED", "SKYVERN_TELEMETRY"):
        env[key] = values.get(key, "false")
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(ROOT / "cache" / "browsers")
    env["BROWSER_USE_CONFIG_DIR"] = str(ROOT / "profiles" / "browser-use")
    env["XDG_CONFIG_HOME"] = str(ROOT / "cache" / "config")
    env["XDG_CACHE_HOME"] = str(ROOT / "cache")
    env["HF_HOME"] = str(ROOT / "cache" / "huggingface")
    env["TIKTOKEN_CACHE_DIR"] = str(ROOT / "cache" / "tiktoken")
    bypass = env.get("NO_PROXY", env.get("no_proxy", ""))
    env["NO_PROXY"] = ",".join(filter(None, [bypass, "localhost", "127.0.0.1", "::1"]))
    env["no_proxy"] = env["NO_PROXY"]
    env["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env
