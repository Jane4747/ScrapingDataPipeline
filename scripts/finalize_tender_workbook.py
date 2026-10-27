"""Add native URL links to an existing workbook, writing a new file.

Usage: python -B scripts/finalize_tender_workbook.py --book input.xlsx
       --links-file previews/hyperlinks.json --output linked.xlsx
Only standard-library OOXML handling is needed; this does not render workbooks.
"""
from __future__ import annotations
import argparse
from io import BytesIO
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

S = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P = 'http://schemas.openxmlformats.org/package/2006/relationships'
AFTER = set('printOptions pageMargins pageSetup headerFooter rowBreaks colBreaks customProperties cellWatches ignoredErrors smartTags drawing legacyDrawing legacyDrawingHF picture oleObjects controls webPublishItems tableParts extLst'.split())


def finalize(book, links_file, output):
    book, output = Path(book).resolve(), Path(output).resolve()
    if book == output or output.exists():
        raise ValueError('输出必须是尚不存在的新文件，保留原工作簿')
    links = json.loads(Path(links_file).read_text(encoding='utf-8-sig'))
    if not isinstance(links, list):
        raise ValueError('hyperlinks.json必须是列表')
    with ZipFile(book) as z:
        payload = {name:z.read(name) for name in z.namelist()}
    groups = {}
    for row in links:
        sid, cell, url = row['sheet'], row['cell'], row['url']
        if isinstance(sid, bool) or not isinstance(sid, int) or sid < 1:
            raise ValueError('sheet必须是正整数')
        if not re.fullmatch(r'[A-Z]{1,3}[1-9][0-9]*', cell):
            raise ValueError('无效单元格地址')
        if urlsplit(url).scheme not in ('http', 'https') or not urlsplit(url).hostname:
            raise ValueError('仅接受HTTP/HTTPS网址')
        group = groups.setdefault(sid, {})
        if cell in group and group[cell] != url:
            raise ValueError('同一单元格出现冲突网址')
        group[cell] = url
    for sid, group in groups.items():
        name = f'xl/worksheets/sheet{sid}.xml'
        if name not in payload:
            raise ValueError(f'工作表不存在：{sid}')
        tree = ET.fromstring(payload[name])
        if tree.findall(f'.//{{{S}}}c[@t="e"]'):
            raise ValueError('工作表含Excel错误单元格')
        relname = f'xl/worksheets/_rels/sheet{sid}.xml.rels'
        rel = ET.fromstring(payload[relname]) if relname in payload else ET.Element(f'{{{P}}}Relationships')
        # Replace links at the requested cells; keep every unrelated link and relationship.
        hyper = tree.find(f'{{{S}}}hyperlinks')
        if hyper is None:
            hyper = ET.Element(f'{{{S}}}hyperlinks')
            index = next((i for i, item in enumerate(tree) if item.tag.split('}')[-1] in AFTER), len(tree))
            tree.insert(index, hyper)
        removed = set()
        for entry in list(hyper):
            if entry.get('ref') in group:
                removed.add(entry.get(f'{{{R}}}id'))
                hyper.remove(entry)
        remaining = {entry.get(f'{{{R}}}id') for entry in hyper}
        for entry in list(rel):
            if entry.get('Id') in removed - remaining and entry.get('Type') == R + '/hyperlink':
                rel.remove(entry)
        ids = {entry.get('Id') for entry in rel}
        for cell, url in group.items():
            suffix = 1
            while f'rIdTender{sid}_{suffix}' in ids:
                suffix += 1
            rid = f'rIdTender{sid}_{suffix}'
            ids.add(rid)
            ET.SubElement(rel, f'{{{P}}}Relationship', Id=rid, Type=R+'/hyperlink', Target=url, TargetMode='External')
            ET.SubElement(hyper, f'{{{S}}}hyperlink', {'ref':cell, f'{{{R}}}id':rid})
        payload[name] = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
        payload[relname] = ET.tostring(rel, encoding='utf-8', xml_declaration=True)
    buffer = BytesIO()
    with ZipFile(buffer, 'w', ZIP_DEFLATED) as z:
        for name, data in payload.items():
            z.writestr(name, data)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as f:
        f.write(buffer.getvalue())
    return {'output':str(output), 'updated_hyperlinks':sum(map(len, groups.values())), 'updated_sheets':len(groups)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--book', required=True)
    parser.add_argument('--links-file', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        result = finalize(args.book, args.links_file, args.output)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status':'failed', 'error':str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({'status':'completed', **result}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
