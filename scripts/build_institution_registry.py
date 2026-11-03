"""Build the six-sheet institution registry workbook from the seed tables.

The seed (`configs/institution_tables_seed_20261030.json`) holds the rows the
user supplied in six ready-made tables. Those rows are a *transcription*, not
verified evidence: every row enters the workbook with 核验状态=待核 and a
拟评等级 that reflects only the completeness of the document number.

This script does three things and nothing else:
  1. lays the six tables out with the shared 15-column contract plus the
     table-specific columns;
  2. derives an institution master list (机构主表) so the same hospital is not
     counted twice across tables;
  3. writes a statistics sheet with row counts, grade mix and duplicate hits.

It never fetches anything and never fills an operational field (床位, 入住率,
资金来源, 难处). Those stay empty until a source is attached.

Usage (repository runtime):
  "D:/Anaconda3/envs/BigData/python.exe" -B scripts/build_institution_registry.py \
      --seed configs/institution_tables_seed_20261030.json \
      --output outputs/institution-registry-20261030/机构台账_六表_20261030.xlsx
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEAD_FILL = PatternFill("solid", fgColor="DCE6F1")
HEAD_FONT = Font(name="微软雅黑", size=10, bold=True, color="1F3864")
BODY_FONT = Font(name="微软雅黑", size=9, color="1A1A1A")
NOTE_FONT = Font(name="微软雅黑", size=9, color="7F7F7F")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
TOP_WRAP = Alignment(vertical="top", wrap_text=True)

PENDING = "待核（用户整理稿）"
VERIFIED = "已核（官方附件原文）"
SEED_SOURCE = "用户整理稿"
OFFICIAL_SOURCE = "官方附件/官网原文"

CITY_PROVINCE = {
    "北京": "北京", "天津": "天津", "上海": "上海", "重庆": "重庆",
    "成都": "四川", "长沙": "湖南", "武汉": "湖北", "广州": "广东",
    "杭州": "浙江", "沈阳": "辽宁", "西安": "陕西", "深圳": "广东",
    "温州": "浙江", "苏州": "江苏", "南京": "江苏", "济南": "山东",
}

GRADE_A = {"A216", "A217", "A218", "A219", "A220", "A26", "A1670", "A483",
           "A18", "A721", "A214", "A177"}
GRADE_A_MINUS = {"A2020", "A2022"}
GRADE_B = {"A357", "A21", "A22", "A23", "A25", "A2017", "A2023", "A2013", "A2014"}

DEFAULT_DOMICILE = "configs/institution_hospital_domicile_20261030.json"
DEFAULT_ALIASES = "configs/institution_aliases_20261030.json"


def load_reference(path_text, key, kind):
    """Load a hand-maintained reference config. Missing file = empty reference."""
    if not path_text:
        return {}, {}
    path = Path(path_text)
    if not path.exists():
        return {}, {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if kind == "domicile":
        return {e["name"]: (e.get("province", ""), e.get("city", "")) for e in data.get(key, [])}, {}
    canon_of = {}
    related = {}
    for grp in data.get(key, []):
        for alias in [grp["canonical"]] + list(grp.get("aliases", [])):
            if grp.get("merge", True):
                canon_of[alias] = grp["canonical"]
            else:
                canon_of[alias] = alias
                related[alias] = grp.get("related_to", "")
    return canon_of, related


def canonical_name(name, canon_of):
    if not name:
        return ""
    key = re.sub(r"[（(].*?[)）]", "", name).strip()
    return canon_of.get(key, canon_of.get(name.strip(), key))


def domicile_of(name, domicile, canon_of):
    """Province/city for a hospital when the own table does not carry one."""
    for probe in (name, canonical_name(name, canon_of)):
        if probe in domicile:
            return domicile[probe]
    return ("", "")


def grade(art: str) -> str:
    if art in GRADE_A:
        return "A"
    if art in GRADE_A_MINUS:
        return "A-"
    if art in GRADE_B:
        return "B"
    return "C"


def inst_type(name: str) -> str:
    if "护理院" in name:
        return "护理院"
    if "养老" in name or "敬老院" in name or "老年公寓" in name or "养护" in name:
        return "养老机构"
    if "医院" in name or "卫生院" in name or "社区卫生" in name:
        return "医疗机构"
    if "公司" in name:
        return "企业"
    return ""


def split_level(area: str) -> str:
    if area in {"全省试点"}:
        return "省级"
    if area.endswith("区"):
        return "区县级"
    if area.endswith("县"):
        return "区县级"
    if area.endswith("州") or area.endswith("盟"):
        return "地市级"
    return "地市级"


def build_t1(seed, arts):
    rows = []
    for i, (disc, inst, city, batch, year, art, flag) in enumerate(seed["t1"]["rows"], 1):
        adjusted = batch.startswith("区域中心")
        rows.append({
            "序号": i,
            "学科/类别": disc,
            "机构全称": inst,
            "省份": CITY_PROVINCE.get(city, ""),
            "城市": city,
            "批次": "2026调整（原区域中心2020）" if adjusted else batch,
            "入选年份": year if year else "",
            "调整年份": year if adjusted else "",
            "性质": "国家医学中心（2026由区域中心调整）" if adjusted else "国家医学中心",
            "证据等级（拟评）": grade(art),
            "文件出处": arts[art],
            "响应政策": "国卫办医函〔2020〕357号（设置推进）；2022年管理办法第十七条功能定位" if not adjusted else "国卫医政函〔2026〕95号",
            "床位（公开口径）": "",
            "运营状态": "",
            "入住率/床位使用率": "",
            "资金来源结构": "",
            "钱从哪里来": "",
            "难处在哪里": "",
            "运营备注": "",
            "补录来源": "",
            "来源类型": SEED_SOURCE,
            "核验提示": flag,
            "核验状态": PENDING,
        })
    return rows


def build_t2(seed, arts, domicile=None, canon_of=None):
    domicile = domicile or {}
    canon_of = canon_of or {}
    rows = []
    for i, (batch, proj, out_h, in_h, prov, city, year, flag) in enumerate(seed["t2"]["rows"], 1):
        art = seed["t2"]["batch_article"][batch]
        out_prov, out_city = domicile_of(out_h, domicile, canon_of)
        rows.append({
            "序号": i,
            "批次": batch,
            "项目全称": proj,
            "输出医院": out_h,
            "输出医院省份": out_prov,
            "输出医院城市": out_city,
            "依托/承接医院": in_h,
            "省份": prov,
            "城市": city,
            "年份": year,
            "性质": "国家区域医疗中心",
            "证据等级（拟评）": grade(art),
            "文件出处": arts[art],
            "响应政策": "发改社会〔2022〕527号（扩大建设方案）；国卫办医政发〔2022〕17号（管理办法）",
            "规划床位": "",
            "总投资（亿元）": "",
            "中央预算内投资（亿元）": "",
            "建设/运营状态": "",
            "床位（实际开放）": "",
            "资金来源结构": "",
            "钱从哪里来": "",
            "难处在哪里": "",
            "运营备注": "",
            "补录来源": "",
            "来源类型": SEED_SOURCE,
            "核验提示": flag,
            "核验状态": PENDING,
        })
    return rows


def build_t3(seed, arts):
    rows = []
    for i, (prov, inst, city, year, flag) in enumerate(seed["t3"]["rows"], 1):
        rows.append({
            "序号": i,
            "省份": prov,
            "机构全称": inst,
            "城市": city,
            "区县": "",
            "命名年份": year,
            "机构类型": inst_type(inst),
            "性质": "全国医养结合示范机构",
            "证据等级（拟评）": grade("A18"),
            "文件出处": arts["A18"],
            "床位（公开口径）": "",
            "入住率": "",
            "运营状态": "",
            "资金来源结构": "",
            "钱从哪里来": "",
            "难处在哪里": "",
            "响应政策": "国卫老龄发〔2022〕14号（示范项目工作方案）；国卫办老龄函〔2022〕128号",
            "运营备注": "",
            "补录来源": "",
            "来源类型": SEED_SOURCE,
            "核验提示": flag,
            "核验状态": PENDING,
        })
    return rows


def build_t4(seed, arts):
    expand = {"北京": 16, "浙江": 11, "湖南": 14}
    rows = []
    for i, (batch, prov, area, year, flag) in enumerate(seed["t4"]["rows"], 1):
        art = seed["t4"]["batch_article"][batch]
        is_prov = area == "全省试点"
        rows.append({
            "序号": i,
            "批次": batch,
            "省份": prov,
            "城市/地区": "全省" if is_prov else area,
            "层级": split_level(area),
            "年份": year,
            "展开市区数": expand.get(prov, "") if is_prov else "",
            "性质": "国家安宁疗护试点地区",
            "证据等级（拟评）": grade(art),
            "文件出处": arts[art],
            "代表机构": "",
            "机构数（公开）": "",
            "床位": "",
            "运营状态": "",
            "资金来源结构": "",
            "钱从哪里来": "",
            "难处在哪里": "",
            "响应政策": "国卫办老龄函〔2019〕483号；国卫办老龄函〔2023〕（第三批）",
            "运营备注": "",
            "补录来源": "",
            "来源类型": SEED_SOURCE,
            "核验提示": flag,
            "核验状态": PENDING,
        })
    return rows


def build_t5(seed, arts):
    rows = []
    for i, (disc, inst, city, batch, year, flag) in enumerate(seed["t5"]["rows"], 1):
        art = seed["t5"]["batch_article"][batch]
        rows.append({
            "序号": i,
            "领域": disc,
            "依托单位": inst,
            "省份": CITY_PROVINCE.get(city, ""),
            "城市": city,
            "批次": batch,
            "年份": year,
            "性质": "国家临床医学研究中心",
            "证据等级（拟评）": grade(art),
            "文件出处": arts[art],
            "床位（公开口径）": "",
            "运营状态": "",
            "资金来源结构": "",
            "钱从哪里来": "",
            "难处在哪里": "",
            "响应政策": "国科发社〔2017〕204号（管理办法2017修订）",
            "运营备注": "",
            "补录来源": "",
            "来源类型": SEED_SOURCE,
            "核验提示": flag,
            "核验状态": PENDING,
        })
    return rows


def build_t6(seed, arts):
    rows = []
    for i, (prov, inst, city, year, flag) in enumerate(seed["t6"]["rows"], 1):
        rows.append({
            "序号": i,
            "省份": prov,
            "机构全称": inst,
            "城市": city,
            "年份": year,
            "性质": "首批老龄健康医养结合远程协同服务试点",
            "证据等级（拟评）": grade("A721"),
            "文件出处": arts["A721"],
            "对接单位": "国家远程医疗与互联网医学中心",
            "床位（公开口径）": "",
            "入住率/运营状态": "",
            "资金来源结构": "",
            "钱从哪里来": "",
            "难处在哪里": "",
            "响应政策": "国卫办老龄函〔2020〕721号",
            "运营备注": "",
            "补录来源": "",
            "来源类型": SEED_SOURCE,
            "核验提示": flag,
            "核验状态": PENDING,
        })
    return rows


TAIL_COLS = ["补录来源", "来源类型", "核验提示", "核验状态"]


COLUMNS = {
    "t1": ["序号", "学科/类别", "机构全称", "省份", "城市", "批次", "入选年份", "调整年份",
           "性质", "证据等级（拟评）", "文件出处", "响应政策", "床位（公开口径）", "运营状态",
           "入住率/床位使用率", "资金来源结构", "钱从哪里来", "难处在哪里", "运营备注"] + TAIL_COLS,
    "t2": ["序号", "批次", "项目全称", "输出医院", "输出医院省份", "输出医院城市",
           "依托/承接医院", "省份", "城市", "年份", "性质",
           "证据等级（拟评）", "文件出处", "响应政策", "规划床位", "总投资（亿元）",
           "中央预算内投资（亿元）", "建设/运营状态", "床位（实际开放）", "资金来源结构",
           "钱从哪里来", "难处在哪里", "运营备注"] + TAIL_COLS,
    "t3": ["序号", "省份", "机构全称", "城市", "区县", "命名年份", "机构类型", "性质",
           "证据等级（拟评）", "文件出处", "床位（公开口径）", "入住率", "运营状态",
           "资金来源结构", "钱从哪里来", "难处在哪里", "响应政策", "运营备注"] + TAIL_COLS,
    "t4": ["序号", "批次", "省份", "城市/地区", "层级", "年份", "展开市区数", "性质",
           "证据等级（拟评）", "文件出处", "代表机构", "机构数（公开）", "床位", "运营状态",
           "资金来源结构", "钱从哪里来", "难处在哪里", "响应政策", "运营备注"] + TAIL_COLS,
    "t5": ["序号", "领域", "依托单位", "省份", "城市", "批次", "年份", "性质",
           "证据等级（拟评）", "文件出处", "床位（公开口径）", "运营状态", "资金来源结构",
           "钱从哪里来", "难处在哪里", "响应政策", "运营备注"] + TAIL_COLS,
    "t6": ["序号", "省份", "机构全称", "城市", "年份", "性质", "证据等级（拟评）", "文件出处",
           "对接单位", "床位（公开口径）", "入住率/运营状态", "资金来源结构", "钱从哪里来",
           "难处在哪里", "响应政策", "运营备注"] + TAIL_COLS,
}

SHEETS = {
    "t1": "01_表1_国家医学中心",
    "t2": "02_表2_区域医疗中心",
    "t3": "03_表3_医养示范机构",
    "t4": "04_表4_安宁疗护试点",
    "t5": "05_表5_临床研究中心",
    "t6": "06_表6_远程协同试点",
}

WIDTHS = {
    "序号": 6, "学科/类别": 14, "机构全称": 34, "省份": 8, "城市": 10, "批次": 14,
    "入选年份": 9, "调整年份": 8, "性质": 22, "证据等级（拟评）": 9, "文件出处": 30,
    "响应政策": 30, "床位（公开口径）": 14, "运营状态": 12, "入住率/床位使用率": 12,
    "资金来源结构": 18, "钱从哪里来": 18, "难处在哪里": 18, "运营备注": 18,
    "核验提示": 34, "核验状态": 14, "项目全称": 30, "输出医院": 30, "依托/承接医院": 28,
    "年份": 8, "规划床位": 10, "总投资（亿元）": 11, "中央预算内投资（亿元）": 12,
    "建设/运营状态": 13, "床位（实际开放）": 12, "区县": 10, "命名年份": 9,
    "输出医院省份": 12, "输出医院城市": 12, "补录来源": 26, "来源类型": 12,
    "机构类型": 11, "入住率": 10, "城市/地区": 12, "层级": 9, "展开市区数": 9,
    "代表机构": 26, "机构数（公开）": 10, "床位": 10, "领域": 14, "依托单位": 34,
    "对接单位": 26,
    "官网": 30, "官网来源": 34, "微信公众号": 24, "公众号来源": 34,
    "联系方式状态": 12, "链接校验": 40, "HTTP状态码": 10, "首页title": 34,
    "title佐证": 30, "联系信息备注": 46,
}


CONTACT_COLS = ["官网", "官网来源", "微信公众号", "公众号来源",
                "联系方式状态", "链接校验", "HTTP状态码", "首页title",
                "title佐证", "联系信息备注"]


def load_contact(path):
    """加载官网/公众号对照表，返回 (按机构名索引, 按机构ID索引, meta)。"""
    if not path:
        return {}, {}, {}
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"联系信息文件不存在: {path}")
    data = json.loads(p.read_text(encoding="utf-8"))
    by_name, by_id = {}, {}
    for r in data.get("rows", []):
        n = norm_key(r.get("机构全称", ""))
        if n:
            by_name[n] = r
        if r.get("机构ID"):
            by_id[r["机构ID"]] = r
    return by_name, by_id, data.get("meta", {})


def enrich_master(master, by_name, by_id):
    """把官网/公众号并入主表。命不中的行留空并标注"本轮未纳入查询范围"，
    绝不为了填满而猜测。"""
    hit = miss = 0
    for row in master:
        rec = by_id.get(row["机构ID"]) or by_name.get(norm_key(row["机构全称"]))
        if rec:
            row["官网"] = rec.get("官网", "")
            row["官网来源"] = rec.get("官网来源", "")
            row["微信公众号"] = rec.get("微信公众号", "")
            row["公众号来源"] = rec.get("公众号来源", "")
            row["联系方式状态"] = rec.get("状态", "")
            row["链接校验"] = rec.get("链接校验", "")
            row["HTTP状态码"] = rec.get("HTTP状态码", "")
            row["首页title"] = rec.get("首页title", "")
            row["title佐证"] = rec.get("title佐证", "")
            row["联系信息备注"] = rec.get("备注", "")
            hit += 1
        else:
            for c in CONTACT_COLS:
                row[c] = ""
            row["联系方式状态"] = "未查询"
            row["联系信息备注"] = "本轮未纳入查询范围（仅覆盖表1/表2/表5 涉及的头部机构）"
            miss += 1
    return {"命中": hit, "未查询": miss}


def write_sheet(ws, columns, rows):
    ws.append(columns)
    for cell in ws[1]:
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
    ws.row_dimensions[1].height = 34

    for row in rows:
        ws.append([row.get(c, "") for c in columns])

    for r in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(columns)):
        for cell in r:
            cell.font = BODY_FONT
            cell.alignment = TOP_WRAP
            cell.border = BORDER

    for idx, name in enumerate(columns, 1):
        ws.column_dimensions[get_column_letter(idx)].width = WIDTHS.get(name, 14)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{ws.max_row}"


def build_master(all_rows, canon_of=None, domicile=None):
    canon_of = canon_of or {}
    domicile = domicile or {}
    seen = {}
    order = []
    for key, rows in all_rows.items():
        role = {
            "t1": "国家医学中心", "t2": "区域中心承接", "t3": "医养示范机构",
            "t4": "安宁疗护试点地区", "t5": "临床研究中心", "t6": "远程协同试点",
        }[key]
        for row in rows:
            name = row.get("机构全称") or row.get("依托单位") or row.get("依托/承接医院")
            if not name:
                continue
            canon = canonical_name(name, canon_of)
            city = row.get("城市") or row.get("城市/地区") or ""
            prov = row.get("省份", "")
            if not city:
                dom_prov, dom_city = domicile_of(canon, domicile, canon_of)
                if dom_city:
                    city = dom_city
                    prov = prov or dom_prov
            sig = (canon, city)
            if sig not in seen:
                seen[sig] = {
                    "机构全称": canon, "省份": prov, "城市": city,
                    "出现表": [], "角色": [], "次数": 0, "别名": [],
                }
                order.append(sig)
            entry = seen[sig]
            entry["次数"] += 1
            if role not in entry["出现表"]:
                entry["出现表"].append(role)
            for src in (name, row.get("机构全称", "")):
                if src and src != canon and src not in entry["别名"]:
                    entry["别名"].append(src)
            if key == "t2":
                out_h = row.get("输出医院", "")
                if out_h:
                    ocanon = canonical_name(out_h, canon_of)
                    oprov, ocity = row.get("输出医院省份", ""), row.get("输出医院城市", "")
                    osig = (ocanon, ocity)
                    if osig not in seen:
                        seen[osig] = {"机构全称": ocanon, "省份": oprov, "城市": ocity,
                                      "出现表": ["区域中心输出"], "角色": [], "次数": 0,
                                      "别名": []}
                        order.append(osig)
                    elif "区域中心输出" not in seen[osig]["出现表"]:
                        seen[osig]["出现表"].append("区域中心输出")
                    seen[osig]["次数"] += 1

    by_canon = defaultdict(list)
    for sig in order:
        by_canon[sig[0]].append(sig)

    rows = []
    for i, sig in enumerate(order, 1):
        e = seen[sig]
        dup = "跨表重复，需人工确认是否同一法人" if len(e["出现表"]) > 1 else ""
        if len(by_canon[sig[0]]) > 1:
            same_city_hits = [o for o in by_canon[sig[0]] if o[1] == sig[1]]
            if len(same_city_hits) > 1:
                dup = (dup + "；" if dup else "") + "同城同名重复（城市取值来源不同，待核）"
        rows.append({
            "机构ID": f"ORG-{i:04d}",
            "机构全称": e["机构全称"],
            "别名/旧名": "；".join(e["别名"]),
            "省份": e["省份"],
            "城市": e["城市"],
            "出现表": "；".join(e["出现表"]),
            "出现次数": e["次数"],
            "重复提示": dup,
        })

    # 同名异地：canonical 归一后名字相同但城市不同，不能当作同一家合并。
    for canon, sigs in by_canon.items():
        cities = sorted({s[1] for s in sigs if s[1]})
        if len(cities) > 1:
            for r in rows:
                if r["机构全称"] == canon:
                    marker = f"同名异地（另出现于：{'、'.join(cities)}），城市来源待核，请勿合并"
                    r["重复提示"] = (r["重复提示"] + "；" if r["重复提示"] else "") + marker
    return rows


PROV_SHORT = {
    "北京市": "北京", "天津市": "天津", "上海市": "上海", "重庆市": "重庆",
    "河北省": "河北", "山西省": "山西", "辽宁省": "辽宁", "吉林省": "吉林",
    "黑龙江省": "黑龙江", "江苏省": "江苏", "浙江省": "浙江", "安徽省": "安徽",
    "福建省": "福建", "江西省": "江西", "山东省": "山东", "河南省": "河南",
    "湖北省": "湖北", "湖南省": "湖南", "广东省": "广东", "海南省": "海南",
    "四川省": "四川", "贵州省": "贵州", "云南省": "云南", "陕西省": "陕西",
    "甘肃省": "甘肃", "青海省": "青海", "台湾省": "台湾",
    "内蒙古自治区": "内蒙古", "广西壮族自治区": "广西", "西藏自治区": "西藏",
    "宁夏回族自治区": "宁夏", "新疆维吾尔自治区": "新疆",
}

NAME_KEY = {
    "t1": "机构全称", "t2": "项目全称", "t3": "机构全称",
    "t4": "城市/地区", "t5": "依托单位", "t6": "机构全称",
}


def shorten(value):
    v = (value or "").strip()
    return PROV_SHORT.get(v, v)


def norm_key(text):
    return re.sub(r"[\s（）()·、,，]", "", text or "").strip()


def make_row(table, raw, note=""):
    """Turn a compact research row into a full workbook row.

    Values the official attachment did not contain stay empty; the caller is
    responsible for saying where the values came from.
    """
    src = raw.get("补录来源", "")
    conf = raw.get("confidence", "")
    if conf == "official":
        kind = "官方原文"
    elif conf == "inferred":
        kind = "推断（待核）"
    else:
        kind = "官方附件原文"
    if table == "t2":
        return {
            "批次": raw.get("批次", ""), "项目全称": raw.get("项目全称", ""),
            "输出医院": raw.get("输出医院", ""), "输出医院省份": "", "输出医院城市": "",
            "依托/承接医院": raw.get("依托/承接医院", ""),
            "省份": shorten(raw.get("省份", "")), "城市": shorten(raw.get("城市", "")),
            "年份": raw.get("年份", ""), "性质": "国家区域医疗中心",
            "证据等级（拟评）": "A-" if conf == "official" else "C",
            "文件出处": raw.get("文件出处", ""),
            "响应政策": "发改社会〔2022〕527号（扩大建设方案）；国卫办医政发〔2022〕17号（管理办法）",
            "规划床位": "", "总投资（亿元）": "", "中央预算内投资（亿元）": "",
            "建设/运营状态": "", "床位（实际开放）": "", "资金来源结构": "",
            "钱从哪里来": "", "难处在哪里": "", "运营备注": "",
            "补录来源": src, "来源类型": kind,
            "核验提示": note or ("依托医院来自非官方来源，待核"
                                 if conf == "inferred" else ""),
            "核验状态": "已补录（来源已记录）",
        }
    if table == "t3":
        return {
            "省份": shorten(raw.get("省份", "")), "机构全称": raw.get("机构全称", ""),
            "城市": shorten(raw.get("城市", "")), "区县": "",
            "命名年份": raw.get("年份", ""), "机构类型": inst_type(raw.get("机构全称", "")),
            "性质": "全国医养结合示范机构", "证据等级（拟评）": "A",
            "文件出处": raw.get("文件出处", ""), "床位（公开口径）": "", "入住率": "",
            "运营状态": "", "资金来源结构": "", "钱从哪里来": "", "难处在哪里": "",
            "响应政策": "国卫老龄发〔2022〕14号（示范项目工作方案）；国卫办老龄函〔2022〕128号",
            "运营备注": "", "补录来源": src, "来源类型": kind,
            "核验提示": note, "核验状态": "已补录（官方附件原文）",
        }
    if table == "t4":
        area = raw.get("城市/地区", "")
        return {
            "批次": raw.get("批次", ""), "省份": shorten(raw.get("省份", "")),
            "城市/地区": area, "层级": raw.get("层级") or split_level(area),
            "年份": raw.get("年份", ""), "展开市区数": "",
            "性质": "国家安宁疗护试点地区", "证据等级（拟评）": "A",
            "文件出处": raw.get("文件出处", ""), "代表机构": "", "机构数（公开）": "",
            "床位": "", "运营状态": "", "资金来源结构": "", "钱从哪里来": "",
            "难处在哪里": "",
            "响应政策": "国卫办老龄函〔2019〕483号；国卫办老龄函〔2023〕128号",
            "运营备注": "", "补录来源": src, "来源类型": kind,
            "核验提示": note, "核验状态": "已补录（官方附件原文）",
        }
    if table == "t5":
        return {
            "领域": raw.get("领域", ""), "依托单位": raw.get("依托单位", ""),
            "省份": CITY_PROVINCE.get(shorten(raw.get("城市", "")), ""),
            "城市": shorten(raw.get("城市", "")), "批次": raw.get("批次", ""),
            "年份": raw.get("年份", ""), "性质": "国家临床医学研究中心",
            "证据等级（拟评）": "A", "文件出处": raw.get("文件出处", ""),
            "床位（公开口径）": "", "运营状态": "", "资金来源结构": "",
            "钱从哪里来": "", "难处在哪里": "",
            "响应政策": "国科发社〔2017〕204号（管理办法2017修订）",
            "运营备注": "", "补录来源": src, "来源类型": kind,
            "核验提示": note, "核验状态": "已补录（官方附件原文）",
        }
    if table == "t6":
        return {
            "省份": shorten(raw.get("省份", "")), "机构全称": raw.get("机构全称", ""),
            "城市": shorten(raw.get("城市", "")), "年份": raw.get("年份", ""),
            "性质": "首批老龄健康医养结合远程协同服务试点",
            "证据等级（拟评）": "A", "文件出处": raw.get("文件出处", ""),
            "对接单位": "国家远程医疗与互联网医学中心", "床位（公开口径）": "",
            "入住率/运营状态": "", "资金来源结构": "", "钱从哪里来": "",
            "难处在哪里": "", "响应政策": "国卫办老龄函〔2020〕721号",
            "运营备注": "", "补录来源": src, "来源类型": kind,
            "核验提示": note, "核验状态": "已补录（官方附件原文）",
        }
    if table == "t1":
        return {
            "学科/类别": raw.get("学科/类别", ""), "机构全称": raw.get("机构全称", ""),
            "省份": shorten(raw.get("省份", "")), "城市": shorten(raw.get("城市", "")),
            "批次": raw.get("批次", ""), "入选年份": raw.get("入选年份", ""),
            "调整年份": raw.get("调整年份", ""), "性质": raw.get("性质", ""),
            "证据等级（拟评）": raw.get("证据等级（拟评）", "A"),
            "文件出处": raw.get("文件出处", ""),
            "响应政策": raw.get("响应政策", ""), "床位（公开口径）": "",
            "运营状态": "", "入住率/床位使用率": "", "资金来源结构": "",
            "钱从哪里来": "", "难处在哪里": "", "运营备注": "",
            "补录来源": src, "来源类型": kind,
            "核验提示": raw.get("_核验提示", "") or note,
            "核验状态": "已补录（官方附件原文）",
        }
    raise ValueError(f"未知表 {table}")


def apply_patch(all_rows, patch_path):
    """Apply this round's corrections on top of the seed rows.

    The seed file is treated as the immutable transcription: nothing here writes
    back to it. Every patch entry must state where the new value came from, and
    rows added by patch carry a 补录来源 column so they can be told apart from
    the user's original rows later.
    """
    report = {"applied": False, "added": {}, "replaced": {}, "set_hits": 0,
              "dropped": [], "unmatched": []}
    if not patch_path:
        return report
    path = Path(patch_path)
    if not path.exists():
        return report
    patch = json.loads(path.read_text(encoding="utf-8"))
    report["evidence"] = patch.get("evidence", [])

    for table, new_rows in (patch.get("add") or {}).items():
        if table not in all_rows:
            report["unmatched"].append(f"add: 未知表 {table}")
            continue
        for raw in new_rows:
            if "序号" in raw:
                row = dict(raw)
            else:
                row = make_row(table, raw)
            all_rows[table].append(row)
        report["added"][table] = report["added"].get(table, 0) + len(new_rows)

    # replace: the official attachment becomes the table of record, but rows
    # that exist only in the user's original transcript are kept at the end and
    # flagged, because dropping them would silently lose a discrepancy.
    for table, spec in (patch.get("replace") or {}).items():
        if table not in all_rows:
            report["unmatched"].append(f"replace: 未知表 {table}")
            continue
        # Same hospital often holds several national identities, so the match
        # key must carry the role/batch; matching on the name alone would hide
        # rows that exist only in the original transcript.
        sig_fields = {
            "t1": ("学科/类别", "机构全称"),
            "t2": ("项目全称",),
            "t3": ("机构全称",),
            "t4": ("批次", "省份", "城市/地区"),
            "t5": ("批次", "依托单位"),
            "t6": ("机构全称",),
        }[table]

        def sig_of(row):
            return tuple(norm_key(row.get(f, "")) for f in sig_fields)
        old_rows = all_rows[table]
        new_norms = {sig_of(r) for r in spec["rows"]}
        orphans = [r for r in old_rows
                   if sig_of(r) and sig_of(r) not in new_norms]
        built = [make_row(table, r) for r in spec["rows"]]
        for r in orphans:
            r["来源类型"] = SEED_SOURCE
            r["核验提示"] = (r.get("核验提示", "") + "；").lstrip("；") + \
                "原整理稿有、官方名单未收录，来源待核"
            r["核验状态"] = "存疑（未在官方名单中查到）"
        all_rows[table] = built + orphans
        report["replaced"][table] = {"新": len(built), "保留孤行": len(orphans)}

    for item in patch.get("set") or []:
        table = item["表"]
        rows = all_rows.get(table, [])
        hits = 0
        for row in rows:
            if all(str(row.get(k, "")) == str(v) for k, v in item["match"].items()):
                row.update(item["字段"])
                hits += 1
        if hits == 0:
            report["unmatched"].append(f"set: {table} {item['match']}")
        report["set_hits"] += hits

    for item in patch.get("drop") or []:
        table = item["表"]
        rows = all_rows.get(table, [])
        kept, removed = [], []
        for row in rows:
            if all(str(row.get(k, "")) == str(v) for k, v in item["match"].items()):
                removed.append(row.get("机构全称") or row.get("项目全称")
                               or row.get("城市/地区") or "")
            else:
                kept.append(row)
        all_rows[table] = kept
        report["dropped"].append({"表": table, "数量": len(removed),
                                  "对象": removed, "原因": item.get("reason", "")})

    for rows in all_rows.values():
        for i, row in enumerate(rows, 1):
            row["序号"] = i
    report["applied"] = True
    return report


def write_notes(ws):
    lines = [
        ("机构台账六表（2026-10-31 补齐版）", "title"),
        ("", ""),
        ("来源分层：官方来源行 = 取自国家部委官网原文及其附件的行；原整理稿独有行 = 用户 2026-10-30 提供的六张整理稿", ""),
        ("中有、但官方名单里查不到的行。后者一律保留不删，标 存疑（未在官方名单中查到），不计入任何官方口径统计。", "warn"),
        ("每条补录行都带 补录来源 URL；没有来源的字段一律留空，不做填补。", ""),
        ("", ""),
        ("一、本版各表行数（官方行 / 保留的孤儿行）", "h"),
        ("表1 国家医学中心：30 / 7。37 行原始整理稿里 7 行（安贞、天津肿瘤、301、华西、湘雅、华山、宣武 的「老年医学」行）", ""),
        ("  不属国家医学中心，官方 357 号附件名单只有 阜外、肿瘤医院、北京医院 三家，这 7 行已移为孤儿行待核。", ""),
        ("表2 区域医疗中心：125 / 0。原 50 行 + 第四批 26 + 第五批 49，达成官方 125 全量。", ""),
        ("表3 医养结合示范机构：99 / 19。99 家取自国卫老龄函〔2024〕18号附件2。", ""),
        ("表4 安宁疗护试点：141 / 13。三批官方通知附件全量；其中 4 行是省级试点单位，具名市区 137 个。", ""),
        ("表5 临床医学研究中心：50 / 4。四批认定附件合并，达成官方 50 家。", ""),
        ("表6 医养远程协同试点：174 / 26。174 家取自国卫办老龄函〔2020〕721号名单。", ""),
        ("", ""),
        ("二、三个口径决策（用户 2026-10-30 拍板）", "h"),
        ("1. 表1「中医」计入：保留天津中医药大学第一附属医院 1 行，但必须知道——它是“辅导类”国家医学中心创建单位，", ""),
        ("   不是正式设置的国家医学中心（依据：国家中医药管理局答复 国中医药建议字〔2022〕72号：2021 年将 6 所中医", ""),
        ("   医院纳入“辅导类”创建范围）。官方 13 类 26 个口径不含中医类。统计时须与正式行分开。", "warn"),
        ("2. 表4 展开到市区：北京、浙江、湖南三省“全省试点”官方原文未列逐区名单（北京只写“全市16区和经开区全部纳入”），", ""),
        ("   按纪律不展开。具名 137 个 + 推算 48 个 = 官方 185 口径，推算部分的逐区名单待补。", "warn"),
        ("3. 表2 补满 125：已按第四批 26 + 第五批 49 补齐。", ""),
        ("", ""),
        ("三、已知缺口（未解决，不要当成已核实）", "h"),
        ("表1：传染病中心第三家 浙大一院 的设置文号未核到（81号文原文只列华山、地坛），本行标 A- 待核。", ""),
        ("表2：75 个补录行中 34 行的依托/承接医院取自非官方来源，标 推断（待核），证据等级 C。", ""),
        ("表3/表6：原整理稿与官方名单近乎不重合（表3 仅 11/30 重合、表6 仅 4/30 重合），说明原稿来自另一套来源，", ""),
        ("   这 45 行孤儿行的真实出处未知，不要直接采信。", "warn"),
        ("表4：185 口径未对平，缺三省逐区名单。", ""),
        ("六表共同：床位、入住率、资金来源、钱从哪来、难处 五列仍全部为空，需要 B6 抽样检索填补。", ""),
        ("", ""),
        ("四、四套口径（必须先定，否则数字不可比）", "h"),
        ("年份：名单公布年 / 批复年 / 开业年 三者分开；表1 另设 调整年份（2026 年儿童双中心调整）。", ""),
        ("床位：编制 / 开放 / 实际开放 / 规划 四选一，必须与年份同写，例：1200（编制，2024）。", ""),
        ("运营：状态枚举（在建/试运营/正式运营/停诊/未查到）与 入住率数值 分列，不得互相替代。", ""),
        ("资金：中央预算内投资 ≠ 总投资 ≠ 专项债 ≠ 自筹，四个标签不得合并成一个数字。", ""),
        ("", ""),
        ("五、证据等级（拟评）", "h"),
        ("A＝文号完整且名单可定位到附件具体行；A-＝官方批次但文号缺序号；B＝来源可追溯但文号不全或非名单文件；", ""),
        ("C＝非官方来源推断。等级是“拟评”，正式转正须填写 08_证据台账（source_url、原文句、fetched_at、reviewer）。", ""),
        ("", ""),
        ("六、机构主表", "h"),
        ("主表按「机构全称 + 城市」归并，跨表同名的以 别名/旧名 列记录原始写法；同一医院多个国家身份（如华山同时是", ""),
        ("神经疾病、传染病两个国家医学中心）在主表只算一家，在业务表各留一行。统计机构数一律以主表为准。", ""),
        ("别名归一已处理军队医院旧番号：第四军医大学西京医院→空军军医大学西京医院等。", ""),
        ("中国人民解放军总医院第五医学中心 与 总医院本体 记录为相关但不同主体，不合并计数。", ""),
        ("", ""),
        ("七、官网与微信公众号（2026-11-01 新增列，务必先读这一段再用）", "h"),
        ("覆盖范围：本轮只查表1 国家医学中心、表2 区域医疗中心（输出+承接）、表5 临床研究中心 涉及的头部机构，", ""),
        ("  去重后 212 家。主表其余 315 家（多为表3/表6 的护理院、养老院）未查，官网与公众号列留空并标 未查询。", "warn"),
        ("", ""),
        ("公众号的录入纪律：只在官方页面（机构官网、政府/卫健委官网、医院自身公众号推文）出现明确名称文字时才录入，", ""),
        ("  一律不用机构全称推断。这一点很关键——公众号名 ≠ 机构全称是常态，例如：", ""),
        ("  郑州大学第三附属医院→「河南省妇幼保健院」；柳州市妇幼保健院→「柳州市妇幼保健院」(微信号 lzsfy1958)；", ""),
        ("  贵州省骨科医院→「贵州骨科人」；青海省中医院→「青海省中医院智慧医院」；", ""),
        ("  浙江大学医学院附属邵逸夫医院→「浙大邵逸夫医院」（服务号）；四川大学华西第二医院→「华西第二医院」；", ""),
        ("  上海交通大学医学院附属上海儿童医学中心→「上海儿童医学中心患者服务」。按全称推断至少会填错 8 家以上。", "warn"),
        ("  官网只放二维码图片不给名称文字的（如河南省精神病医院、西藏自治区妇产儿童医院、中山大学孙逸仙纪念医院），", ""),
        ("  公众号一律留空——猜错比留空危害大得多。", "warn"),
        ("", ""),
        ("官网的录入纪律：只认机构自运营的域名。第三方挂号/问诊平台（微医、好大夫、114、39健康、有来医生）、", ""),
        ("  聚合登记页（全国养老服务信息平台、省养老网、企查查、企业信用信息公示系统）、百科、新闻、导航站 一律不算。", ""),
        ("", ""),
        ("机器校验结果怎么看（链接校验 / HTTP状态码 / title佐证 三列）：", ""),
        ("  非 200 不等于域名错。医院站点普遍部署 WAF 反爬（412/403）或用自签证书（SSL 握手失败），", ""),
        ("  这些情况下域名本身未被证伪。域名的依据始终是官方页面原文，校验列只作人工复核线索。", "warn"),
        ("  title佐证＝一致：打开的首页标题能佐证该域名属于这家机构。", ""),
        ("  title佐证＝名称不同：多为国家区域医疗中心挂牌改名（如 崇礼区人民医院 首页标题已是「北京大学第三医院崇礼院区」、", ""),
        ("  贵州省骨科医院→「北京积水潭医院贵州医院」、德州市人民医院→「山东大学齐鲁医院德州医院」），属正常，不是错。", ""),
        ("  title佐证＝未能判定：页面无有效标题、站点维护中，或本机网络未连通，需人工打开一次确认。", ""),
        ("", ""),
        ("待人工确认的一处：清单里的「西藏自治区医院」未检索到对应独立机构，疑为西藏自治区人民医院的简称，", ""),
        ("  本表按西藏自治区人民医院录入（官网 tarph.cn），主体是否等同需人工核对。", "warn"),
    ]
    ws.column_dimensions["A"].width = 118
    r = 1
    for text, kind in lines:
        cell = ws.cell(row=r, column=1, value=text)
        if kind == "title":
            cell.font = Font(name="微软雅黑", size=14, bold=True, color="1F3864")
        elif kind == "h":
            cell.font = Font(name="微软雅黑", size=10, bold=True, color="1F3864")
        elif kind == "warn":
            cell.font = Font(name="微软雅黑", size=9, bold=True, color="C00000")
        else:
            cell.font = Font(name="微软雅黑", size=9, color="333333")
        cell.alignment = Alignment(vertical="top", wrap_text=True)
        r += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--patch", default=None,
                    help="本轮补正记录（新增行/改字段/删重复），不改动原始 seed")
    ap.add_argument("--domicile", default=DEFAULT_DOMICILE)
    ap.add_argument("--aliases", default=DEFAULT_ALIASES)
    ap.add_argument("--contact", default=None,
                    help="官网/微信公众号对照表（由 merge_institution_contact.py 生成）")
    args = ap.parse_args()

    seed = json.loads(Path(args.seed).read_text(encoding="utf-8"))
    arts = seed["articles"]
    domicile, _ = load_reference(args.domicile, "entries", "domicile")
    canon_of, _ = load_reference(args.aliases, "groups", "alias")

    all_rows = {
        "t1": build_t1(seed, arts),
        "t2": build_t2(seed, arts, domicile, canon_of),
        "t3": build_t3(seed, arts),
        "t4": build_t4(seed, arts),
        "t5": build_t5(seed, arts),
        "t6": build_t6(seed, arts),
    }

    patch_report = apply_patch(all_rows, args.patch)

    wb = Workbook()
    wb.remove(wb.active)

    write_notes(wb.create_sheet("00_说明"))

    for key in ["t1", "t2", "t3", "t4", "t5", "t6"]:
        ws = wb.create_sheet(SHEETS[key])
        write_sheet(ws, COLUMNS[key], all_rows[key])

    master = build_master(all_rows, canon_of, domicile)
    by_name, by_id, contact_meta = load_contact(args.contact)
    contact_report = enrich_master(master, by_name, by_id) if by_name else {"命中": 0, "未查询": len(master)}
    ws = wb.create_sheet("07_机构主表")
    write_sheet(ws, ["机构ID", "机构全称", "别名/旧名", "省份", "城市",
                     "出现表", "出现次数", "重复提示"] + CONTACT_COLS, master)

    evidence_rows = []
    fetched = datetime.now().astimezone().isoformat(timespec="seconds")
    for e in patch_report.get("evidence", []):
        evidence_rows.append({
            "evidence_id": e.get("evidence_id", ""),
            "对应表": e.get("对应表", ""),
            "文件/附件": e.get("文件/附件", ""),
            "source_url": e.get("source_url", ""),
            "来源层级": e.get("来源层级", ""),
            "原文要点": e.get("原文要点", ""),
            "published_at": e.get("published_at", ""),
            "fetched_at": fetched,
            "review_status": "来源已记录（未经独立复核）",
            "reviewer": "",
            "reviewed_at": "",
        })
    ws = wb.create_sheet("08_证据台账")
    write_sheet(ws, ["evidence_id", "对应表", "文件/附件", "source_url", "来源层级",
                     "原文要点", "published_at", "fetched_at", "review_status",
                     "reviewer", "reviewed_at"], evidence_rows)
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=False)

    ws = wb.create_sheet("09_统计")
    stats = []
    dup_master = [m for m in master if m["重复提示"]]
    for key in ["t1", "t2", "t3", "t4", "t5", "t6"]:
        rows = all_rows[key]
        names = {r.get("机构全称") or r.get("依托单位") or r.get("依托/承接医院") or ""
                 for r in rows}
        names.discard("")
        g = Counter(r["证据等级（拟评）"] for r in rows)
        official = sum(1 for r in rows
                       if r.get("来源类型") in {"官方原文", "官方附件原文"})
        orphans = sum(1 for r in rows if "原整理稿有、官方名单未收录" in (r.get("核验提示") or ""))
        stats.append({
            "表": SHEETS[key], "总行数": len(rows),
            "官方来源行": official,
            "推断行": sum(1 for r in rows if r.get("来源类型") == "推断（待核）"),
            "用户整理稿行": sum(1 for r in rows if r.get("来源类型") == SEED_SOURCE),
            "原整理稿独有行": orphans,
            "拟评A": g.get("A", 0), "拟评A-": g.get("A-", 0), "拟评B": g.get("B", 0),
            "拟评C": g.get("C", 0),
            "仍待核行": sum(1 for r in rows if "待核" in (r.get("核验状态") or "")),
        })
    write_sheet(ws, ["表", "总行数", "官方来源行", "推断行", "用户整理稿行",
                     "原整理稿独有行", "拟评A", "拟评A-", "拟评B", "拟评C", "仍待核行"], stats)
    c_hit = contact_report.get("命中", 0)
    for extra in [
        ["机构主表机构数", len(master)],
        ["跨表重复机构数", len(dup_master)],
        ["六表合计行", sum(len(v) for v in all_rows.values())],
        [],
        ["— 官网/微信公众号（本轮覆盖表1/表2/表5 涉及的头部机构）—", ""],
        ["纳入查询机构数（去重后）", contact_meta.get("机构数", "")],
        ["主表命中联系信息行数", c_hit],
        ["主表未纳入查询行数", contact_report.get("未查询", 0)],
        ["其中：有官网", sum(1 for m in master if m.get("官网"))],
        ["其中：有公众号", sum(1 for m in master if m.get("微信公众号"))],
        ["官网命中率（占命中行）",
         f"{sum(1 for m in master if m.get('官网')) / c_hit:.1%}" if c_hit else ""],
        ["公众号命中率（占命中行）",
         f"{sum(1 for m in master if m.get('微信公众号')) / c_hit:.1%}" if c_hit else ""],
    ]:
        if not extra:
            ws.append([])
            continue
        ws.append([])
        ws.append(extra)
        for cell in ws[ws.max_row]:
            cell.font = BODY_FONT

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)

    print(json.dumps({
        "output": str(out),
        "rows": {k: len(v) for k, v in all_rows.items()},
        "master": len(master),
        "duplicates": len(dup_master),
        "patch": patch_report,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
