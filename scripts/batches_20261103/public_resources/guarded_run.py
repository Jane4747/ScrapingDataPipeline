"""Use the repository GGZY collector with conservative response guards.

The collector's source code is left unchanged. This task-local wrapper refuses
incorrect date filters, empty nonzero pages, repeated pages and further detail
requests after an explicit access challenge.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
import importlib.util
_snapshot_path = Path(__file__).with_name("national_ggzy_task_snapshot.py")
_spec = importlib.util.spec_from_file_location("national_ggzy_task_snapshot", _snapshot_path)
ng = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ng)


def challenge_error(error):
    return bool(re.search(r"Challenge/rate limit|HTTP\s+(?:401|403|429)\b|code\s+(?:800|829)\b", str(error), re.I))


class GuardedCollector(ng.Collector):
    def __init__(self, args):
        super().__init__(args)
        self.stop_all_requests = False

    def prepare(self):
        super().prepare()
        self.state["prepared_only"] = False
        self.state["execution_started_at"] = ng.now()
        self.state["guard_code_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self.state["collector_snapshot_sha256"] = hashlib.sha256(_snapshot_path.read_bytes()).hexdigest()
        self.state.setdefault("guard_page_hashes", {})
        self.checkpoint()

    def mark_access_stop(self, error):
        self.stop_all_requests = True
        self.state["access_stop"] = {"at": ng.now(), "reason": str(error),
                                     "action": "All subsequent list and detail requests stopped in this process"}

    async def query(self, page, task):
        if self.stop_all_requests:
            raise ng.StopCollection("All requests stopped after access challenge")
        try:
            body = await super().query(page, task)
        except ng.StopCollection as exc:
            if challenge_error(exc):
                self.mark_access_stop(exc)
            raise
        data = body["data"]
        rows = data["records"]
        total = int(data.get("total") or 0)
        if total > 0 and not rows:
            raise ng.StopCollection("Integrity guard: nonzero search total with empty page; window remains incomplete")
        for row in rows:
            published = str(row.get("publishTime") or "")[:10]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", published) or not task["start"] <= published <= task["end"]:
                raise ng.StopCollection(
                    f"Integrity guard: returned publication date {published!r} outside query window {task['start']}..{task['end']}; filter not proven"
                )
        if rows:
            window = {k: task.get(k) for k in ("start", "end", "word", "source", "stage", "endpoint")}
            window_key = hashlib.sha256(json.dumps(window, sort_keys=True).encode()).hexdigest()[:24]
            signature = hashlib.sha256(json.dumps(
                [[r.get("id"), r.get("url"), r.get("publishTime"), r.get("title")] for r in rows],
                ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            previous = self.state["guard_page_hashes"].setdefault(window_key, {})
            for old_page, old_signature in previous.items():
                if old_page != str(task["page"]) and old_signature == signature:
                    raise ng.StopCollection("Integrity guard: repeated search page at different page number; window remains incomplete")
            previous[str(task["page"])] = signature
        return body

    async def details(self, context, count):
        if self.stop_all_requests:
            return
        try:
            return await super().details(context, count)
        except ng.StopCollection as exc:
            if challenge_error(exc):
                self.mark_access_stop(exc)
            raise


if __name__ == "__main__":
    ng.Collector = GuardedCollector
    raise SystemExit(ng.main())
