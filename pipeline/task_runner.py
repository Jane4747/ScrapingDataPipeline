"""Local, resumable research tasks. Each derived attempt is immutable."""
from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

from pipeline.catalog import OUTPUTS
from pipeline.task_spec import load_task, read_json, validate_task_id


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else hashlib.sha256(handle.read()).hexdigest()


@contextmanager
def task_lock(folder):
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / "task.lock"
    try:
        with lock.open("x", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "started_at": now()}, handle)
    except FileExistsError:
        raise ValueError(f"任务已被锁定；核实没有运行进程后再处理遗留锁：{lock}") from None
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def task_folder(task_id, output_root=None):
    validate_task_id(task_id)
    base = Path(output_root or OUTPUTS).resolve()
    folder = (base / task_id).resolve()
    if folder.parent != base:
        raise ValueError("任务目录超出 output-root")
    return folder


def _read(path):
    # Result files can be larger than configuration files.
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _configuration(spec):
    from pipeline.research.config import load_config
    config = load_config(spec["source_config"])
    selected = set(spec["source_ids"])
    known = {s["id"] for s in config["sources"]}
    if selected - known:
        raise ValueError("未知来源ID：" + ", ".join(sorted(selected - known)))
    if selected:
        config["sources"] = [s for s in config["sources"] if s["id"] in selected]
    # Topic is provenance and report context; do not pretend it changes the medical classifier.
    config["topic"] = spec["question"]
    return config


def _snapshot_file(source, destination, document):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    document["input_hashes"][str(destination)] = digest(destination)
    return str(destination)


def start_task(spec_path, output_root=None, dry_run=False):
    spec = load_task(spec_path)
    config = _configuration(spec)
    folder = task_folder(spec["task_id"], output_root)
    if dry_run:
        return {"schema_version": 1, "task_id": spec["task_id"], "status": "validated",
                "output_dir": str(folder), "stages": spec["stages"], "source_count": len(config["sources"]),
                "allow_network": spec["allow_network"], "spec": spec,
                "note": "只校验，不联网，不创建输出目录；地域和场景为研究限定，需在证据核验时判断。"}
    with task_lock(folder):
        if any(p.name != "task.lock" for p in folder.iterdir()):
            raise ValueError("任务目录已有内容，请使用 resume 或新的 task_id")
        document = {"schema_version": 1, "created_at": now(), "source_spec": str(Path(spec_path).resolve()),
                    "spec": spec, "input_hashes": {}, "changes": [], "pending_stages": []}
        config_path = folder / "inputs" / "sources.json"
        write_json(config_path, config)
        document["input_hashes"][str(config_path)] = digest(config_path)
        spec["source_config"] = str(config_path)
        for section, field, name in (("discovery", "import_results", "candidates.json"), ("review", "decisions_path", "review-001.json")):
            if spec[section].get(field):
                spec[section][field] = _snapshot_file(spec[section][field], folder / "inputs" / name, document)
        write_json(folder / "task.json", document)
        state = {"schema_version": 1, "task_id": spec["task_id"], "title": spec["title"],
                 "status": "running", "created_at": now(), "updated_at": now(),
                 "output_dir": str(folder), "stages": {}, "attempt_history": [], "warnings": []}
        write_json(folder / "status.json", state)
        return _execute(folder, document, state)


def get_status(task_id, output_root=None):
    folder = task_folder(task_id, output_root)
    state = _read(folder / "status.json")
    document = _read(folder / "task.json")
    pending = document.get("pending_stages", [])
    locked = (folder / "task.lock").exists()
    if pending:
        state["previous_status"] = state["status"]
        state["status"] = "running" if locked else "needs_input"
        state["pending_stages"] = pending
        state["next_action"] = "任务变更尚未执行完；无运行进程时使用resume，旧派生结果不代表最新任务。"
        order = document["spec"]["stages"]
        first = min(order.index(stage) for stage in pending)
        for stage in order[first:]:
            if stage in state["stages"] and state["stages"][stage]["status"] != "running":
                state["stages"][stage]["status"] = "stale"
    return {**state, "lock_present": locked}


