"""Offline, explicit project decisions over saved source excerpts.

Validation checks the decision file's structure and references. It never
establishes that a source statement or a reviewer's conclusion is true.
"""

from contextlib import contextmanager
import csv
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
import uuid

from .research.deployments import csv_safe


STATUSES = ("pending", "source_claim", "corroborated", "conflict", "insufficient_evidence")
PROJECT_FIELDS = (
    "project_id", "name", "entity", "product", "application_org", "location",
    "event_date", "stage", "evidence_ids", "review_status", "reviewer", "reviewed_at", "notes",
)
REVIEW_NOTE = (
    "项目仅由填写者显式归并；review_status 是填写者的核验声明，不是程序事实验证。"
    "corroborated 仅通过引用数量、来源与站点主机差异及核验记录的结构检查，"
    "不证明来源相互独立、陈述一致或项目已实际落地。线索数不等于项目数。"
)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 JSON 文件 {path}: {exc}") from exc


def _read_snapshot(root, names, optional=()):
    """Read a stable multi-file snapshot; refuse unfinished upstream writes."""
    root = Path(root).resolve()
    locks = [root / name for name in (".write.lock", "evidence.lock", "run.lock")]
    if any(lock.exists() for lock in locks):
        raise ValueError(f"输入目录仍有写入锁，请等待上游任务完成：{root}")
    documents, fingerprints = {}, {}
    try:
        for name in names:
            path = root / name
            if name in optional and not path.exists():
                documents[name], fingerprints[name] = {}, None
                continue
            data = path.read_bytes()
            documents[name] = json.loads(data.decode("utf-8-sig"))
            fingerprints[name] = hashlib.sha256(data).digest()
        for name in names:
            path = root / name
            current = hashlib.sha256(path.read_bytes()).digest() if path.exists() else None
            if current != fingerprints[name]:
                raise ValueError(f"读取期间输入文件发生变化，拒绝混合快照：{path}")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取完整输入快照 {root}: {exc}") from exc
    if any(lock.exists() for lock in locks):
        raise ValueError(f"读取期间输入目录开始写入，请等待上游任务完成：{root}")
    return documents


def _write_json(path, value):
    """Atomic publication; each writer owns the enclosing output lock."""
    path = Path(path)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _output_directory(output_dir, inputs=()):
    """Serialize writers, including the check that an existing target is empty."""
    target = Path(output_dir).resolve()
    for item in inputs:
        if item is None:
            continue
        source = Path(item).resolve()
        if target == source or source.is_relative_to(target):
            raise ValueError("输出目录不能为输入目录或其父目录")
    if target.exists() and not target.is_dir():
        raise ValueError("输出路径不是目录")
    target.mkdir(parents=True, exist_ok=True)
    lock = target / ".write.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError("输出目录正在被其他任务使用，请使用独立输出目录") from None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        if any(item.name != lock.name for item in target.iterdir()):
            raise ValueError("输出目录非空，拒绝覆盖已有文件")
        yield target
    finally:
        lock.unlink(missing_ok=True)


def _write_csv(path, fields, rows):
    with Path(path).open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: csv_safe(row.get(field)) for field in fields} for row in rows)


def _load_evidence(evidence_dir):
    root = Path(evidence_dir).resolve()
    snapshot = _read_snapshot(root, ("deployment_evidence.json", "summary.json"))
    rows, summary = snapshot["deployment_evidence.json"], snapshot["summary.json"]
    if not isinstance(rows, list) or not isinstance(summary, dict):
        raise ValueError("证据文件必须是对象列表，summary.json 必须是对象")
    index = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("evidence_id"), str) or not row["evidence_id"].strip():
            raise ValueError("每条证据必须包含非空 evidence_id")
        if row["evidence_id"] in index:
            raise ValueError(f"重复 evidence_id: {row['evidence_id']}")
        index[row["evidence_id"]] = row
    return rows, summary, index


def _validate_date(value, field, timestamp=False):
    if not value:
        return
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            date.fromisoformat(value)
        elif timestamp and re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", value):
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError(f"{field} 必须是有效 ISO 日期" + ("或日期时间" if timestamp else " YYYY-MM-DD")) from None


def _site_host(row):
    try:
        url = urlsplit(str(row.get("url") or ""))
        host = (url.hostname or "").lower().rstrip(".")
        if url.scheme not in ("http", "https") or not host:
            return ""
        # www aliases do not constitute a second site.
        return host[4:] if host.startswith("www.") else host
    except ValueError:
        return ""


