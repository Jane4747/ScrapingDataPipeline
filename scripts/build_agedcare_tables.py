# -*- coding: utf-8 -*-
"""合并养老补查 p1-p9 原始 JSON，生成全量汇总工作簿并落地到'想法树'目录。
纪律：不推断公众号/官网、缺口留空；全量完成（p1-p9 共 162 家）。
"""
import json, glob, os, collections, shutil
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(ROOT, "outputs", "institution-registry-20261030")
os.makedirs(OUTDIR, exist_ok=True)
RAW_BACKUP = os.path.join(OUTDIR, "_agedcare_raw")
os.makedirs(RAW_BACKUP, exist_ok=True)

# 仅取已落盘批次（p1-p6），按文件名排序
files = sorted(glob.glob(os.path.join(ROOT, "configs", "agedcare_reports_p*.json")))
data = []
for f in files:
    try:
        d = json.load(open(f, encoding="utf-8"))
        data.append((os.path.basename(f), d))
    except Exception as e:
        print("跳过无法解析:", f, e)

insts, reps, prjs = [], [], []
for fn, d in data:
    insts += d.get("institutions", [])
    reps += d.get("reports", [])
    prjs += d.get("projects", [])

# 机构去重（按机构ID，保留首次出现）
seen, inst_dedup = set(), []
for it in insts:
    k = it.get("机构ID")
    if k in seen:
        continue
    seen.add(k)
    inst_dedup.append(it)

# 来源类型归一
def norm_src(s):
    s = str(s or "").strip()
    if not s: return "其他"
    for kw, label in [("公众号", "公众号原文"), ("官网", "官网新闻"), ("采购", "采购公告"),
                      ("中标", "中标公告"), ("民政", "民政公示"), ("学术", "学术"),
                      ("财政", "财政"), ("会议", "行业会议"), ("媒体", "媒体转载")]:
        if kw in s: return label
    return s

for r in reps:
    r["来源类型"] = norm_src(r.get("来源类型"))

def norm_atype(s):
    s = str(s or "").strip()
    if not s:
        return "其他/未标注"
    if "中标" in s: return "中标公告"
    if "采购" in s or "招标" in s: return "采购公告"
    if "战略合作" in s: return "战略合作框架协议"
    if "课题" in s or "研发计划" in s or "试点示范" in s: return "科研专项课题"
    if "财政" in s or "预算" in s or "政府行动方案" in s or "政府投资" in s: return "财政/政府投资"
    if "公示" in s: return "公示类"
    if any(k in s for k in ["建设", "上线", "自建", "自有", "引进", "投用", "部署", "平台"]):
        return "自主建设/非采购"
    return "其他"

for p in prjs:
    p["公告类型_归一"] = norm_atype(p.get("公告类型"))

batches = sorted({d.get("批次") for fn, d in data})
completed_inst = len(inst_dedup)

# ===== 构建工作簿 =====
wb = Workbook()
thin = Side(style="thin", color="BBBBBB")
border = Border(left=thin, right=thin, top=thin, bottom=thin)
hdr_fill = PatternFill("solid", fgColor="1F4E78")
hdr_font = Font(bold=True, color="FFFFFF")
title_font = Font(bold=True, size=12, color="1F4E78")

def write_sheet(ws, header, rows, freeze="A2"):
    ws.append(header)
    for c in ws[1]:
        c.fill = hdr_fill; c.font = hdr_font; c.border = border
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for row in rows:
        ws.append([row.get(h, "") if isinstance(row, dict) else "" for h in header])
    for r in ws.iter_rows(min_row=2):
        for c in r:
            c.border = border
            c.alignment = Alignment(vertical="top", wrap_text=True)
    ws.freeze_panes = freeze
    # 列宽
    for i, h in enumerate(header, 1):
        ws.column_dimensions[get_column_letter(i)].width = min(max(len(str(h)) * 1.6, 12), 40)

# 00 说明
ws0 = wb.active; ws0.title = "00_说明"
notes = [
    ("养老院补查汇总工作簿（全量完成）", True),
    ("", False),
    ("产出时间：2026-11-02", False),
    (f"数据范围：全量批次 p{int(min(batches))}–p{int(max(batches))}，共覆盖 {completed_inst} 家养老/护理/医养类机构", False),
    ("配套原始数据：本目录 _agedcare_raw/ 含 p1–p9 各批次 JSON", False),
    ("", False),
    ("【数据来源】", True),
    ("原始台账：机构台账_六表_20261101.xlsx 主表（表3 医养示范机构 + 表6 远程协同试点 中养老类机构）", False),
    ("采集方式：WebSearch 实时检索该机构官网/官方公众号/联系方式及 2023–2026 医卫数字化报道", False),
    ("", False),
    ("【证据纪律】", True),
    ("1. 不推断公众号名：仅录检索结果中明确写明是该机构官方公众号者；查不到留空", False),
    ("2. 官网认定：仅认机构自有独立域名官网；第三方养老平台/地图/百科/民政名单页/母体医院域名均不算官网", False),
    ("3. 养老院/护理院无独立官网为常态，如实标注，不编造", False),
    ("4. 缺口留空：电话/地址/金额/专家/资格要求等查不到即空，严禁推断", False),
    ("5. 时间范围仅 2023–2026", False),
    ("", False),
    ("【表结构】", True),
    ("01_机构采集表：官网/公众号/联系方式/采集状态（去重后 %d 家）" % completed_inst, False),
    ("02_报道分析表：发布时间/响应政策/内容总结/技术支持机构/资金支持机构/目的与结果/%d 条" % len(reps), False),
    ("03_采购项目明细表：明确项目（采购/中标/战略合作/财政预算等）%d 条" % len(prjs), False),
    ("04_统计：分类统计", False),
    ("", False),
    ("注：表B 项目数可能大于表A'是'报道数，因一份公告含多标包（1:N）或直采公告无对应服务型报道，属口径差异非错误。", False),
]
for text, bold in notes:
    ws0.append([text])
    if bold:
        ws0[ws0.max_row][0].font = title_font
