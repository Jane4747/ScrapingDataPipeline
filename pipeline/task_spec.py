"""Versioned, dependency-free task validation for local research workflows."""
from __future__ import annotations

from datetime import date
import json
import math
from pathlib import Path
import re

from pipeline.catalog import ROOT

STAGES = ("discovery", "collection", "evidence", "review", "delivery")
TASK_KEYS = {"schema_version", "task_id", "title", "question", "research_type", "region",
             "scenarios", "source_config", "source_ids", "allow_network", "discovery",
             "collection", "budget", "time_range", "delivery", "stages", "review", "topic_profile"}


def validate_task_id(value):
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", value)
            or ".." in value or value.endswith(".")
            or value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}):
        raise ValueError("task_id 必须是安全的字母数字目录名（最多80字符），不能包含路径或保留设备名")
    return value


def _object(value, allowed, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是对象")
    unknown = set(value) - set(allowed)
    if unknown:
        raise ValueError(f"{label} 存在不支持的字段：{', '.join(sorted(unknown))}")
    return dict(value)


def _text(value, label, required=False):
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"{label} 必须是{'非空' if required else ''}字符串")
    return value.strip()


def _strings(value, label):
    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
        raise ValueError(f"{label} 必须是非空字符串组成的数组")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} 不得有重复项")
    return value


