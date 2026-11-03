"""Pull the official .doc/.docx/.pdf attachment behind a registry table row
and dump it as structured JSON.

The point of this script is evidence hygiene, not parsing cleverness. Each run
records where the file came from (source_url), when it was fetched, and refuses
to invent rows: whatever the official attachment does not contain stays absent
from the output, so a later reader can tell "not found" apart from "not looked
for".

It also converts .doc to a text/table dump because, on Windows, the legacy
binary format cannot be read by any pure-python parser available here; Word COM
is the only faithful reader and it is already used elsewhere in this repo.

Usage:
  "D:/Anaconda3/envs/BigData/python.exe" -B scripts/institution_doc_extract.py \
      --url <attachment-url> --out outputs/institution-registry-20261030/_extract/<id>.json
      [--raw-dir outputs/institution-registry-20261030/_sources] [--no-download]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def safe_name(url: str) -> str:
    tail = unquote(urlparse(url).path).rstrip("/").split("/")[-1]
    keep = "".join(ch for ch in tail if ch not in '\\/:*?"<>|')
    return keep or "attachment.doc"


def download(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["curl", "-sL", "--max-time", "120", "-A", UA, "-o", str(dest), url],
        check=True,
    )
    return dest


def read_doc_via_com(path: Path):
    import win32com.client as wc

    word = wc.Dispatch("Word.Application")
    word.Visible = False
    text = ""
    tables = []
    try:
        doc = word.Documents.Open(str(path), ReadOnly=True)
        try:
            text = doc.Content.Text
            for ti in range(1, doc.Tables.Count + 1):
                t = doc.Tables(ti)
                rows = []
                for r in range(1, t.Rows.Count + 1):
                    cells = []
                    for c in range(1, t.Columns.Count + 1):
                        try:
                            raw = t.Cell(r, c).Range.Text
                        except Exception:
                            raw = ""
                        cells.append(raw.replace("\x07", "").replace("\r", "").strip())
                    rows.append(cells)
                tables.append({"rows": rows})
        finally:
            doc.Close(False)
    finally:
        word.Quit()
    return text, tables


def read_pdf(path: Path):
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [(p.extract_text() or "") for p in reader.pages]
    return "\n".join(pages), []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--evidence-id", default="")
    ap.add_argument("--raw-dir", default="outputs/institution-registry-20261030/_sources")
    ap.add_argument("--local", default="", help="已下载好的本地文件，跳过下载")
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    raw_dir = Path(args.raw_dir)
    if args.local:
        path = Path(args.local)
    else:
        path = raw_dir / safe_name(args.url)
        download(args.url, path)

    if not path.exists() or path.stat().st_size == 0:
        print(json.dumps({"ok": False, "reason": "download_failed",
                          "url": args.url, "path": str(path)}, ensure_ascii=False))
        sys.exit(1)

    suffix = path.suffix.lower()
    if suffix in {".doc", ".docx"}:
        text, tables = read_doc_via_com(path)
    elif suffix == ".pdf":
        text, tables = read_pdf(path)
    else:
        text, tables = path.read_text(encoding="utf-8", errors="replace"), []

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "evidence_id": args.evidence_id,
        "source_url": args.url if not args.local else "",
        "local_path": str(path),
        "bytes": path.stat().st_size,
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "note": args.note,
        "table_count": len(tables),
        "tables": tables,
        "text": text,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "evidence_id": args.evidence_id,
        "out": str(out),
        "bytes": path.stat().st_size,
        "text_chars": len(text),
        "table_count": len(tables),
        "table_sizes": [f"{len(t['rows'])}x{len(t['rows'][0]) if t['rows'] else 0}"
                        for t in tables],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
