"""Offline, traceable research packages; no automatically verified conclusions."""

from collections import Counter
from datetime import date
import html
from pathlib import Path
from urllib.parse import quote, urlsplit

from .research.deployments import FIELDNAMES as EVIDENCE_FIELDS, _known_date, csv_safe
from .review import (
    PROJECT_FIELDS, REVIEW_NOTE, STATUSES, _load_evidence, _now,
    _output_directory, _read_snapshot, _validate_date, _validate_projects, _write_csv, _write_json,
)


SOURCE_FIELDS = ("source_id", "source_name", "title", "url", "published_at", "status", "error")
PACKAGE_NOTE = (
    "本交付为机器整理资料包，待 GPT 综合分析与必要核验；不包含程序自动确认的事实结论。"
    "资料、原文线索与填写者归并的项目分别计数，线索数不等于项目数。"
)


def _md(value):
    if isinstance(value, (list, tuple)):
        value = "、".join(map(str, value))
    return html.escape(str(value or ""), quote=False).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _link(title, url):
    try:
        parsed = urlsplit(str(url or ""))
        if parsed.scheme in ("http", "https") and parsed.hostname:
            safe = quote(str(url), safe=":/?#[]@!$&'*+,;=%")
            return f"[{_md(title).replace('[', '&#91;').replace(']', '&#93;')}]({safe})"
    except ValueError:
        pass
    return _md(title) + (f"（{_md(url)}）" if url else "")


def _markdown(report):
    task, coverage = report["task"], report["coverage"]
    interval = task.get("time_range")
    interval = {} if interval is None else interval
    lines = [f"# {_md(task.get('title') or '调研资料包')}", "", PACKAGE_NOTE, "",
             f"调研问题：{_md(task.get('question') or '未填写')}", "",
             f"时间范围：{_md(interval.get('since') or '不限')} 至 {_md(interval.get('until') or '不限')}；日期口径：{_md(interval.get('basis') or '未填写')}。", "",
             f"地域：{_md(task.get('region') or task.get('regions') or '未限定')}；场景：{_md(task.get('scenarios') or '未限定')}。",
             f"研究类型：{_md(task.get('research_type') or '未填写')}；指定来源 ID：{_md(task.get('source_ids') or '未限定')}。", "",
             "地域、场景及来源范围是调研要求；是否符合范围仍需逐项目判断，不能由关键词命中或日期落入范围自动确认。", "",
             "## 覆盖与统计", "",
             f"采集来源 {coverage['source_count']} 个；页面记录 {coverage['attempted_pages']} 个，成功 {coverage['successful_pages']} 个，失败或未成功 {coverage['failed_pages']} 个。",
             f"成功页面中发布日期未知 {coverage['unknown_publication_date_pages']} 个；原文线索 {coverage['evidence_count']} 条；填写者归并项目 {coverage['project_count']} 个。", "",
             f"仅按填写者提供的事件日期与上述起止日期比较（含边界）：范围内项目 {coverage['event_date_in_range_projects']} 个，范围外 {coverage['event_date_out_of_range_projects']} 个，事件日期未知 {coverage['unknown_event_date_projects']} 个。未知日期未计入范围内项目数，项目台账保留全部记录。", "",
             "这里的日期范围内数量不是已核实或完全符合调研范围的项目数量；地域、场景、阶段和事实依据仍需核验。若任务按发布日期限定，事件日期统计仅作独立补充。", "",
             "发布日期、事件日期和抓取日期分别保留。日期未知不等于落在调研时间范围内；不能直接用于限定年份的项目数量统计。", "",
             "## 项目与核验声明", "", REVIEW_NOTE, "",
             "| 项目 ID | 项目名称 | 阶段 | 事件日期 | 填写者核验声明 | 证据 ID |",
             "|---|---|---|---|---|---|"]
    for project in report["projects"]:
        lines.append("| " + " | ".join(_md(project[key]) if key != "evidence_ids" else _md("、".join(project[key]))
                                           for key in ("project_id", "name", "stage", "event_date", "review_status", "evidence_ids")) + " |")
    if not report["projects"]:
        lines.append("| — | 尚未提交项目归并决定，项目台账为空 | — | — | 待核验 | — |")
    for project in report["projects"]:
        lines += ["", f"### {_md(project['project_id'])}：{_md(project['name'])}", "",
                  f"企业/主体：{_md(project['entity'])}；产品：{_md(project['product'])}；应用机构：{_md(project['application_org'])}；地点：{_md(project['location'])}。",
                  f"填写者：{_md(project['reviewer']) or '未填写'}；核验记录日期：{_md(project['reviewed_at']) or '未填写'}。",
                  f"备注：{_md(project['notes']) or '未填写'}。"]
    lines += ["", "## 缺口与后续核验", ""]
    lines.extend(f"- {_md(gap)}" for gap in report["gaps"])
    lines += ["", "## 原文证据", ""]
    if not report["evidence"]:
        lines.append("没有可用原文线索；不能据此判断研究对象不存在相关项目。")
    for row in report["evidence"]:
        lines += [f"### {_md(row['evidence_id'])}", "",
                  f"{_link(row.get('title') or row.get('source_name') or row.get('source_id') or '来源', row.get('url'))}", "",
                  f"> {_md(row.get('evidence_text'))}", "",
                  f"来源 ID：{_md(row.get('source_id'))}；发布日期：{_md(row.get('published_at')) or '未知'}；抓取日期：{_md(row.get('collected_at')) or '未知'}。",
                  f"原文位置：正文行 {_md(row.get('paragraph_index')) or '未知'}；片段 {_md(row.get('fragment_index')) or '未知'}；PDF 页 {_md(row.get('pdf_page')) or '不适用/未知'}。",
                  f"线索类型：{_md(row.get('signal_type'))}；原文文件：{_md(row.get('text_path') or row.get('text_file')) or '未提供'}。", ""]
    lines += ["## 采集来源与失败记录", ""]
    for source in report["sources"]:
        lines.append(f"- {_link(source['title'] or source['source_name'] or source['source_id'] or '页面', source['url'])}；状态：{_md(source['status'])}；发布日期：{_md(source['published_at']) or '未知'}" + (f"；原因：{_md(source['error'])}" if source['error'] else ""))
    if not report["sources"]:
        lines.append("未提供采集页面记录，覆盖范围未知。")
    return "\n".join(lines) + "\n"


