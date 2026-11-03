"""Versioned, resumable arXiv literature collection, reusing the repository Fetcher.

Run from the coding repository with: python -B literature/collector.py --spec ...
No paid search API or model is called. Discovery queries and curated candidates
are inputs; executing this command does not imply those queries were searched.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import sys

from bs4 import BeautifulSoup
from pypdf import PdfReader

try:
    from pipeline.research.fetch import Fetcher
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from pipeline.research.fetch import Fetcher


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def validate_spec(spec):
    allowed = {"schema_version", "task_id", "title", "question", "year", "cutoff",
               "allow_network", "output_dir", "queries", "candidates", "delay", "max_bytes"}
    if set(spec) - allowed:
        raise ValueError("Unknown spec fields: " + str(sorted(set(spec) - allowed)))
    if spec.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", spec.get("task_id", "")):
        raise ValueError("Invalid task_id")
    if type(spec.get("year")) is not int:
        raise ValueError("year must be integer")
    cutoff = date.fromisoformat(spec["cutoff"])
    if cutoff.year != spec["year"] or not isinstance(spec.get("output_dir"), str):
        raise ValueError("Invalid cutoff/output_dir")
    if type(spec.get("allow_network", False)) is not bool:
        raise ValueError("allow_network must be boolean")
    if not 15 <= spec.get("delay", 15) <= 120:
        raise ValueError("delay must be between 15 and 120 seconds")
    if not 1024 <= spec.get("max_bytes", 64 * 1024 * 1024) <= 128 * 1024 * 1024:
        raise ValueError("Invalid max_bytes")
    if not isinstance(spec.get("candidates"), list) or not 1 <= len(spec["candidates"]) <= 100:
        raise ValueError("candidates must contain 1..100 records")
    seen, clean = set(), []
    for item in spec["candidates"]:
        if set(item) - {"arxiv_id", "category", "discovery_url", "reason"}:
            raise ValueError("Unknown candidate field")
        identifier = item.get("arxiv_id", "")
        if not re.fullmatch(r"\d{4}\.\d{4,5}", identifier):
            raise ValueError("Only modern, unversioned arXiv identifiers are accepted")
        if identifier not in seen:
            clean.append(dict(item))
            seen.add(identifier)
    return {**spec, "candidates": clean}


def parse_abs(raw, identifier, cutoff):
    soup = BeautifulSoup(raw, "html.parser")

    def meta(name):
        return [node.get("content", "").strip() for node in soup.find_all("meta", attrs={"name": name})]

    title = meta("citation_title")
    authors = meta("citation_author")
    dates = meta("citation_date")
    if not title or not dates:
        raise ValueError("Missing official title/publication date")
    published = date.fromisoformat(dates[0].replace("/", "-"))
    if published > cutoff:
        return {"arxiv_id": identifier, "title": title[0], "authors": authors,
                "first_submitted": published.isoformat(), "selected_version": None,
                "version_id": None, "version_date": None, "abstract": "",
                "abs_url": f"https://arxiv.org/abs/{identifier}", "pdf_url": None}
    history = soup.select_one(".submission-history")
    if history is None:
        raise ValueError("Missing submission history; cannot pin a version")
    history_text = history.get_text(" ", strip=True)
    versions = []
    for match in re.finditer(r"\[v(\d+)\]\s*(?:[A-Za-z]{3},\s*)?(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})", history_text):
        posted = datetime.strptime(match[2], "%d %b %Y").date()
        if posted <= cutoff:
            versions.append((int(match[1]), posted.isoformat()))
    if not versions:
        raise ValueError("No version on or before cutoff")
    version, version_date = max(versions)
    abstract_node = soup.select_one("blockquote.abstract")
    abstract = re.sub(r"^Abstract:\s*", "", abstract_node.get_text(" ", strip=True)) if abstract_node else ""
    links = sorted({node["href"] for node in soup.select(".comments a[href], blockquote.abstract a[href]")
                    if node["href"].startswith("https://")})
    license_node = soup.select_one(".full-text .abs-license a, .abs-license a")
    journal = meta("citation_journal_title")
    return {"arxiv_id": identifier, "title": title[0], "authors": authors,
            "first_submitted": published.isoformat(), "selected_version": version,
            "version_date": version_date, "version_id": f"{identifier}v{version}",
            "abstract": abstract, "author_links": links,
            "journal_reference": journal[0] if journal else None,
            "publication_type": "arXiv preprint; peer-review status not inferred",
            "license_url": license_node.get("href") if license_node else None,
            "abs_url": f"https://arxiv.org/abs/{identifier}v{version}",
            "pdf_url": f"https://arxiv.org/pdf/{identifier}v{version}"}


def validate_pdf(raw):
    if not raw.lstrip().startswith(b"%PDF-"):
        raise ValueError("Response is not a PDF")
    reader = PdfReader(io.BytesIO(raw), strict=False)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 500:
        raise ValueError("Encrypted or invalid page count")
    return len(reader.pages)


def verified_file(root, record, key, hash_key):
    relative = record.get(key)
    if not relative or not record.get(hash_key):
        return False
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        return False
    return digest(path.read_bytes()) == record[hash_key]


def export(root, spec, records):
    included = [r for r in records if r.get("in_scope")]
    fields = ["arxiv_id", "title", "first_submitted", "version_id", "category", "status", "pdf_path", "pdf_sha256", "abs_url", "pdf_url", "error"]
    with (root / "catalog.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in included:
            safe = {k: ("'" + str(v) if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v) for k, v in row.items()}
            writer.writerow(safe)
    bib = []
    for r in included:
        bib.append("@misc{arxiv" + r["arxiv_id"].replace(".", "") + ",\n"
                   + "  title = {" + r["title"].replace("{", "").replace("}", "") + "},\n"
                   + "  author = {" + " and ".join(r["authors"]) + "},\n"
                   + f"  year = {{{spec['year']}}},\n  eprint = {{{r['arxiv_id']}}},\n"
                   + "  archivePrefix = {arXiv},\n  url = {" + r["abs_url"] + "}\n}")
    (root / "references.bib").write_text("\n\n".join(bib) + "\n", encoding="utf-8")
    successes = sum(r.get("status") == "downloaded" for r in included)
    failed = [r for r in records if r.get("status") == "failed"]
    summary = {"schema_version": 1, "task_id": spec["task_id"], "finished_at": utcnow(),
               "cutoff": spec["cutoff"], "candidate_count": len(records), "in_scope_count": len(included),
               "downloaded_count": successes, "failed_count": len(failed),
               "excluded_count": sum(r.get("status") == "excluded" for r in records),
               "status": "partial" if failed else "completed", "output_dir": str(root),
               "coverage": "Curated topic collection; not an exhaustive or systematic review"}
    write_json(root / "catalog.json", records)
    write_json(root / "failures.json", failed)
    write_json(root / "manifest.json", summary)
    return summary


def collect(spec_path, dry_run=False, resume=False, fetcher_factory=Fetcher):
    spec_path = Path(spec_path).resolve()
    spec = validate_spec(json.loads(spec_path.read_text(encoding="utf-8-sig")))
    root = (spec_path.parent / spec["output_dir"]).resolve()
    if root == spec_path.parent or root in spec_path.parents:
        raise ValueError("Output must be a dedicated directory")
    if dry_run:
        return {"status": "validated", "task_id": spec["task_id"], "output_dir": str(root),
                "candidate_count": len(spec["candidates"]), "allow_network": spec.get("allow_network", False)}
    if not spec.get("allow_network", False):
        raise ValueError("Network collection requires allow_network=true")
    snapshot = root / "spec.snapshot.json"
    if root.exists() and any(root.iterdir()) and not resume:
        raise ValueError("Output exists; use --resume or a new task/output")
    if resume and not snapshot.exists():
        raise ValueError("Cannot resume without snapshot")
    if snapshot.exists() and json.loads(snapshot.read_text(encoding="utf-8")) != spec:
        raise ValueError("Spec changed; create a new task")
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "collection.lock"
    handle = lock.open("x", encoding="utf-8")
    fetcher = None
    try:
        handle.write(utcnow())
        handle.close()
        write_json(snapshot, spec)
        for directory in ("pdfs", "text", "metadata", "raw", "receipts"):
            (root / directory).mkdir(exist_ok=True)
        catalog = root / "catalog.json"
        records = json.loads(catalog.read_text(encoding="utf-8")) if catalog.exists() else []
        previous = {r["arxiv_id"]: r for r in records}
        records = []
        fetcher = fetcher_factory(timeout=45, retries=1, delay=spec.get("delay", 15),
                                  max_bytes=spec.get("max_bytes", 64 * 1024 * 1024))
        for item in spec["candidates"]:
            identifier = item["arxiv_id"]
            old = previous.get(identifier, {})
            if (old.get("status") == "downloaded"
                    and verified_file(root, old, "pdf_path", "pdf_sha256")
                    and verified_file(root, old, "text_path", "text_sha256")):
                records.append(old)
                continue
            record = {**item, "status": "failed", "error": "", "collected_at": utcnow()}
            try:
                metadata_file = root / "metadata" / f"{identifier}.json"
                if metadata_file.exists():
                    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
                else:
                    result = fetcher.fetch(f"https://arxiv.org/abs/{identifier}", ["arxiv.org"])
                    raw = result.pop("raw", b"")
                    write_json(root / "receipts" / f"{identifier}.abs.json", {k:v for k,v in result.items() if k not in {"text", "links"}})
                    if result["status"] != "ok":
                        raise ValueError("Metadata: " + result["status"] + ": " + result.get("error", ""))
                    metadata = parse_abs(raw, identifier, date.fromisoformat(spec["cutoff"]))
                    metadata["metadata_sha256"] = digest(raw)
                    (root / "raw" / f"{identifier}.abs.html").write_bytes(raw)
                    write_json(metadata_file, metadata)
                record.update(metadata)
                record["in_scope"] = (record["first_submitted"].startswith(str(spec["year"]) + "-")
                                      and record["first_submitted"] <= spec["cutoff"])
                if not record["in_scope"]:
                    record.update(status="excluded", error="First submission outside year/cutoff")
                else:
                    result = fetcher.fetch(record["pdf_url"], ["arxiv.org"])
                    raw = result.pop("raw", b"")
                    write_json(root / "receipts" / f"{identifier}.pdf.json", {k:v for k,v in result.items() if k not in {"text", "links"}})
                    pages = validate_pdf(raw)
                    filename = record["version_id"] + ".pdf"
                    target = root / "pdfs" / filename
                    if target.exists() and digest(target.read_bytes()) != digest(raw):
                        raise ValueError("Existing pinned PDF differs; refusing overwrite")
                    target.write_bytes(raw)
                    text_path = root / "text" / (record["version_id"] + ".txt")
                    text = result.get("text", "")
                    text_path.write_text(text, encoding="utf-8")
                    record.update(status="downloaded", pages=pages, bytes=len(raw), pdf_sha256=digest(raw),
                                  pdf_path=target.relative_to(root).as_posix(),
                                  text_path=text_path.relative_to(root).as_posix(),
                                  text_sha256=digest(text_path.read_bytes()),
                                  text_status=result["status"], text_warning=result.get("error", ""))
            except Exception as exc:
                record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            records.append(record)
            write_json(catalog, records)
            print(f"{len(records)}/{len(spec['candidates'])} {identifier} {record['status']} {record.get('error','')}", file=sys.stderr, flush=True)
        return export(root, spec, records)
    finally:
        handle.close()
        if fetcher is not None:
            fetcher.close()
        lock.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = collect(args.spec, args.dry_run, args.resume)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 3 if result["status"] == "partial" else 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