def resume_task(task_id, output_root=None, *, retry_failed=False, max_pages=None, max_depth=None, review_file=None):
    folder = task_folder(task_id, output_root)
    if not (folder / "task.json").is_file() or not (folder / "status.json").is_file():
        raise ValueError("找不到完整任务；请提供正确的 task-id/output-root")
    with task_lock(folder):
        document = _read(folder / "task.json")
        state = _read(folder / "status.json")
        spec = document["spec"]
        if spec["task_id"] != task_id or state["task_id"] != task_id:
            raise ValueError("任务文件与目录ID不一致")
        for name, expected in document["input_hashes"].items():
            if not Path(name).is_file() or digest(name) != expected:
                raise ValueError("任务输入快照已变化，请创建新任务：" + name)
        rerun_collection = False
        for key, value, cap in (("max_pages", max_pages, 10000), ("max_depth", max_depth, 10)):
            if value is None:
                continue
            if spec["collection"]["mode"] != "crawl":
                raise ValueError("已有资料模式不能修改采集页数/深度")
            if type(value) is not int or value < spec["budget"][key] or value > cap:
                raise ValueError(f"{key} 只能提高至不超过{cap}，缩小范围请创建新任务")
            rerun_collection |= value > spec["budget"][key]
            if value != spec["budget"][key]:
                document["changes"].append({"at": now(), "field": key, "old": spec["budget"][key], "new": value})
                spec["budget"][key] = value
        if retry_failed:
            if spec["collection"]["mode"] != "crawl":
                raise ValueError("retry-failed 仅重试 crawl 采集失败；已有资料请先在原采集任务处理")
            rerun_collection = True
        rerun_review = bool(review_file)
        if review_file:
            if "review" not in spec["stages"]:
                raise ValueError("本任务未包含 review 阶段")
            review_path = Path(review_file).resolve()
            value = read_json(review_path)
            if not isinstance(value, dict) or not isinstance(value.get("projects"), list):
                raise ValueError("review-file 必须包含 projects 数组")
            number = len(list((folder / "inputs").glob("review-*.json"))) + 1
            spec["review"]["decisions_path"] = _snapshot_file(review_path, folder / "inputs" / f"review-{number:03}.json", document)
            document["changes"].append({"at": now(), "field": "review.decisions_path", "new": spec["review"]["decisions_path"]})
        pending = set(document.get("pending_stages", []))
        if rerun_collection:
            pending.add("collection")
            document["pending_retry_failed"] = retry_failed or document.get("pending_retry_failed", False)
        if rerun_review:
            pending.add("review")
        document["pending_stages"] = sorted(pending)
        write_json(folder / "task.json", document)
        return _execute(folder, document, state, retry_failed=retry_failed,
                        rerun_collection=rerun_collection, rerun_review=rerun_review)


def _attempt_path(folder, stage, state):
    used = [s for s in state["attempt_history"] if s.get("stage") == stage]
    number = len(used) + 1 + int(stage in state["stages"])
    parent = folder / stage
    path = parent / f"attempt-{number:03}"
    while path.exists():
        number += 1
        path = parent / f"attempt-{number:03}"
    return path


