"""Verify actual PDFs, text hashes, version identity and dates without networking."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from pypdf import PdfReader

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def verify(root):
    root=Path(root).resolve()
    catalog=json.loads((root/"catalog.json").read_text(encoding="utf8"))
    spec=json.loads((root/"spec.snapshot.json").read_text(encoding="utf8"))
    results=[]
    for r in catalog:
        checks={}; errors=[]
        try:
            if r.get("status")!="downloaded":
                raise ValueError("not downloaded: "+r.get("error",""))
            pdf=(root/r["pdf_path"]).resolve(); text=(root/r["text_path"]).resolve()
            if not pdf.is_relative_to(root) or not text.is_relative_to(root):
                raise ValueError("path outside collection")
            checks["pdf_hash"]=sha(pdf)==r["pdf_sha256"]
            checks["text_hash"]=sha(text)==r["text_sha256"]
            reader=PdfReader(pdf)
            checks["pages"]=len(reader.pages)==r["pages"] and r["pages"]>0
            checks["pdf_signature"]=pdf.read_bytes()[:5]==b"%PDF-"
            checks["year_and_cutoff"]=r["first_submitted"].startswith(str(spec["year"])+"-") and r["first_submitted"]<=spec["cutoff"] and r["version_date"]<=spec["cutoff"]
            content=text.read_text(encoding="utf8")
            normalized=re.sub(r"\s+","",content[:20000]+content[-20000:])
            checks["arxiv_version_in_text"]=r["version_id"] in normalized
            checks["text_layer"]=len(content)>1000 and r.get("text_status")=="ok"
            checks["pdf_page_markers"]=len(re.findall(r"\[第 \d+ 页\]",content))==r["pages"]
            metadata_path=root/"raw"/(r["arxiv_id"]+".abs.html")
            checks["metadata_hash"]=sha(metadata_path)==r["metadata_sha256"]
        except Exception as ex:
            errors.append(f"{type(ex).__name__}: {ex}")
        results.append({"arxiv_id":r["arxiv_id"],"checks":checks,"errors":errors,"ok":bool(checks) and all(checks.values()) and not errors})
    summary={"status":"passed" if all(r["ok"] for r in results) else "failed","papers_checked":len(results),"passed":sum(r["ok"] for r in results),"results":results}
    (root/"verification.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf8")
    return summary

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);a=p.parse_args()
    s=verify(a.root)
    print(json.dumps({k:v for k,v in s.items() if k!="results"},ensure_ascii=False))
    sys.exit(0 if s["status"]=="passed" else 2)

