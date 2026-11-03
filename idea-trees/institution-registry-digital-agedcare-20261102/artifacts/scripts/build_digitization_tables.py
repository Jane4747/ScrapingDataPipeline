# -*- coding: utf-8 -*-
"""合并 digit_reports_batch*.json -> 医卫数字化公众号报道_分析表.xlsx
表A 报道分析表（按用户指定的6分析维度+关联字段）
表B 采购项目明细表（用户给定的40列字段）
全量版：支持 batch1..batchN 任意数量，动态统计 + 报道去重。
"""
import json, glob, os, collections
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

BASE = "configs"
OUT = "outputs/institution-registry-20261030/医卫数字化公众号报道_分析表_全量_20261101.xlsx"
files = sorted(glob.glob(os.path.join(BASE, "digit_reports_batch*.json")))
reports, projects = [], []
file_stats = []
for f in files:
    d = json.load(open(f, encoding="utf-8"))
    rs = d.get("reports", [])
    ps = d.get("projects", [])
    reports.extend(rs)
    projects.extend(ps)
    file_stats.append((os.path.basename(f), len(rs), len(ps), d.get("failed", [])))

# 报道去重：同一机构+同标题+同链接 视为重复
seen = set(); deduped = []
for r in reports:
    key = (r.get("机构ID", ""), r.get("报道标题", ""), r.get("来源链接", ""))
    if key in seen:
        continue
    seen.add(key); deduped.append(r)
reports = deduped

# ---------- 表A 报道分析表 ----------
A_COLS = ["合并序号", "机构名称", "机构ID", "省份", "公众号", "报道标题", "来源类型",
          "来源链接", "发布时间", "响应的政策", "具体内容总结", "提供技术支持的机构",
          "提供资金支持的机构", "目的与结果", "是否明确项目", "备注"]
A_MAP = {"具体内容总结": "内容总结", "提供技术支持的机构": "技术支持机构",
         "提供资金支持的机构": "资金支持机构", "响应的政策": "响应政策"}

# ---------- 表B 采购项目明细表（用户给定字段） ----------
B_COLS = ["合并序号", "时间", "项目名称", "产品", "招标单位", "客户标签", "中标单位",
          "运营商类型", "中标金额（万元）", "场景", "评审专家", "网址", "公告类型",
          "省份", "项目编号", "中标金额原文", "信息缺口", "标签依据",
          "响应人资格要求（对供应商基本要求）", "资格预审资质要求", "来源平台",
          "资格要求出处", "原文文件", "医院名称", "医院ID", "日期依据", "采购人依据",
          "采集来源", "抓取时间", "公告ID", "原文SHA256", "数字化标签", "入口任务ID",
          "金额口径备注", "批次", "来源记录数", "字段差异数", "来源文件",
          "来源工作表", "原始行号"]

wb = openpyxl.Workbook()
HEAD_FILL = PatternFill("solid", fgColor="1F4E78")
HEAD_FONT = Font(bold=True, color="FFFFFF", size=10)
WRAP = Alignment(wrap_text=True, vertical="top")
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

def style_header(ws, ncols):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HEAD_FILL; cell.font = HEAD_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
    ws.freeze_panes = "A2"

# 00 说明
ws0 = wb.active; ws0.title = "00_说明"
_covered = set(r.get("机构ID") for r in reports) | set(p.get("医院ID") for p in projects)
_covered.discard(""); _covered.discard(None)
inst = [
    ("医卫数字化公众号报道分析表（全量爬取）", True),
    ("", False),
    ("构建时间：2026-11-01  采集方式：WebSearch 实时检索（近3年 2023-2026）", False),
    ("覆盖范围：机构台账中已录官方公众号的机构（主表按机构全称去重后共 193 家）", False),
    ("   · 试点 20 家（batch1-5，前序已完成）", False),
    ("   · 全量爬取 173 家（batch6-15，本批分批并发完成）", False),
    ("   · 省份空白的'区域中心输出'重复行已按机构名称确定性映射补全省份，避免重复检索", False),
    ("", False),
    ("【表A 报道分析表】字段说明", True),
    ("发布时间/响应的政策/具体内容总结/提供技术支持的机构/提供资金支持的机构/目的与结果 = 用户指定的6个分析维度", False),
    ("另含机构名称、机构ID、省份、公众号、报道标题、来源类型、来源链接、是否明确项目、备注，便于溯源与衔接表B", False),
    ("", False),
    ("【表B 采购项目明细表】字段说明", True),
    ("采用用户给定的采购/中标项目字段（共40列；用户原文称'45列'，实际列出40个，按列出字段实现）", False),
    ("仅收录'明确写明了具体项目'的报道：采购公告/中标公告/战略合作框架协议/科研专项课题/财政信息化预算类", False),
    ("缺口留空：未披露的中标单位、金额、专家、资格要求等一律留空，不推断、不编造", False),
    ("", False),
    ("【证据纪律（沿用机构台账口径）】", True),
    ("1. 公众号仅认台账已录的官方公众号；检索不到即标'未检索到'，不按机构全称推断公众号名", False),
    ("2. 来源类型区分：公众号原文(mp.weixin.qq.com)/官网新闻/媒体转载/采购公告/中标公告/学术/财政", False),
    ("3. 报道若非单一采购项目（如服务型举措、自研产品、厂商案例），'是否明确项目'填'否'，不进表B", False),
    ("4. 医院ID 关联：projects 的医院ID/医院名称按台账机构归并；招标单位为挂牌/区域中心输出分院时保留原文并在信息缺口标注主体差异", False),
    ("", False),
    ("【表A / 表B 计数口径（重要）】", True),
    ("· 表A 按'报道/文章'计数，表B 按'项目/标包'计数，二者非一一对应", False),
    ("· 一份中标/采购公告常含多个标包（不同中标单位/金额），拆为多条项目，形成 1:N", False),
    ("· 表B 另含直接检索到的政府采购网/公共资源交易中心中标公告（ccgp.gov.cn、ggzy.* 等），无对应服务型报道", False),
    ("· 因此 表B项目数 通常大于 表A'是'报道数，此为口径差异，非重复或错误", False),
    ("· 规范化脚本 scripts/fix_digit_reports.py 已回填空医院ID与缺键（幂等，可重跑）", False),
    ("", False),
    ("【统计速览】", True),
    (f"合并批次文件：{len(files)} 个（含 batch1-5 试点、batch10_retry 补爬）", False),
    (f"表A 报道记录：{len(reports)} 条（去重后）", False),
    (f"表B 明确项目：{len(projects)} 条", False),
    (f"覆盖唯一机构：{len(_covered)} 家", False),
    ("注：batch10 首轮失败的『济南市中医医院』已由 batch10_retry 补爬成功入库", False),
    ("注：『广州医学院第一附属医院』(ORG-0345) 为『广州医科大学附属第一医院』(ORG-0012) 旧称，同一主体，数据已归并至后者、未丢失；193 编号实为 192 个唯一主体，全覆盖", False),
]
for i, (txt, bold) in enumerate(inst, start=1):
    c = ws0.cell(row=i, column=1, value=txt)
    if bold:
        c.font = Font(bold=True, size=11, color="1F4E78")