def _import_collection(spec, target):
    from pipeline.research.export import export_results
    from pipeline.research.deployments import _inside_file
    source = Path(spec["collection"]["input_dir"])
    if (source / "run.lock").exists():
        raise ValueError("原采集目录仍有 run.lock，等待采集完成后再复用")
    initial_hash = digest(source / "pages.json")
    pages = _read(source / "pages.json")
    records = _read(source / "records.json") if (source / "records.json").exists() else []
    if not isinstance(pages, list) or any(not isinstance(p, dict) for p in pages):
        raise ValueError("pages.json 必须是页面对象数组")
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise ValueError("records.json 必须是资料对象数组")
    config = _configuration(spec)
    selected = {s["id"] for s in config["sources"]}
    pages = [dict(p) for p in pages if p.get("source_id") in selected]
    records = [dict(r) for r in records if r.get("source_id") in selected]
    if not pages:
        raise ValueError("已有采集目录没有所选来源的页面")
    target.mkdir(parents=True, exist_ok=False)
    copied = {}
    for row in pages + records:
        for field in ("raw_file", "text_file"):
            if not row.get(field):
                if field == "text_file" and row.get("status") == "ok":
                    raise ValueError("成功页面缺少text_file，无法保存可追溯正文")
                continue
            original = _inside_file(source.resolve(), row[field])
            relative = original.relative_to(source.resolve())
            # Prefix prevents imported references from overwriting stage metadata.
            destination = target / "archive" / relative
            if str(relative) not in copied:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, destination)
                copied[str(relative)] = {"file": destination.relative_to(target).as_posix(), "sha256": digest(destination)}
            row[field] = destination.relative_to(target).as_posix()
    if (source / "run.lock").exists() or digest(source / "pages.json") != initial_hash:
        raise ValueError("复用期间原采集目录发生变化；本次副本保留为失败记录，请稍后重试")
    old_manifest = _read(source / "manifest.json") if (source / "manifest.json").exists() else {}
    old_sources = {s["source_id"]: s for s in old_manifest.get("sources", [])}
    results = []
    for item in config["sources"]:
        local = [p for p in pages if p.get("source_id") == item["id"]]
        relevant = [r for r in records if r.get("source_id") == item["id"]]
        old = old_sources.get(item["id"], {})
        successful = sum(p.get("status") == "ok" for p in local)
        failed = len(local) - successful
        status = "failed" if not successful else "partial" if failed or old.get("status") == "partial" else "completed"
        results.append({"source_id": item["id"], "source_name": item["name"], "pages": local,
                        "records": relevant, "status": status,
                        "remaining_candidates": old.get("remaining_candidates", 0), "stop_reason": old.get("stop_reason", "imported_existing")})
    manifest = export_results(results, target, spec["question"], ("json", "markdown"))
    write_json(target / "import_provenance.json", {"source_dir": str(source), "imported_at": now(),
                                                  "pages_sha256": initial_hash, "files": copied})
    write_json(target / "config.snapshot.json", config)
    return manifest


def _stage(stage, spec, target, state, *, retry_failed=False, resume_collection=False):
    if stage == "discovery":
        from pipeline.research.discovery import run
        args = SimpleNamespace(config=Path(spec["source_config"]), source=[], output_dir=target,
                               query_topics=spec["query_topics"], **spec["discovery"])
        args.import_results = Path(args.import_results) if args.import_results else None
        run(args)
        summary = _read(target / "discovery_summary.json")
        # Plan-only is intentionally not reported as searches that were executed.
        status = "partial" if summary["search_errors"] else "completed"
        return summary, status
    if stage == "collection":
        if spec["collection"]["mode"] == "existing":
            summary = _import_collection(spec, target)
        else:
            if not spec["allow_network"]:
                raise ValueError("任务未允许联网")
            from pipeline.research.config import load_config
            from pipeline.research.crawler import ResearchCrawler
            from pipeline.research.export import export_results
            config_path = spec["source_config"]
            if "discovery" in state["stages"]:
                config_path = str(Path(state["stages"]["discovery"]["output_dir"]) / "config.discovered.json")
            config = load_config(config_path)
            options = {k: spec["budget"][k] for k in ("max_pages", "max_depth", "workers", "timeout", "delay", "retries", "max_bytes", "browser")}
            crawler = ResearchCrawler(target, resume=resume_collection, retry_failed=retry_failed, **options)
            crawler.validate_sources(config["sources"])
            target.mkdir(parents=True, exist_ok=True)
            # This lock also prevents external evidence readers from treating a live run as a snapshot.
            lock = target / "run.lock"
            with lock.open("x", encoding="utf-8") as handle:
                handle.write(str(os.getpid()))
            try:
                write_json(target / "config.snapshot.json", config)
                results = crawler.collect(config["sources"])
                summary = export_results(results, target, spec["question"], ("json", "markdown"))
            finally:
                lock.unlink(missing_ok=True)
        return summary, summary["status"]
    if stage == "evidence":
        from pipeline.research.deployments import build_index
        dates = spec["time_range"] if spec["time_range"]["basis"] == "publication" else {}
        summary = build_index(Path(state["stages"]["collection"]["output_dir"]), target,
                              max_per_page=spec["budget"]["max_per_page"], proximity=spec["budget"]["proximity"],
                              since=dates.get("since"), until=dates.get("until"))
        return summary, "partial" if summary["read_errors"] else "completed"
    if stage == "review":
        from pipeline.review import build_review
        summary = build_review(Path(state["stages"]["evidence"]["output_dir"]), target, spec["review"]["decisions_path"])
        return summary, "completed"
    if stage == "delivery":
        from pipeline.delivery import build_delivery
        summary = build_delivery(spec, Path(state["stages"]["collection"]["output_dir"]),
                                 Path(state["stages"]["evidence"]["output_dir"]),
                                 Path(state["stages"]["review"]["output_dir"]), target, formats=spec["delivery"])
        return summary, "completed"
    raise ValueError(f"未知阶段：{stage}")


