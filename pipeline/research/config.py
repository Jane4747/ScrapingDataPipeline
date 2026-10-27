"""Load and validate the bounded, explicit source registry."""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "medical_equipment_sources.json"
DEFAULT_SOURCE_COUNT = 21
_ID = re.compile(r"[a-z][a-z0-9_-]{0,79}\Z")
_DOMAIN = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}\Z")


def _valid_domain(value: object) -> bool:
    if not isinstance(value, str) or not _DOMAIN.fullmatch(value):
        return False
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return True
    return False


def validate_seed_url(seed: object, allowed_domains=None) -> None:
    """Validate the same HTTP seed contract for registries and discoveries.

    Validation does not normalize a URL or resolve DNS. Callers importing
    candidates may normalize first, but the saved URL must pass this contract.
    """
    if not isinstance(seed, str) or not seed:
        raise ValueError("invalid HTTP seed URL")
    try:
        parsed = urlsplit(seed)
        hostname = parsed.hostname or ""
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"invalid HTTP seed URL: {seed}") from exc
    if (parsed.scheme not in {"http", "https"} or not _valid_domain(hostname)
            or parsed.username is not None or parsed.password is not None
            or port not in {None, 80, 443} or any(c.isspace() for c in seed)
            or "\\" in seed):
        raise ValueError(f"invalid HTTP seed URL: {seed}")
    if allowed_domains is not None and not any(
            hostname == domain or hostname.endswith("." + domain)
            for domain in allowed_domains):
        raise ValueError(f"seed is outside allowed_domains: {seed}")


def load_config(path: str | Path | None = None) -> dict:
    """Return validated JSON; raise ValueError for invalid configuration.

    Domains are lowercase DNS names, without wildcards, schemes, paths or ports.
    A domain permits itself and its subdomains, separated by a literal dot.
    Custom registries may contain 1..1000 sources; the bundled registry has 21.
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG
    try:
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {config_path}: {exc.msg}") from exc
    if not isinstance(config, dict):
        raise ValueError("Configuration must be an object")
    if type(config.get("version")) is not int or config["version"] != 1:
        raise ValueError("Configuration version must be 1")
    if not isinstance(config.get("topic"), str) or not config["topic"].strip():
        raise ValueError("Configuration topic must be a non-empty string")
    sources = config.get("sources")
    if not isinstance(sources, list) or not 1 <= len(sources) <= 1000:
        raise ValueError("Configuration must contain 1..1000 sources")
    if path is None and len(sources) != DEFAULT_SOURCE_COUNT:
        raise ValueError(f"Bundled configuration must contain {DEFAULT_SOURCE_COUNT} sources")
    ids: set[str] = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f"Source {index} must be an object")
        source_id = source.get("id")
        if not isinstance(source_id, str) or not _ID.fullmatch(source_id):
            raise ValueError(f"Source {index} has an invalid id")
        if source_id in ids:
            raise ValueError(f"Duplicate source id: {source_id}")
        ids.add(source_id)
        if not isinstance(source.get("name"), str) or not source["name"].strip():
            raise ValueError(f"Source {source_id} needs a non-empty name")
        domains = source.get("allowed_domains")
        if not isinstance(domains, list) or not domains or not all(_valid_domain(d) for d in domains):
            raise ValueError(f"Source {source_id} has invalid allowed_domains")
        if len(domains) != len(set(domains)):
            raise ValueError(f"Source {source_id} has duplicate allowed_domains")
        seeds = source.get("seeds")
        if not isinstance(seeds, list) or not seeds or not all(isinstance(s, str) for s in seeds):
            raise ValueError(f"Source {source_id} needs non-empty HTTP seed URLs")
        if len(seeds) != len(set(seeds)):
            raise ValueError(f"Source {source_id} has duplicate seed URLs")
        for seed in seeds:
            try:
                validate_seed_url(seed, domains)
            except ValueError as exc:
                raise ValueError(f"Source {source_id} has an {exc}") from exc
    return config
