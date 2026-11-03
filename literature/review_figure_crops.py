"""Apply explicit visually reviewed crop corrections; preserve every replaced output."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil

s=importlib.util.spec_from_file_location("extract_figures",Path(__file__).with_name("extract_figures.py"))
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def main():
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);p.add_argument("--corrections",type=Path,required=True);p.add_argument("--attempt",type=int,default=1)
    args=p.parse_args();root=args.root.resolve()
    if (root/"extraction.lock").exists():raise ValueError("Extraction is still locked")
    if args.attempt<1:raise ValueError("attempt must be positive")
    suffix="" if args.attempt==1 else f"_{args.attempt:03d}"
    history_file=root/("review_history"+suffix+".json")
    if history_file.exists():raise ValueError("A final crop review already exists; create a new review attempt")
    correction=json.loads(args.corrections.read_text(encoding="utf8"))
    override_path=Path(__file__).with_name("figure_overrides.json")
    override_data=json.loads(override_path.read_text(encoding="utf8"))
    backups=root/"qa"/("pre_review"+suffix);backups.mkdir(parents=True)
    shutil.copy2(override_path,backups/"figure_overrides.json")
    for name in ["figures_manifest.json","manifest.json","verification.json"]:
        shutil.copy2(root/name,backups/name)
    results=[json.loads(f.read_text(encoding="utf8")) for f in sorted((root/"paper_results").glob("*.json"))]
    result_map={r["arxiv_id"]:r for r in results};history=[]
    for n,c in enumerate(correction["items"],1):
        result=result_map[c["arxiv_id"]];f=next(f for f in result["figures"] if f["number"]==c["number"])
        source=Path(result["source_pdf"]);doc=m.pdfium.PdfDocument(source);page=doc[c["page"]-1]
        w,h=page.get_size();x0,y0,x1,y1=c["crop"]
        if not(0<=x0<x1<=w and 0<=y0<y1<=h):raise ValueError("Invalid reviewed crop")
        image=m.render_crop(page,c["crop"],240);page.close();doc.close()
        original=(root/f["file"]).resolve();thumbnail=(root/f["thumbnail"]).resolve()
        if not original.is_relative_to(root) or not thumbnail.is_relative_to(root):raise ValueError("Output escapes collection")
        backup_name=c["arxiv_id"]+"__"+f["label"].replace(" ","_")+".png"
        shutil.copy2(original,backups/backup_name)
        replacement=backups/("replacement_"+str(n)+".png")
        props=m.save_image(replacement,image,240)
        old_hash=f["sha256"];old_crop=f["crop"]
        replacement.replace(original)
        thumb=image.copy();thumb.thumbnail((560,420))
        replacement_thumb=backups/("replacement_thumb_"+str(n)+".png")
        m.save_image(replacement_thumb,thumb);replacement_thumb.replace(thumbnail);thumb.close();image.close()
        f.update(props,crop=c["crop"],method="reviewed crop override",review_status="source_page_visually_reviewed",override_reason=c["reason"])
        override_data["items"]=[o for o in override_data["items"] if not(o["arxiv_id"]==c["arxiv_id"] and o["number"]==c["number"])]
        override_data["items"].append(c)
        history.append({**c,"old_crop":old_crop,"old_sha256":old_hash,"new_sha256":props["sha256"],"backup":(backups/backup_name).relative_to(root).as_posix(),"output":f["file"]})
        m.contact_sheet(root,result)
    m.save_json(override_path,override_data)
    recipe=m.sha(Path(__file__).with_name("extract_figures.py"))+m.sha(override_path)
    for result in results:
        result["recipe_hash"]=recipe
        m.save_json(root/"paper_results"/(result["arxiv_id"]+".json"),result)
    spec=json.loads((root/"spec.snapshot.json").read_text(encoding="utf8"))
    m.save_json(history_file,history)
    print(json.dumps(m.finalize(root,results,spec,override_data["expected_labels"]),ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()