def _execute(folder, document, state, *, retry_failed=False, rerun_collection=False, rerun_review=False):
    spec = document["spec"]
    rerun_collection |= "collection" in document.get("pending_stages", [])
    rerun_review |= "review" in document.get("pending_stages", [])
    retry_failed |= document.get("pending_retry_failed", False)
    state.update(status="running", updated_at=now(), error=None)
    state["warnings"] = []
    changed_upstream = False
    try:
        for stage in spec["stages"]:
            previous = state["stages"].get(stage)
            force = changed_upstream or (stage == "collection" and rerun_collection) or (stage == "review" and rerun_review)
            if previous and previous["status"] in {"completed", "partial"} and not force:
                continue
            # Never silently repeat potentially paid calls after an interrupted search.
            if stage == "discovery" and previous and spec["discovery"]["provider"] == "brave":
                state.update(status="needs_input", error="搜索阶段曾中断，不自动重复付费请求；检查已有结果后创建明确预算的新任务")
                break
            target = _attempt_path(folder, stage, state)
            resume_collection = False
            if stage == "collection" and previous and spec["collection"]["mode"] == "crawl":
                target = Path(previous["output_dir"])
                resume_collection = True
                if (target / "run.lock").exists():
                    raise ValueError("采集目录有遗留run.lock，请核实原进程后处理，程序不会自动删除")
            item = {"stage": stage, "status": "running", "started_at": now(), "output_dir": str(target)}
            # Persist dependency invalidation BEFORE running the upstream stage.
            # A process crash must never make old downstream results appear current.
            for downstream in spec["stages"][spec["stages"].index(stage) + 1:]:
                old = state["stages"].get(downstream)
                if old and old["status"] != "stale":
                    old.update(previous_status=old["status"], status="stale", invalidated_at=now(), invalidated_by=stage)
            if previous:
                state["attempt_history"].append(dict(previous))
            state["stages"][stage] = item
            state["current_stage"] = stage
            write_json(folder / "status.json", state)
            with redirect_stdout(sys.stderr):
                summary, status = _stage(stage, spec, target, state, retry_failed=retry_failed, resume_collection=resume_collection)
            item.update(status=status, finished_at=now(), summary=summary)
            state["updated_at"] = now()
            write_json(folder / "status.json", state)
            if status in {"completed", "partial"} and stage in document.get("pending_stages", []):
                document["pending_stages"].remove(stage)
                if stage == "collection":
                    document["pending_retry_failed"] = False
                write_json(folder / "task.json", document)
            changed_upstream = True
            if status == "failed":
                state.update(status="failed", error=f"{stage} 阶段没有成功结果；详见阶段摘要和失败清单")
                break
        else:
            state["status"] = "partial" if any(s["status"] == "partial" for s in state["stages"].values()) else "completed"
        evidence = state["stages"].get("evidence", {}).get("summary", {})
        if evidence.get("unknown_publication_date_pages"):
            state["warnings"].append(f"{evidence['unknown_publication_date_pages']}个页面日期未知，不能直接计入时间范围统计")
        if evidence.get("omitted_evidence_count"):
            state["warnings"].append(f"线索数量上限省略了{evidence['omitted_evidence_count']}条候选，请按需另建任务提高上限")
        if spec["time_range"]["basis"] == "event":
            state["warnings"].append("事件日期不能从发布日期推断；本轮保留全部线索，须在项目台账核验event_date")
        if spec["region"] or spec["scenarios"]:
            state["warnings"].append("地域/场景是研究限定，程序不从来源名称猜测适用范围，需逐项目核验")
        if "review" in spec["stages"] and not spec["review"]["decisions_path"]:
            state["warnings"].append("尚未提交项目核验记录；线索数量不等于项目数量，资料包待GPT/研究人员综合分析")
        if "discovery" in spec["stages"] and spec["discovery"]["provider"] == "plan":
            state["warnings"].append("发现阶段只生成检索计划/导入候选，未实际执行搜索引擎查询")
    except Exception as exc:
        current = state["stages"].get(state.get("current_stage"))
        if current and current["status"] == "running":
            current.update(status="failed", finished_at=now(), error=f"{type(exc).__name__}: {exc}")
        state.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    state["updated_at"] = now()
    write_json(folder / "status.json", state)
    return state