ws0.column_dimensions["A"].width = 120

# 表A
wsA = wb.create_sheet("01_报道分析表")
wsA.append(A_COLS)
for i, r in enumerate(reports, start=1):
    row = [i]
    for col in A_COLS[1:]:
        key = A_MAP.get(col, col)
        row.append(r.get(key, ""))
    wsA.append(row)
style_header(wsA, len(A_COLS))
widthsA = [8, 22, 10, 8, 18, 34, 12, 40, 14, 26, 50, 24, 20, 30, 12, 14]
for i, w in enumerate(widthsA, start=1):
    wsA.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
for row in wsA.iter_rows(min_row=2):
    for cell in row:
        cell.alignment = WRAP; cell.border = BORDER
        cell.font = Font(size=9)

# 表B
wsB = wb.create_sheet("02_采购项目明细表")
wsB.append(B_COLS)
for i, p in enumerate(projects, start=1):
    row = [i]
    for col in B_COLS[1:]:
        key = "中标金额万元" if col == "中标金额（万元）" else col
        row.append(p.get(key, ""))
    wsB.append(row)
style_header(wsB, len(B_COLS))
for i in range(1, len(B_COLS) + 1):
    wsB.column_dimensions[openpyxl.utils.get_column_letter(i)].width = 16
wsB.column_dimensions["C"].width = 34   # 项目名称
wsB.column_dimensions["D"].width = 32   # 产品
wsB.column_dimensions["L"].width = 42   # 网址
wsB.column_dimensions["P"].width = 30   # 中标金额原文
wsB.column_dimensions["Q"].width = 24   # 信息缺口
wsB.column_dimensions["R"].width = 28   # 标签依据
wsB.column_dimensions["S"].width = 30   # 响应人资格要求
wsB.column_dimensions["AJ"].width = 24   # 金额口径备注
for row in wsB.iter_rows(min_row=2):
    for cell in row:
        cell.alignment = WRAP; cell.border = BORDER
        cell.font = Font(size=9)

# 03 统计
wsS = wb.create_sheet("03_统计")
wsS.append(["维度", "分类", "数量"])
def addstat(dim, counter):
    for k, v in counter.items():
        wsS.append([dim, k, v])
addstat("省份", collections.Counter(r.get("省份", "") for r in reports))
addstat("是否明确项目", collections.Counter(r.get("是否明确项目", "") for r in reports))
addstat("来源类型", collections.Counter(r.get("来源类型", "") for r in reports))
addstat("表B-公告类型", collections.Counter(p.get("公告类型", "") for p in projects))
addstat("表B-省份", collections.Counter(p.get("省份", "") for p in projects))
wsS.append(["合计", "批次文件", len(files)])
wsS.append(["合计", "表A报道(去重)", len(reports)])
wsS.append(["合计", "表B项目", len(projects)])
style_header(wsS, 3)
for i, w in enumerate([18, 40, 10], start=1):
    wsS.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
for row in wsS.iter_rows(min_row=2):
    for cell in row:
        cell.border = BORDER; cell.font = Font(size=9)

# 04 分批次来源
wsF = wb.create_sheet("04_分批次")
wsF.append(["批次文件", "报道数", "项目数", "检索失败机构数", "失败机构"])
for fn, nr, np, failed in file_stats:
    wsF.append([fn, nr, np, len(failed), "；".join(failed) if failed else ""])
style_header(wsF, 5)
for i, w in enumerate([26, 10, 10, 16, 60], start=1):
    wsF.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
for row in wsF.iter_rows(min_row=2):
    for cell in row:
        cell.alignment = WRAP; cell.border = BORDER; cell.font = Font(size=9)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
import time
try:
    wb.save(OUT)
except PermissionError:
    alt = OUT.replace(".xlsx", f"_{int(time.time())}.xlsx")
    wb.save(alt); OUT = alt
    print("目标文件被占用，已另存为:", alt)
print("已生成:", OUT)
print("批次文件:", len(files), " 表A(去重):", len(reports), " 表B:", len(projects))
print("省份分布:", dict(collections.Counter(r.get('省份','') for r in reports)))
print("表B公告类型:", dict(collections.Counter(p.get('公告类型','') for p in projects)))