def build_delivery(task, collection_dir, evidence_dir, review_dir, output_dir, formats=("json", "markdown")):
    """Package saved data. JSON and Markdown are the always-present audit core."""
    if not isinstance(task, dict):
        raise ValueError("task 必须是对象")
    interval = task.get("time_range")
    interval = {} if interval is None else interval
    if not isinstance(interval, dict):
        raise ValueError("task.time_range 必须是对象")
    for key in ("since", "until"):
        if interval.get(key) is not None:
            if not isinstance(interval[key], str) or not interval[key]:
                raise ValueError(f"time_range.{key} 必须是有效 ISO 日期 YYYY-MM-DD")
            _validate_date(interval[key], f"time_range.{key}")
    lower = date.fromisoformat(interval["since"]) if interval.get("since") else None
    upper = date.fromisoformat(interval["until"]) if interval.get("until") else None
    if lower and upper and lower > upper:
        raise ValueError("time_range.since 不得晚于 until")
    if not isinstance(formats, (list, tuple, set)) or any(not isinstance(value, str) for value in formats):
        raise ValueError("formats 必须是格式列表")
    selected = set(formats)
    unknown = selected - {"json", "markdown", "csv", "excel", "xlsx"}
    if unknown:
        raise ValueError(f"不支持的交付格式: {', '.join(sorted(unknown))}")
    # Optional export libraries must not become CLI startup dependencies.
    pandas = None
    if selected & {"excel", "xlsx"}:
        try:
            import pandas
            import xlsxwriter  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("Excel 导出需要 pandas 和 xlsxwriter；基础 JSON/Markdown/CSV 不需要它们") from exc
    gaps = []
    if collection_dir is not None:
        collection = Path(collection_dir).resolve()
        snapshot = _read_snapshot(collection, ("pages.json", "manifest.json"), optional=("manifest.json",))
        pages, manifest = snapshot["pages.json"], snapshot["manifest.json"]
        if not isinstance(pages, list) or any(not isinstance(page, dict) for page in pages) or not isinstance(manifest, dict):
            raise ValueError("采集 pages.json 必须是对象列表，manifest.json 必须是对象")
        if not manifest:
            gaps.append("缺少采集 manifest，无法核对原始运行参数与来源清单。")
    else:
        pages, manifest = [], {}
        gaps.append("未提供采集目录，采集覆盖范围未知。")
    if evidence_dir is not None:
        evidence, evidence_summary, evidence_index = _load_evidence(evidence_dir)
        if collection_dir and evidence_summary.get("input_dir") and Path(evidence_summary["input_dir"]).resolve() != Path(collection_dir).resolve():
            raise ValueError("证据索引的 input_dir 与本次 collection_dir 不一致，拒绝混用资料")
    else:
        evidence, evidence_summary, evidence_index = [], {}, {}
        gaps.append("未提供证据目录，没有可引用的原文线索。")
    if review_dir is not None:
        review = Path(review_dir).resolve()
        snapshot = _read_snapshot(review, ("projects.json", "review_summary.json"))
        projects = _validate_projects(snapshot["projects.json"], evidence_index)
        review_summary = snapshot["review_summary.json"]
        if not isinstance(review_summary, dict):
            raise ValueError("review_summary.json 必须是对象")
        if evidence_dir and review_summary.get("input_dir") and Path(review_summary["input_dir"]).resolve() != Path(evidence_dir).resolve():
            raise ValueError("核验台账的 input_dir 与本次 evidence_dir 不一致，拒绝混用资料")
    else:
        projects, review_summary = [], {}
    successes = [page for page in pages if page.get("status") == "ok"]
    failures = [page for page in pages if page.get("status") != "ok"]
    sources = [{field: page.get(field) or "" for field in SOURCE_FIELDS} for page in pages]
    for source, page in zip(sources, pages):
        source["url"] = page.get("url") or page.get("requested_url") or ""
    source_ids = {page.get("source_id") for page in pages if page.get("source_id")}
    manifest_sources = manifest.get("sources") or []
    if isinstance(manifest_sources, list):
        source_ids.update(item.get("source_id") or item.get("id") for item in manifest_sources if isinstance(item, dict) and (item.get("source_id") or item.get("id")))
    else:
        manifest_sources = []
    manifest_sources = [item for item in manifest_sources if isinstance(item, dict)]
    failed_sources = sum(item.get("status") == "failed" for item in manifest_sources)
    budget_limited_sources = sum(item.get("stop_reason") == "page_budget" for item in manifest_sources)
    remaining_candidates = sum(item.get("remaining_candidates", 0) for item in manifest_sources
                               if isinstance(item.get("remaining_candidates", 0), int) and item.get("remaining_candidates", 0) > 0)
    unknown_dates = sum(_known_date(page.get("published_at")) is None for page in successes)
    unknown_evidence_dates = sum(_known_date(row.get("published_at")) is None for row in evidence)
    unknown_events = sum(not project["event_date"] for project in projects)
    dated_events = [date.fromisoformat(project["event_date"]) for project in projects if project["event_date"]]
    in_range_events = sum((lower is None or value >= lower) and (upper is None or value <= upper) for value in dated_events)
    linked = {ref for project in projects for ref in project["evidence_ids"]}
    coverage = {
        "source_count": len(source_ids), "attempted_pages": len(pages), "successful_pages": len(successes),
        "failed_pages": len(failures), "unknown_publication_date_pages": unknown_dates,
        "failed_sources": failed_sources, "page_budget_limited_sources": budget_limited_sources,
        "remaining_candidates": remaining_candidates,
        "evidence_count": len(evidence), "unknown_publication_date_evidence": unknown_evidence_dates,
        "project_count": len(projects), "unknown_event_date_projects": unknown_events,
        "event_date_in_range_projects": in_range_events,
        "event_date_out_of_range_projects": len(dated_events) - in_range_events,
        "event_date_range": {"since": interval.get("since"), "until": interval.get("until"),
                             "inclusive": True, "basis": "reviewer_supplied_event_date", "unknown_included": False},
        "unassigned_evidence_count": len(evidence_index.keys() - linked),
        "project_review_status_counts": {status: sum(project["review_status"] == status for project in projects) for status in STATUSES},
        "page_status_counts": dict(Counter(str(page.get("status") or "unknown") for page in pages)),
    }
    if failures:
        gaps.append(f"{len(failures)} 个页面抓取失败或未成功，不能把当前资料视为完整覆盖。")
    if failed_sources:
        gaps.append(f"{failed_sources} 个来源的采集状态为失败，需单独补充资料。")
    if budget_limited_sources or remaining_candidates:
        gaps.append(f"{budget_limited_sources} 个来源达到页数上限；采集记录中仍有 {remaining_candidates} 个候选链接，当前资料不代表完整网站覆盖。")
    if not successes:
        gaps.append("没有成功采集页面，不能据此形成有关研究对象的事实结论。")
    if unknown_dates or unknown_evidence_dates:
        gaps.append(f"{unknown_dates} 个成功页面及 {unknown_evidence_dates} 条线索的发布日期未知，不可据此计入限定年份。")
    if not projects:
        gaps.append("项目台账为空；尚无填写者提交的项目归并与核验决定。")
    if unknown_events:
        gaps.append(f"{unknown_events} 个填写者归并项目缺少事件日期，不能按事件年份统计。")
    if coverage["unassigned_evidence_count"]:
        gaps.append(f"{coverage['unassigned_evidence_count']} 条线索尚未关联项目，需要逐条核验与归并。")
    for key, label in (("truncated_page_count", "页面证据被截断"), ("omitted_evidence_count", "条候选线索被省略")):
        if evidence_summary.get(key):
            gaps.append(f"{evidence_summary[key]} {label}，需要查看完整原文。")
    if evidence_summary.get("read_errors"):
        gaps.append(f"证据提取存在 {len(evidence_summary['read_errors'])} 项原文读取异常。")
    gaps.append("待 GPT 综合分析：检查来源独立性、事件一致性及冲突；关键结论需逐条引用，缺失信息保留未知。")
    gaps.append("地域、应用场景及指定来源是否符合调研范围，仍需逐项目判断；日期范围内项目数不代表已满足全部研究条件。")
    if interval.get("basis") in ("event_date", "event"):
        gaps.append("事件日期范围需按项目事件日期另行核验；原始线索的发布日期筛选不能代替事件日期筛选。")
    files = ["report.json", "report.md"]
    if "csv" in selected:
        files += ["projects.csv", "evidence.csv", "sources.csv"]
    if pandas is not None:
        files.append("report.xlsx")
    summary = {
        "schema_version": 1, "generated_at": _now(), "output_dir": str(Path(output_dir).resolve()),
        "package_type": "machine_prepared_research_package", "analysis_status": "pending_gpt_synthesis",
        "scope_note": PACKAGE_NOTE, "review_note": REVIEW_NOTE, "coverage": coverage,
        "gaps": gaps, "files": files,
    }
    report = {
        **summary, "task": {key: task[key] for key in ("task_id", "title", "question", "time_range", "region", "scenarios", "source_ids", "research_type", "regions", "topics") if key in task},
        "inputs": {"collection_dir": str(Path(collection_dir).resolve()) if collection_dir else None,
                   "evidence_dir": str(Path(evidence_dir).resolve()) if evidence_dir else None,
                   "review_dir": str(Path(review_dir).resolve()) if review_dir else None},
        "collection_manifest": manifest, "evidence_summary": evidence_summary, "review_summary": review_summary,
        "projects": projects, "evidence": evidence, "sources": sources,
        "claim_policy": {"facts_automatically_verified": False, "review_status_origin": "decision_file_author"},
    }
    with _output_directory(output_dir, (collection_dir, evidence_dir, review_dir)) as target:
        _write_json(target / "report.json", report)
        (target / "report.md").write_text(_markdown(report), encoding="utf-8")
        if "csv" in selected:
            _write_csv(target / "projects.csv", PROJECT_FIELDS, projects)
            _write_csv(target / "evidence.csv", EVIDENCE_FIELDS, evidence)
            _write_csv(target / "sources.csv", SOURCE_FIELDS, sources)
        if pandas is not None:
            with pandas.ExcelWriter(target / "report.xlsx", engine="xlsxwriter", engine_kwargs={"options": {
                "strings_to_formulas": False, "strings_to_urls": False,
            }}) as writer:
                for sheet, fields, rows in (("Projects", PROJECT_FIELDS, projects), ("Evidence", EVIDENCE_FIELDS, evidence), ("Sources", SOURCE_FIELDS, sources)):
                    safe_rows = [{field: csv_safe(row.get(field)) for field in fields} for row in rows]
                    pandas.DataFrame(safe_rows, columns=fields).to_excel(writer, sheet_name=sheet, index=False)
    if not all((Path(output_dir) / filename).is_file() for filename in files):
        raise RuntimeError("交付文件不完整")
    return summary