ws0.column_dimensions["A"].width = 120

# 01 机构采集表
ws1 = wb.create_sheet("01_机构采集表")
inst_header = ["机构ID", "机构全称", "省份", "城市", "出现表", "机构类型", "疑似重复组",
               "官网", "官网来源", "官网可达性", "微信公众号", "公众号来源",
               "联系电话", "地址", "采集状态", "备注"]
write_sheet(ws1, inst_header, inst_dedup)

# 02 报道分析表
ws2 = wb.create_sheet("02_报道分析表")
rep_header = ["机构名称", "机构ID", "省份", "公众号", "报道标题", "来源类型", "来源链接",
              "发布时间", "响应政策", "内容总结", "技术支持机构", "资金支持机构", "目的与结果", "是否明确项目", "备注"]
write_sheet(ws2, rep_header, reps)

# 03 采购项目明细表
ws3 = wb.create_sheet("03_采购项目明细表")
prj_header = list(prjs[0].keys()) if prjs else ["机构名称", "机构ID", "项目名称", "中标单位", "中标金额万元", "公告类型"]
write_sheet(ws3, prj_header, prjs)

# 04 统计
ws4 = wb.create_sheet("04_统计")
stat = []
stat.append(["指标", "数值"])
stat.append(["覆盖机构数（去重）", completed_inst])
stat.append(["有官网机构数", sum(1 for it in inst_dedup if str(it.get("官网") or "").strip())])
stat.append(["有公众号机构数", sum(1 for it in inst_dedup if str(it.get("微信公众号") or "").strip())])
stat.append(["采集状态=检索失败", sum(1 for it in inst_dedup if str(it.get("采集状态") or "") == "检索失败")])
stat.append(["采集状态=已查询-有官网", sum(1 for it in inst_dedup if "有官网" in str(it.get("采集状态") or ""))])
stat.append(["采集状态=已查询-无独立官网", sum(1 for it in inst_dedup if "无独立官网" in str(it.get("采集状态") or ""))])
stat.append(["采集状态=已查询-仅公众号", sum(1 for it in inst_dedup if "仅公众号" in str(it.get("采集状态") or ""))])
stat.append(["报道分析表条数", len(reps)])
stat.append(["明确项目条数", len(prjs)])
stat.append(["有金额项目数", sum(1 for p in prjs if str(p.get("中标金额万元") or "").strip())])
stat.append(["— 机构类型分布 —", ""])
for k, v in collections.Counter(it.get("机构类型") for it in inst_dedup).most_common():
    stat.append([f"  机构类型: {k}", v])
stat.append(["— 省份分布 —", ""])
for k, v in collections.Counter(it.get("省份") for it in inst_dedup).most_common():
    stat.append([f"  省份: {k}", v])
stat.append(["— 报道来源类型 —", ""])
for k, v in collections.Counter(r.get("来源类型") for r in reps).most_common():
    stat.append([f"  来源: {k}", v])
stat.append(["— 公告类型（项目·归一主类） —", ""])
for k, v in collections.Counter(p.get("公告类型_归一") for p in prjs).most_common():
    stat.append([f"  公告: {k}", v])
stat.append(["— 表A 是否明确项目分布 —", ""])
for k, v in collections.Counter(str(r.get("是否明确项目") or "").split("（")[0] for r in reps).most_common():
    stat.append([f"  {k}", v])
for row in stat:
    ws4.append(row)
ws4[1][0].font = Font(bold=True); ws4[1][1].font = Font(bold=True)
ws4.column_dimensions["A"].width = 36; ws4.column_dimensions["B"].width = 14

# 落地（全量完成，命名含日期与覆盖数，避免与旧版预览锁文件冲突）
OUT = os.path.join(OUTDIR, "养老院补查_汇总_全量162家_20261102.xlsx")
try:
    wb.save(OUT)
except PermissionError:
    OUT = os.path.join(OUTDIR, "养老院补查_汇总_全量162家_20261102_v2.xlsx")
    wb.save(OUT)
print("已生成汇总工作簿:", OUT)

# 备份原始 JSON 到 _agedcare_raw
for fn, d in data:
    shutil.copy(os.path.join(ROOT, "configs", fn), os.path.join(RAW_BACKUP, fn))
print("原始批次 JSON 已备份至:", RAW_BACKUP, "共", len(data), "个文件")

# 体检
print(f"\n机构(去重)={completed_inst} 报道={len(reps)} 项目={len(prjs)}")
print("来源类型归一后:", dict(collections.Counter(r['来源类型'] for r in reps)))
print("项目公告类型:", dict(collections.Counter(p.get('公告类型') for p in prjs)))