def exit_code(state):
    return {"completed": 0, "validated": 0, "partial": 3, "needs_input": 4}.get(state["status"], 2)


def register(sub):
    parser = sub.add_parser("task", help="按JSON任务执行调研，默认不允许联网")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", help="返回一个JSON对象；进度写入stderr")
    parser.set_defaults(func=cmd_task)
    for name, help_text in (("status", "读取任务状态，不联网"), ("resume", "恢复任务，保留历史派生结果")):
        parser = sub.add_parser(name, help=help_text)
        parser.add_argument("--task-id", required=True)
        parser.add_argument("--output-root", type=Path)
        parser.add_argument("--json", action="store_true")
        if name == "resume":
            parser.add_argument("--retry-failed", action="store_true")
            parser.add_argument("--max-pages", type=int)
            parser.add_argument("--max-depth", type=int)
            parser.add_argument("--review-file", type=Path)
        parser.set_defaults(func=cmd_status if name == "status" else cmd_resume)


def _print(state):
    if state.get("status") == "validated":
        result = state
    else:
        result = {key: state[key] for key in ("schema_version", "task_id", "title", "status", "current_stage", "output_dir", "created_at", "updated_at", "warnings", "error", "lock_present", "pending_stages", "next_action", "previous_status") if key in state}
        result["status_file"] = str(Path(state["output_dir"]) / "status.json")
        result["stages"] = {}
        for name, stage in state.get("stages", {}).items():
            item = {key: stage[key] for key in ("status", "output_dir", "started_at", "finished_at", "error", "invalidated_by") if key in stage}
            summary = stage.get("summary", {})
            item["counts"] = {key: value for key, value in summary.items()
                              if type(value) in {int, float} and not key.endswith("version")}
            if "coverage" in summary:
                item["coverage"] = summary["coverage"]
            if "files" in summary:
                item["files"] = [str(Path(stage["output_dir"]) / file) for file in summary["files"]]
            result["stages"][name] = item
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code(state)


def cmd_task(args):
    return _print(start_task(args.spec, args.output_root, args.dry_run))


def cmd_status(args):
    # A successful read is exit 0 even if the stored execution failed.
    _print(get_status(args.task_id, args.output_root))
    return 0


def cmd_resume(args):
    return _print(resume_task(args.task_id, args.output_root, retry_failed=args.retry_failed,
                             max_pages=args.max_pages, max_depth=args.max_depth, review_file=args.review_file))