def _validate_projects(rows, evidence):
    if not isinstance(rows, list):
        raise ValueError("decisions.projects 必须是列表")
    projects, ids = [], set()
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("每个项目必须是对象")
        unknown = set(item) - set(PROJECT_FIELDS)
        if unknown:
            raise ValueError(f"未知项目字段: {', '.join(sorted(unknown))}")
        row = {field: item.get(field, "") for field in PROJECT_FIELDS}
        for field in PROJECT_FIELDS:
            if field != "evidence_ids" and not isinstance(row[field], str):
                raise ValueError(f"项目 {field} 必须是字符串")
        for field in ("project_id", "name"):
            if not row[field].strip():
                raise ValueError(f"项目必须包含非空 {field}")
        if row["project_id"] in ids:
            raise ValueError(f"重复 project_id: {row['project_id']}")
        ids.add(row["project_id"])
        references = row["evidence_ids"]
        if not isinstance(references, list) or not references or any(not isinstance(ref, str) or ref not in evidence for ref in references):
            raise ValueError(f"项目 {row['project_id']} 必须引用存在的非空 evidence_ids 列表")
        if len(references) != len(set(references)):
            raise ValueError(f"项目 {row['project_id']} 包含重复 evidence_ids")
        row["review_status"] = row["review_status"] or "pending"
        if row["review_status"] not in STATUSES:
            raise ValueError(f"review_status 必须为 {', '.join(STATUSES)}")
        _validate_date(row["event_date"], "event_date")
        _validate_date(row["reviewed_at"], "reviewed_at", timestamp=True)
        if row["review_status"] == "corroborated":
            if not row["reviewer"].strip() or not row["reviewed_at"]:
                raise ValueError("corroborated 项目必须填写 reviewer 和 reviewed_at")
            pairs = [(str(evidence[ref].get("source_id") or "").strip(), _site_host(evidence[ref])) for ref in references]
            if not any(a[0] and b[0] and a[1] and b[1] and a[0] != b[0] and a[1] != b[1]
                       for a in pairs for b in pairs):
                raise ValueError("corroborated 必须引用至少两个不同 source_id 且不同站点主机的证据")
        projects.append(row)
    return projects


def build_review(evidence_dir, output_dir, decisions_path=None):
    """Create a review queue and explicit project register without inferring facts."""
    evidence, evidence_summary, index = _load_evidence(evidence_dir)
    if decisions_path is None:
        projects = []
    else:
        decisions = _read_json(decisions_path)
        if not isinstance(decisions, dict) or "projects" not in decisions:
            raise ValueError("decisions 必须是含 projects 列表的对象")
        projects = _validate_projects(decisions["projects"], index)
    assignments = {key: [] for key in index}
    for project in projects:
        for reference in project["evidence_ids"]:
            assignments[reference].append(project)
    queue = []
    for row in evidence:
        linked = assignments[row["evidence_id"]]
        queue.append({
            **row, "queue_status": "linked" if linked else "pending",
            "project_ids": [project["project_id"] for project in linked],
            "project_review_statuses": {project["project_id"]: project["review_status"] for project in linked},
            "review_note": "关联项目不代表原文陈述已获程序验证。" if linked else "待核验；尚未归并为项目。",
        })
    files = ["projects.json", "projects.csv", "review_queue.json", "review_template.json", "review_summary.json"]
    summary = {
        "schema_version": 1, "generated_at": _now(),
        "input_dir": str(Path(evidence_dir).resolve()), "output_dir": str(Path(output_dir).resolve()),
        "decisions_path": str(Path(decisions_path).resolve()) if decisions_path else None,
        "evidence_count": len(evidence), "project_count": len(projects),
        "linked_evidence_count": sum(bool(value) for value in assignments.values()),
        "unassigned_evidence_count": sum(not value for value in assignments.values()),
        "status_counts": {status: sum(project["review_status"] == status for project in projects) for status in STATUSES},
        "unknown_publication_date_pages": evidence_summary.get("unknown_publication_date_pages"),
        "review_note": REVIEW_NOTE, "files": files,
    }
    template = {
        "projects": [], "instructions": REVIEW_NOTE,
        "project_fields": list(PROJECT_FIELDS), "review_status_values": list(STATUSES),
        "required_fields": ["project_id", "name", "evidence_ids"],
        "date_format": "event_date: YYYY-MM-DD；reviewed_at: ISO 日期或日期时间；未知留空。",
        "corroborated_requirements": "填写 reviewer/reviewed_at；至少两条不同 source_id 且不同站点主机的证据。须由填写者核实独立性和一致性。",
    }
    inputs = [evidence_dir] + ([decisions_path] if decisions_path else [])
    with _output_directory(output_dir, inputs) as target:
        _write_json(target / "projects.json", projects)
        _write_csv(target / "projects.csv", PROJECT_FIELDS, projects)
        _write_json(target / "review_queue.json", queue)
        _write_json(target / "review_template.json", template)
        _write_json(target / "review_summary.json", summary)
    return summary
