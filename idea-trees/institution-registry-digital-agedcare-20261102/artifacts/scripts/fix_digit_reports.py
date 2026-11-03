# -*- coding: utf-8 -*-
"""规范化 digit_reports_batch*.json（幂等，可重跑）
1) 按「机构名称/医院名称」确定性纠正写错的 机构ID/医院ID（不影响内容，仅修关联键）
2) 补齐 projects/reports 缺失键（填空串）
3) reports「来源类型」归一化到 8 个主类（统一 pilot 期自由标注）
4) projects 医院ID 为空时，用「招标单位」确定性匹配台账机构ID并回填医院名称/省份
5) 对「招标单位为挂牌分院/含主机构名的近似匹配」在信息缺口追加主体差异声明
仅在本次任务产出的批次 JSON 上运行，不改动历史采集原文与报道内容。
"""
import json, glob, os, re

BASE = "configs"
R_KEYS = ["机构名称", "机构ID", "省份", "公众号", "报道标题", "来源类型", "来源链接",
          "发布时间", "响应政策", "内容总结", "技术支持机构", "资金支持机构",
          "目的与结果", "是否明确项目", "备注"]
P_KEYS = ["时间", "项目名称", "产品", "招标单位", "客户标签", "中标单位", "运营商类型",
          "中标金额万元", "场景", "评审专家", "网址", "公告类型", "省份", "项目编号",
          "中标金额原文", "信息缺口", "标签依据", "响应人资格要求（对供应商基本要求）",
          "资格预审资质要求", "来源平台", "资格要求出处", "原文文件", "医院名称", "医院ID",
          "日期依据", "采购人依据", "采集来源", "抓取时间", "公告ID", "原文SHA256",
          "数字化标签", "入口任务ID", "金额口径备注", "批次", "来源记录数", "字段差异数",
          "来源文件", "来源工作表", "原始行号"]

MAIN_TYPES = {"公众号原文", "官网新闻", "媒体转载", "采购公告", "中标公告", "学术", "财政", "行业会议"}
_NORM = [("中标", "中标公告"), ("采购公告", "采购公告"), ("财政", "财政"),
         ("公众号", "公众号原文"), ("行业会议", "行业会议"), ("会议", "行业会议"),
         ("学术", "学术"), ("期刊", "学术"), ("蓝皮书", "学术"),
         ("官网", "官网新闻"), ("院报", "官网新闻"), ("媒体", "媒体转载")]

def norm_srctype(v):
    s = str(v or "").strip()
    if not s:
        return s
    if s in MAIN_TYPES:
        return s
    for kw, main in _NORM:
        if kw in s:
            return main
    return "其他"

# 台账机构映射（targets 批次 + pilot 名单，名称->ID/省份）
name2id, id2prov = {}, {}
for f in glob.glob(os.path.join(BASE, "digit_targets_batch*.json")):
    for e in json.load(open(f, encoding="utf-8"))["entries"]:
        name2id[e["机构全称"]] = e["机构ID"]
        id2prov[e["机构ID"]] = e["省份"]
try:
    for p in json.load(open(os.path.join(BASE, "pilot_targets_20261101.json"), encoding="utf-8"))["pilot"]:
        name2id[p["机构全称"]] = p["机构ID"]
        id2prov[p["机构ID"]] = p.get("省份", "")
except FileNotFoundError:
    pass

def match_inst(b):
    """返回 (机构ID, 台账全称, 是否近似匹配)"""
    b = str(b or "").strip()
    if not b:
        return "", "", False
    if b in name2id:
        return name2id[b], b, False
    b2 = re.sub(r"[（(].*?[)）]", "", b).strip()
    if b2 in name2id:
        return name2id[b2], b2, True
    m = re.search(r"[（(](.*?)[)）]", b)
    if m and m.group(1).strip() in name2id:
        nm = m.group(1).strip()
        return name2id[nm], nm, True
    for n, i in name2id.items():
        if n in b or (len(b) >= 4 and b in n):
            return i, n, True
    return "", "", False

NOTE = "【规范化】招标单位为挂牌/区域中心输出分院，医院ID按台账主机构归并，采购主体以『招标单位』原文为准，主体是否等同需人工复核"

tot_fillkey = tot_norm = tot_fixid = tot_fillid = tot_approx = tot_fillprov = 0
for f in sorted(glob.glob(os.path.join(BASE, "digit_reports_batch*.json"))):
    d = json.load(open(f, encoding="utf-8"))
    changed = False
    # ---- reports ----
    for r in d.get("reports", []):
        for k in R_KEYS:
            if k not in r:
                r[k] = ""; changed = True; tot_fillkey += 1
        # 纠错：机构名称在台账中，则强制用台账ID
        nm = str(r.get("机构名称") or "").strip()
        if nm in name2id and str(r.get("机构ID") or "").strip() != name2id[nm]:
            r["机构ID"] = name2id[nm]; changed = True; tot_fixid += 1
        nv = norm_srctype(r.get("来源类型"))
        if nv != r.get("来源类型"):
            r["来源类型"] = nv; changed = True; tot_norm += 1
    # ---- projects ----
    for p in d.get("projects", []):
        for k in P_KEYS:
            if k not in p:
                p[k] = ""; changed = True; tot_fillkey += 1
        # 纠错：医院名称在台账中，则强制用台账ID
        pnm = str(p.get("医院名称") or "").strip()
        if pnm in name2id and str(p.get("医院ID") or "").strip() != name2id[pnm]:
            p["医院ID"] = name2id[pnm]; changed = True; tot_fixid += 1
        # 回填空医院ID
        if not str(p.get("医院ID") or "").strip():
            bidder = p.get("招标单位") or ""
            iid, nm, approx = match_inst(bidder)
            if iid:
                p["医院ID"] = iid
                p["医院名称"] = nm
                changed = True; tot_fillid += 1
                if approx:
                    p["信息缺口"] = (str(p.get("信息缺口") or "") + "；" + NOTE).strip("；")
                    tot_approx += 1
            elif not str(p.get("医院名称") or "").strip() and bidder:
                p["医院名称"] = bidder
                changed = True
        if not str(p.get("省份") or "").strip() and p.get("医院ID") in id2prov:
            p["省份"] = id2prov[p["医院ID"]]; changed = True; tot_fillprov += 1
    if changed:
        json.dump(d, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"  已修复 {os.path.basename(f)}")

print(f"\n补键 {tot_fillkey} | 纠正机构ID {tot_fixid} | 来源类型归一化 {tot_norm} | "
      f"回填医院ID {tot_fillid}（近似匹配标注 {tot_approx}）| 回填省份 {tot_fillprov}")