def _path(value, base, label, *, directory=False):
    value = _text(value, label, True)
    path = Path(value)
    path = (path if path.is_absolute() else base / path).resolve()
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError(f"{label} 不存在或类型错误：{path}")
    return str(path)


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 5 * 1024 * 1024:
        raise ValueError(f"配置文件超过5 MiB：{path}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError(f"无法读取JSON配置：{path.name} ({type(exc).__name__})") from exc


def load_task(path):
    path = Path(path).resolve()
    data = _object(read_json(path), TASK_KEYS, "task")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("schema_version 必须为1")
    spec = {"schema_version": 1, "task_id": validate_task_id(data.get("task_id")),
            "title": _text(data.get("title", ""), "title", True),
            "question": _text(data.get("question", ""), "question", True),
            "research_type": data.get("research_type", "health_deployment"),
            "region": _text(data.get("region", ""), "region"),
            "scenarios": _strings(data.get("scenarios", []), "scenarios")}
    if spec["research_type"] != "health_deployment":
        raise ValueError("任务流水线当前支持 health_deployment；其他主题请使用独立采集命令并另行分析")
    allow = data.get("allow_network", False)
    if type(allow) is not bool:
        raise ValueError("allow_network 必须是布尔值")
    spec["allow_network"] = allow
    spec["source_config"] = _path(data.get("source_config", str(ROOT / "configs" / "medical_equipment_sources.json")), path.parent, "source_config")
    spec["source_ids"] = _strings(data.get("source_ids", []), "source_ids")
    time_range = _object(data.get("time_range", {}), {"since", "until", "basis"}, "time_range")
    time_range.setdefault("basis", "publication")
    if not isinstance(time_range["basis"], str) or time_range["basis"] not in {"publication", "event"}:
        raise ValueError("time_range.basis 必须是 publication 或 event")
    for key in ("since", "until"):
        value = time_range.get(key)
        if value is not None:
            if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError(f"time_range.{key} 必须是 YYYY-MM-DD")
            try:
                date.fromisoformat(value)
            except ValueError:
                raise ValueError(f"time_range.{key} 不是有效日期") from None
        time_range[key] = value
    if time_range["since"] and time_range["until"] and time_range["since"] > time_range["until"]:
        raise ValueError("since 不得晚于 until")
    spec["time_range"] = time_range
    collection = _object(data.get("collection", {}), {"mode", "input_dir"}, "collection")
    collection.setdefault("mode", "crawl")
    if not isinstance(collection["mode"], str) or collection["mode"] not in {"crawl", "existing"}:
        raise ValueError("collection.mode 必须是 crawl 或 existing")
    if collection["mode"] == "existing":
        collection["input_dir"] = _path(collection.get("input_dir"), path.parent, "collection.input_dir", directory=True)
        if not (Path(collection["input_dir"]) / "pages.json").is_file():
            raise ValueError("existing 采集目录必须有 pages.json")
    elif "input_dir" in collection:
        raise ValueError("crawl 模式不能指定 input_dir")
    spec["collection"] = collection
    stages = _strings(data.get("stages", list(STAGES[1:] if collection["mode"] == "existing" else STAGES)), "stages")
    if not stages or any(stage not in STAGES for stage in stages) or stages != sorted(stages, key=STAGES.index):
        raise ValueError("stages 必须按 discovery、collection、evidence、review、delivery 顺序且不可为空")
    for stage, parent in (("evidence", "collection"), ("review", "evidence"), ("delivery", "review")):
        if stage in stages and parent not in stages:
            raise ValueError(f"{stage} 阶段需要 {parent} 阶段")
    if collection["mode"] == "existing" and "discovery" in stages:
        raise ValueError("existing 模式不运行 discovery；新候选请使用独立发现任务")
    spec["stages"] = stages
    discovery = _object(data.get("discovery", {}), {"provider", "import_results", "max_queries", "api_budget", "results_per_query"}, "discovery")
    discovery.setdefault("provider", "plan")
    if not isinstance(discovery["provider"], str) or discovery["provider"] not in {"plan", "brave"}:
        raise ValueError("discovery.provider 必须是 plan 或 brave")
    for key, default, upper in (("max_queries", 6, 30), ("api_budget", 6, 30), ("results_per_query", 5, 20)):
        discovery.setdefault(key, default)
        if type(discovery[key]) is not int or not 1 <= discovery[key] <= upper:
            raise ValueError(f"discovery.{key} 必须在1..{upper}之间")
    if discovery.get("import_results"):
        discovery["import_results"] = _path(discovery["import_results"], path.parent, "discovery.import_results")
    else:
        discovery["import_results"] = None
    spec["discovery"] = discovery
    if not allow and (("collection" in stages and collection["mode"] == "crawl") or ("discovery" in stages and discovery["provider"] == "brave")):
        raise ValueError("本任务包含联网阶段，需明确设置 allow_network=true；已有资料分析和plan模式无需联网")
    defaults = {"max_pages": 6, "max_depth": 1, "workers": 3, "timeout": 25,
                "delay": 1.0, "retries": 1, "max_bytes": 12 * 1024 * 1024,
                "browser": False, "max_per_page": 30, "proximity": 100}
    budget = _object(data.get("budget", {}), defaults, "budget")
    budget = {**defaults, **budget}
    bounds = {"max_pages": (1, 10000), "max_depth": (0, 10), "workers": (1, 32), "retries": (0, 10),
              "max_bytes": (1, 128 * 1024 * 1024), "max_per_page": (1, 10000), "proximity": (0, 500)}
    for key, (lower, upper) in bounds.items():
        if type(budget[key]) is not int or not lower <= budget[key] <= upper:
            raise ValueError(f"budget.{key} 必须是{lower}..{upper}的整数")
    for key in ("timeout", "delay"):
        if type(budget[key]) not in {int, float} or not math.isfinite(budget[key]) or not (0 < budget[key] <= 600 if key == "timeout" else 0 <= budget[key] <= 600):
            raise ValueError(f"budget.{key} 超出有效范围")
    if type(budget["browser"]) is not bool:
        raise ValueError("budget.browser 必须是布尔值")
    spec["budget"] = budget
    formats = _strings(data.get("delivery", ["json", "markdown", "csv"]), "delivery")
    if not formats or set(formats) - {"json", "markdown", "csv", "excel"}:
        raise ValueError("delivery 支持 json、markdown、csv、excel")
    spec["delivery"] = formats
    review = _object(data.get("review", {}), {"decisions_path"}, "review")
    review["decisions_path"] = _path(review["decisions_path"], path.parent, "review.decisions_path") if review.get("decisions_path") else None
    spec["review"] = review
    profile_path = _path(data.get("topic_profile", str(ROOT / "configs" / "topics" / "health_deployment.json")), path.parent, "topic_profile")
    profile = _object(read_json(profile_path), {"schema_version", "name", "query_topics"}, "topic_profile")
    if type(profile.get("schema_version")) is not int or profile["schema_version"] != 1 or not isinstance(profile.get("query_topics"), list) or not 1 <= len(profile["query_topics"]) <= 30:
        raise ValueError("topic_profile 需要 schema_version=1 和1..30条 query_topics")
    for query in profile["query_topics"]:
        _object(query, {"purpose", "terms"}, "query_topics[]")
        _text(query.get("purpose"), "query_topics[].purpose", True)
        _text(query.get("terms"), "query_topics[].terms", True)
    spec["query_topics"] = profile["query_topics"]
    spec["topic_profile"] = profile_path
    return spec
