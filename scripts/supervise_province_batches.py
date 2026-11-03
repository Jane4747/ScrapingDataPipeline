"""Unattended handover for the province batches.

Batch 1 and batch 2 hit the same endpoint, so they must not run at the same
time (nine concurrent workers already tripped the platform's rate limit once).
This supervisor only does three things, and does nothing when unsure:

1. Batch 1 run has settled -> enqueue batch 2 (once, recorded in the state file).
2. Batch 2 run has settled -> publish both batches to the handover folder.
3. Copy the national-level three-source workbook in as reference, once.

It never re-runs a failed region and never changes the search scope; recovery
of individual regions stays a deliberate, manual decision.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

BEIJING = timezone(timedelta(hours=8))
ACTIVE = {"running", "queued", "pending", "not started"}


def stamp():
    return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def read(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def latest_run(api, dag_name, dagu=None, dagu_home=None):
    """Return (run_id, status_label) or (None, None) when the DAG never ran.

    The HTTP index can come back empty even when runs exist on disk (observed
    after a host restart), so fall back to the CLI history, which reads the same
    run records the worker wrote.
    """
    url = f"{api}/api/v1/dag-runs?name={dag_name}&limit=1"
    failure = None
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            payload = json.load(response)
        runs = payload.get("dagRuns") or []
        if runs:
            return runs[0].get("dagRunId"), runs[0].get("statusLabel")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        failure = f"unreachable: {exc}"

    if dagu and dagu_home:
        command = [str(dagu), "history", "--dagu-home", str(dagu_home), "--format", "json",
                   "--limit", "1", dag_name]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                runs = json.loads(result.stdout or "[]")
                if runs:
                    status = (runs[0].get("status") or "").replace("_", " ")
                    return runs[0].get("dagRunId"), status
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            pass
    return None, failure


def settled(status):
    return status is not None and status not in ACTIVE


def enqueue(dagu, dagu_home, dag_file, run_id):
    command = [str(dagu), "enqueue", "--dagu-home", str(dagu_home), "--run-id", run_id, str(dag_file)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"enqueue failed ({result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
    return run_id


def await_run(dagu, dagu_home, run_id, wait=45):
    """Return (status, error) for a just-enqueued run, or (None, None) if unseen."""
    deadline = time.monotonic() + wait
    last = (None, None)
    while time.monotonic() < deadline:
        command = [str(dagu), "history", "--dagu-home", str(dagu_home), "--format", "json",
                   "--limit", "5", "--run-id", run_id]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            runs = json.loads(result.stdout or "[]") if result.returncode == 0 else []
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            runs = []
        for run in runs:
            if run.get("dagRunId") == run_id:
                last = ((run.get("status") or "").replace("_", " "), run.get("error") or "")
                if last[0] not in ACTIVE:
                    return last
        time.sleep(5)
    return last


def publish(task_dir, python, target=None):
    command = [str(python), "-B", "-m", "pipeline.research.province_update", "publish"]
    if target:
        command += ["--target", str(target)]
    environment = {"PROVINCE_UPDATE_TASK_DIR": str(Path(task_dir).resolve()), "PYTHONUTF8": "1",
                   "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    result = subprocess.run(command, capture_output=True, text=True,
                            cwd=str(Path(__file__).resolve().parents[1]), env={**os.environ, **environment})
    line = (result.stdout or "").strip().splitlines()
    return result.returncode, line[-1] if line else (result.stderr or "").strip()[-300:]


def copy_national(source, target):
    """Copy the national-level three-source delivery as read-only reference."""
    source = Path(source)
    folder = Path(target) / "00_全国层_央采与全国平台"
    folder.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in ("三平台医疗数字化采购_2024年至今.xlsx", "公告明细.csv", "records.json", "report.md"):
        item = source / name
        if item.exists():
            destination = folder / name
            destination.write_bytes(item.read_bytes())
            copied.append(name)
    summary = read(source.parent / "summary.json", {}) or {}
    lines = ["# 全国层：央采 + 全国公共资源交易平台 + 北京公共资源交易平台", "",
             "| 项目 | 值 |", "| --- | --- |",
             "| 口径 | 按来源平台切分，不是按省份 |",
             "| 来源与条数 | 中央政府采购 60 / 全国平台 361 / 北京平台 661 |",
             "| 记录数 | " + str(summary.get("records", 1082)) + " 条 |",
             "| 发布日期范围 | 2024-01-01 至 2026-10-29 |", "",
             "## 与其他目录的关系", "",
             "- 本目录是**全国层**来源汇总，`01_地方_分省第1批`、`02_地方_分省第2批` 是**地域层**。",
             "- 两层口径不同，**数字不能相加**：同一条公告既可能出现在全国层，也可能出现在某个省。",
             "- 全国层里的「北京平台 661 条」与地方第1批的「北京」是不同入口，条数不一致属正常。"]
    (folder / "说明_全国层.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return copied


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--api", default="http://127.0.0.1:8098")
    parser.add_argument("--dagu", default=r"C:\Users\Jane\.codex\.chatgpt-projects\g-p-6ad9720f1cd48191b33b188cf4398a78\work\searchingagent-dagu-20261029\bin\dagu.exe")
    parser.add_argument("--dagu-home", default=str(root / "outputs/dagu-runtime"))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--task1", default=str(root / "outputs/province-updates/province-b1-2024-20261029"))
    parser.add_argument("--task2", default=str(root / "outputs/province-updates/province-b2-2024-20261029"))
    parser.add_argument("--dag2", default=str(root / "outputs/dagu-runtime/dags/pt-province-b2-2024-20261029.yaml"))
    parser.add_argument("--national", default=str(root / "outputs/tender-updates/medical-2024-20261029/delivery"))
    parser.add_argument("--state", default=str(root / "outputs/province-updates/_supervisor.json"))
    parser.add_argument("--run-id-prefix", default="province-b2-2024-20261029")
    parser.add_argument("--once-publish", action="store_true", help="Publish both batches now without checking Dagu")
    args = parser.parse_args(argv)

    state = read(args.state, {}) or {}
    state.setdefault("events", [])
    state["checked_at"] = stamp()
    actions = []

    def record(event, **fields):
        state["events"].append({"at": stamp(), "event": event, **fields})
        actions.append({"event": event, **fields})

    task1 = Path(args.task1)
    task2 = Path(args.task2)

    if args.once_publish:
        for task in (task1, task2):
            code, output = publish(task, args.python)
            record("publish", task=task.name, exit=code, output=output)
        state["published"] = True
        write(args.state, state)
        print(json.dumps({"actions": actions}, ensure_ascii=False, indent=1))
        return 0

    run1, status1 = latest_run(args.api, "pt-province-b1-2024-20261029", args.dagu, args.dagu_home)
    run2, status2 = latest_run(args.api, "pt-province-b2-2024-20261029", args.dagu, args.dagu_home)
    state.update({"batch1_run": run1, "batch1_status": status1, "batch2_run": run2, "batch2_status": status2})

    if not settled(status1):
        record("wait", reason="batch 1 still active", status=status1)
        write(args.state, state)
        print(json.dumps({"actions": actions, "batch1": status1, "batch2": status2}, ensure_ascii=False, indent=1))
        return 0

    if not state.get("batch2_enqueued") and not (task2 / "regions").exists():
        record("skip", reason="batch 2 folder is not planned yet")
    elif not state.get("batch2_enqueued") and settled(status2) and status2 is not None:
        state["batch2_enqueued"] = run2
        record("note", reason="batch 2 already ran", run=run2, status=status2)
    elif not state.get("batch2_enqueued") and not state.get("batch2_needs_manual"):
        run_id = args.run_id_prefix + "-" + datetime.now(BEIJING).strftime("%H%M%S")
        try:
            enqueue(args.dagu, args.dagu_home, args.dag2, run_id)
        except (RuntimeError, OSError) as exc:
            record("enqueue_failed", error=str(exc)[:300])
        else:
            label, error = await_run(args.dagu, args.dagu_home, run_id)
            if label and "not queued" in (error or ""):
                # This Dagu build dequeues into a run record that is already
                # terminal, so every enqueued run dies before its first step.
                # Leave one clear note instead of spawning a failed run each hour.
                state["batch2_needs_manual"] = True
                record("enqueue_unsupported", run=run_id, status=label,
                       hint="start it from a console: powershell -ExecutionPolicy Bypass -File "
                            "scripts\\resume-province-batch.ps1 -Batch 2")
            else:
                state["batch2_enqueued"] = run_id
                record("enqueue_batch2", run=run_id, after_batch1=run1, batch1_status=status1)

    if state.get("batch2_enqueued") and settled(status2):
        if not state.get("published") or state.get("published_for") != run2:
            for task in (task1, task2):
                code, output = publish(task, args.python)
                record("publish", task=task.name, exit=code, output=output)
            if not state.get("national_copied") and Path(args.national).exists():
                files = copy_national(args.national, read(Path(args.task1) / "publish.json", {}).get("target"))
                state["national_copied"] = True
                record("copy_national", files=len(files))
            state["published"] = True
            state["published_for"] = run2

    write(args.state, state)
    print(json.dumps({"actions": actions, "batch1": status1, "batch2": status2}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
