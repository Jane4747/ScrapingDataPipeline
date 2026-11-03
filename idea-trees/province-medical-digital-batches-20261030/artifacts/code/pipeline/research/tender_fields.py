"""Source-grounded fields shared by the three procurement collectors."""
from __future__ import annotations
import hashlib
import re
from bs4 import BeautifulSoup

HEADERS = ["时间", "项目名称", "产品", "招标单位", "客户标签", "中标单位", "运营商类型", "中标金额（万元）", "场景",
           "评审专家", "网址", "公告类型", "省份", "项目编号", "中标金额原文", "信息缺口", "标签依据",
           "响应人资格要求（对供应商基本要求）", "资格预审资质要求", "来源平台", "资格要求出处", "原文文件"]
QUAL = HEADERS[17]
PREQUAL = HEADERS[18]


def article_text(html):
    soup = BeautifulSoup(html or "", "html.parser")
    node = soup.select_one("#mycontent,.vF_detail_content,.BodyLabel,.article-content,.div-content,.content") or soup.body or soup
    for unwanted in node.select("script,style,nav,header,footer"):
        unwanted.decompose()
    return "\n".join(re.sub(r"[ \t\u3000]+", " ", s).strip() for s in node.get_text("\n", strip=True).splitlines() if s.strip())


MAJOR = re.compile(r"^[一二三四五六七八九十]+[、．.]")
NEXT_SECTION = re.compile(r"^(?:[一二三四五六七八九十\d]+[、．.]\s*)?(?:获取(?:招标|采购|磋商|谈判|资格预审)文件|(?:提交|递交|开启|响应|投标)文件|公告期限|开标时间|其他补充事宜|联系方式|采购人信息|代理服务收费)")


def section(text, pattern):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = re.search(pattern, line)
        if not match:
            continue
        # A table of contents or cross-reference is not the actual requirement.
        if re.search(r"详见|参见|见第|目录", line[:match.start()]):
            continue
        prefix = re.match(r"^\s*(\d+)[、．.]\s*[^\d]", line)
        parts = [line[match.end():].lstrip("：: ")]
        for nxt in lines[i + 1:]:
            if MAJOR.match(nxt) or NEXT_SECTION.match(nxt):
                break
            number = re.match(r"^(\d+)[、．.]\s*[^\d]", nxt)
            if prefix and number and number.group(1) != prefix.group(1) and len(nxt) < 50 and re.search(r"获取|递交|开标|审查方法|项目概况|联系方式", nxt):
                break
            parts.append(nxt)
        value = "\n".join(p for p in parts if p).strip().lstrip("：: \n")
        if value:
            return value, i + 1
    return "", None


def extract_fields(html, title="", url=""):
    text = article_text(html)
    experts, expert_line = section(text, r"(?:评审专家(?:[（(][^）)]*[）)])?(?:名单)?|评标委员会(?:成员)?名单|评标专家名单|谈判小组(?:成员)?名单)\s*[：:]?")
    basic, basic_line = section(text, r"(?:申请人(?:的)?资格要求|(?:供应商|投标人|响应人)(?:的)?(?:基本)?资格(?:条件|要求)|合格供应商(?:的)?条件)\s*[：:]?")
    prequal, prequal_line = section(text, r"(?:资格预审(?:申请人)?(?:资质|资格)?(?:条件|要求)|资格预审资质要求)\s*[：:]?")
    if not prequal and "资格预审" in title and basic:
        prequal, prequal_line = basic, basic_line
    values = {"评审专家": experts, QUAL: basic, PREQUAL: prequal}
    lines = {"评审专家": expert_line, QUAL: basic_line, PREQUAL: prequal_line}
    evidence = {field: {"url": url, "text_line": lines[field], "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                        "quote": value} for field, value in values.items() if value}
    return {**values, "_field_evidence": evidence}


def add_fields(row, html, title="", url=""):
    extra = extract_fields(html, title, url)
    row.update(extra)
    return row


def normalize(row, source):
    result = {key: row.get(key, "") for key in HEADERS}
    result.update(时间=str(row.get("时间") or row.get("公告日期") or "")[:10],
                  网址=row.get("网址") or row.get("相关网页") or row.get("公告链接") or "",
                  来源平台=source, 原文文件=row.get("原文文件") or row.get("_evidence_html") or "")
    result["省份"] = row.get("省份") or row.get("地域") or ""
    result["标签依据"] = row.get("标签依据") or "客户标签、运营商类型及场景来自采购人/供应商名称与公告标题规则；公告事实取原文，规则标签待核验"
    missing = [s for s in str(row.get("信息缺口") or "").split("；") if s]
    if not result["评审专家"]:
        missing.append("本公告未提取到评审专家")
    if not result[QUAL]:
        missing.append("本公告未提取到供应商资格要求，待同项目采购公告补充")
    if not result[PREQUAL]:
        missing.append("本公告未提取到资格预审要求或不适用")
    if not result["产品"]:
        missing.append("产品未提取")
    result["信息缺口"] = "；".join(dict.fromkeys(missing))
    if result[QUAL] or result[PREQUAL]:
        result["资格要求出处"] = result["资格要求出处"] or result["网址"]
    result["_field_evidence"] = row.get("_field_evidence", {})
    result["_is_final_award"] = row.get("_is_final_award", None)
    return result


def link_qualifications(rows):
    """Only link an exact project code AND exact named purchaser; keep every notice."""
    groups = {}
    for row in rows:
        key = (str(row.get("项目编号", "")).strip(), str(row.get("招标单位", "")).strip())
        if all(key):
            groups.setdefault(key, []).append(row)
    for values in groups.values():
        for row in values:
            for field in (QUAL, PREQUAL):
                if row.get(field):
                    continue
                donors = [r for r in values if r.get(field) and (not row.get("时间") or r.get("时间", "") <= row["时间"])]
                unique = {r[field] for r in donors}
                if len(unique) == 1:
                    donor = max(donors, key=lambda r: r.get("时间", ""))
                    row[field] = donor[field]
                    row["资格要求出处"] = "；".join(dict.fromkeys(filter(None, [row.get("资格要求出处"), donor.get("网址")])))
                    row.setdefault("_field_evidence", {})[field] = donor.get("_field_evidence", {}).get(field, {"url": donor["网址"], "quote": donor[field]})
                    row["信息缺口"] = "；".join(x for x in row.get("信息缺口", "").split("；") if not (field == QUAL and x.startswith("本公告未提取到供应商")) and not (field == PREQUAL and x.startswith("本公告未提取到资格预审")))
                elif len(unique) > 1:
                    row["信息缺口"] += "；同项目资格要求有多个版本，未自动合并"
    return rows
