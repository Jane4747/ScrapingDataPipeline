"""Add native OOXML hyperlinks missing from the spreadsheet author's public API.

No cell values, formulas, styles or tables are authored here. Uses bundled Python
stdlib only; all spreadsheet content/layout is authored by artifact-tool.
"""
import json
import os
import posixpath
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

source, target, mapping_file = map(Path, sys.argv[1:4])
mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("", MAIN)
ET.register_namespace("r", REL)
updates = {}
counts = {}
with zipfile.ZipFile(source) as zin:
    wb = ET.fromstring(zin.read("xl/workbook.xml"))
    rels = ET.fromstring(zin.read("xl/_rels/workbook.xml.rels"))
    lookup = {r.attrib["Id"]:r.attrib["Target"] for r in rels}
    for sheet in wb.find(f"{{{MAIN}}}sheets"):
        name = sheet.attrib["name"]
        if name not in mapping:continue
        sheet_target = lookup[sheet.attrib[f"{{{REL}}}id"]]
        sheet_path = sheet_target.lstrip("/") if sheet_target.startswith("/") else posixpath.normpath("xl/"+sheet_target)
        rel_path = posixpath.join(posixpath.dirname(sheet_path),"_rels",posixpath.basename(sheet_path)+".rels")
        root = ET.fromstring(zin.read(sheet_path))
        sheet_rels = ET.fromstring(zin.read(rel_path)) if rel_path in zin.namelist() else ET.Element(f"{{{PKG}}}Relationships")
        ids = {r.attrib["Id"] for r in sheet_rels}
        hyperlinks = root.find(f"{{{MAIN}}}hyperlinks")
        if hyperlinks is None:
            hyperlinks = ET.Element(f"{{{MAIN}}}hyperlinks")
            later = {"printOptions","pageMargins","pageSetup","headerFooter","rowBreaks","colBreaks","customProperties","cellWatches","ignoredErrors","smartTags","drawing","legacyDrawing","legacyDrawingHF","picture","oleObjects","controls","webPublishItems","tableParts","extLst"}
            index = next((i for i,c in enumerate(root) if c.tag.rsplit("}",1)[-1] in later),len(root))
            root.insert(index,hyperlinks)
        for i,item in enumerate(mapping[name],1):
            rid = f"nativeHyperlink{i}"
            while rid in ids:rid += "x"
            ids.add(rid)
            assert item["url"].startswith(("https://www.ggzy.gov.cn/","http://www.ggzy.gov.cn/"))
            ET.SubElement(hyperlinks,f"{{{MAIN}}}hyperlink",{"ref":item["cell"],f"{{{REL}}}id":rid})
            ET.SubElement(sheet_rels,f"{{{PKG}}}Relationship",{"Id":rid,"Type":REL+"/hyperlink","Target":item["url"],"TargetMode":"External"})
        updates[sheet_path] = ET.tostring(root,encoding="utf-8",xml_declaration=True)
        updates[rel_path] = ET.tostring(sheet_rels,encoding="utf-8",xml_declaration=True)
        counts[name] = len(mapping[name])
    temporary = target.with_suffix(".links.tmp")
    with zipfile.ZipFile(temporary,"w",zipfile.ZIP_DEFLATED) as zout:
        seen = set()
        for info in zin.infolist():
            zout.writestr(info,updates.get(info.filename,zin.read(info.filename)))
            seen.add(info.filename)
        for name,data in updates.items():
            if name not in seen:zout.writestr(name,data)
with zipfile.ZipFile(temporary) as check:
    assert check.testzip() is None
os.replace(temporary,target)
print(json.dumps({"native_hyperlinks":counts,"file":str(target)}))
