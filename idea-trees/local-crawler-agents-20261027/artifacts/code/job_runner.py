"""Bounded background supervisor: logs, deadline and process-tree cleanup."""
from __future__ import annotations

import json
import subprocess
import sys

import psutil

from common import ROOT, RUNS, child_environment, interpreter, now, write_json


def main(job_id: str) -> None:
    folder = RUNS / job_id
    request = json.loads((folder / "input.json").read_text(encoding="utf-8"))
    state = json.loads((folder / "state.json").read_text(encoding="utf-8"))
    state.update(status="running", started_at=now())
    write_json(folder / "state.json", state)
    try:
        with (folder / "worker.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([str(interpreter(request["engine"])), str(ROOT / "worker.py"), str(folder)], cwd=str(folder), env=child_environment(), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            state["worker_pid"] = process.pid
            write_json(folder / "state.json", state)
            try:
                code = process.wait(timeout=request["timeout_seconds"])
            except subprocess.TimeoutExpired:
                parent = psutil.Process(process.pid)
                for child in reversed(parent.children(recursive=True)):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                parent.kill()
                process.wait(timeout=15)
                raise TimeoutError("Job exceeded its configured deadline")
        if code != 0:
            raise RuntimeError("Worker exited with code " + str(code) + "; see worker.log")
        if not (folder / "result.json").exists():
            raise RuntimeError("Worker returned without a result")
        state.update(status="completed", finished_at=now())
    except Exception as exc:
        state.update(status="failed", error=str(exc), finished_at=now())
    write_json(folder / "state.json", state)


if __name__ == "__main__":
    main(sys.argv[1])
