# -*- coding: utf-8 -*-
import json, glob, openpyxl
from openpyxl.styles import Font, Alignment, PatternFill

REST_DIR = "rest_hospitals"
PREV_FILE = "医院名单_沪粤苏浙鲁闽.xlsx"

# ---- 1. 读取此前已采集的 6 省数据 ----
prev_hospitals = []
prev_sources = []
wb = openpyxl.load_workbook(PREV_FILE)
ws = wb["医院名单"]
hdr = [c.value for c in ws[1]]
# 列索引（1-based）
idx = {h: i+1 for i, h in enumerate(hdr)}
for r in range(2, ws.max_row+1):
    row = [ws.cell(r, c).value for c in range(1, len(hdr)+1)]
    prev_hospitals.append({
        "省份": row[idx["省份"]-1],
        "医院名称": row[idx["医院名称"]-1],
        "医院等级": row[idx["医院等级"]-1],
        "医院类别": row[idx["医院类别"]-1] or "",
        "名单性质": row[idx["名单性质"]-1] or "",
        "来源机构": row[idx["来源机构"]-1] or "",
        "来源URL": row[idx["来源URL"]-1] or "",
        "备注": row[idx["备注"]-1] or "",
    })
ws1 = wb["来源清单"]
h1 = [c.value for c in ws1[1]]
i1 = {h: i+1 for i, h in enumerate(h1)}
for r in range(2, ws1.max_row+1):
    row = [ws1.cell(r, c).value for c in range(1, len(h1)+1)]
    prev_sources.append({
        "省份": row[i1.get("省份",1)-1],
        "权威机构": row[i1.get("权威机构",2)-1],
        "名单名称": row[i1.get("名单名称",3)-1],
        "来源URL": row[i1.get("来源URL",4)-1],
        "覆盖说明": row[i1.get("名单性质/覆盖说明",5)-1],
        "发布时间": row[i1.get("发布时间",6)-1] if "发布时间" in i1 else "",
    })
print(f"已读取此前 6 省数据：医院 {len(prev_hospitals)} 条，来源 {len(prev_sources)} 条")

# ---- 2. 读取其余省份分组 JSON ----
rest_hospitals = []
rest_sources = []
for f in sorted(glob.glob(f"{REST_DIR}/group*.json")):
    d = json.load(open(f, encoding="utf-8"))
    rest_hospitals.extend(d.get("hospitals", []))
    rest_sources.extend(d.get("sources", []))
print(f"其余省份：医院 {len(rest_hospitals)} 条，来源 {len(rest_sources)} 条")

# ---- 3. 去重（省份+医院名称）----
def dedupe(lst):
    seen = set(); out = []
    for x in lst:
        k = (x.get("省份",""), x.get("医院名称",""))
        if k in seen: 
            continue
        seen.add(k); out.append(x)
    return out

rest_hospitals = dedupe(rest_hospitals)
prev_hospitals = dedupe(prev_hospitals)
print(f"去重后：其余 {len(rest_hospitals)}，此前 {len(prev_hospitals)}")

# ---- 4. 写 Excel ----
HDR = ["序号","省份","医院名称","医院等级","医院类别","名单性质","来源机构","来源URL","备注"]
SRC_HDR = ["省份","权威机构","名单名称","来源URL","名单性质/覆盖说明","发布时间"]

def build_workbook(hospitals, sources, title):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "医院名单"
    ws.append(HDR)
    for i, h in enumerate(hospitals, 1):
        ws.append([i, h.get("省份",""), h.get("医院名称",""), h.get("医院等级","") or "未知",
                   h.get("医院类别","") or "", h.get("名单性质","") or "",
                   h.get("来源机构","") or "", h.get("来源URL","") or "", h.get("备注","") or ""])
    ws2 = wb.create_sheet("来源清单")
    ws2.append(SRC_HDR)
    for s in sources:
        ws2.append([s.get("省份",""), s.get("权威机构", s.get("来源机构","")),
                    s.get("名单名称",""), s.get("来源URL",""),
                    s.get("覆盖说明",""), s.get("发布时间","")])
    # 样式
    head_fill = PatternFill("solid", fgColor="4472C4")
    head_font = Font(color="FFFFFF", bold=True)
    for sheet in (ws, ws2):
        for c in sheet[1]:
            c.fill = head_fill; c.font = head_font
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.freeze_panes = "A2"
    # 列宽
    widths = [6, 10, 34, 12, 14, 22, 28, 46, 26]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    for i, w in enumerate([10, 28, 34, 46, 40, 14], 1):
        ws2.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    wb.save(title)
    print(f"已生成：{title}（医院 {len(hospitals)}，来源 {len(sources)}）")

# 4a. 其余省份文件
build_workbook(rest_hospitals, rest_sources, "医院名单_其余省份.xlsx")

# 4b. 全国汇总（此前6省 + 其余）
all_h = prev_hospitals + rest_hospitals
all_s = prev_sources + rest_sources
build_workbook(all_h, all_s, "全国医院名单_汇总.xlsx")

# ---- 5. 各省数量统计 ----
from collections import Counter
c = Counter(h["省份"] for h in rest_hospitals)
print("\n【其余省份各省市医院数量】")
for k, v in sorted(c.items(), key=lambda x: -x[1]):
    print(f"  {k}: {v}")
c2 = Counter(h["省份"] for h in all_h)
print("\n【全国汇总各省市医院数量（含此前6省）】")
for k, v in sorted(c2.items(), key=lambda x: -x[1]):
    print(f"  {k}: {v}")
print(f"\n总计：其余省份 {len(rest_hospitals)} 家；全国汇总 {len(all_h)} 家")
