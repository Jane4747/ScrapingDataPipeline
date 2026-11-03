# -*- coding:utf-8 -*-
"""北京市政府采购网（www.ccgp-beijing.gov.cn）医疗类公告。

入口说明（2026-10-27 实测）：
- 该站 443 端口在本机两条不同网络下都建立不了 TCP 连接（SYN 被丢弃，curl 亦 000），
  但 80 端口正常返回 200 且首页不做 https 跳转，因此按 HTTP 入口采集。
- robots.txt 在 HTTP 下返回 404（即没有 robots 规则）。
- UA 使用本库统一的自报标识，不伪装成浏览器。

栏目（市级/区级信息公告下的中标公告、招标公告）：
- 市级中标公告 /xxgg/sjxxgg/zbggs/A002004001002index_{page}.htm
- 区级中标公告 /xxgg/qjxxgg/qjzbggs/A002004002002index_{page}.htm
- 市级招标公告 /xxgg/sjxxgg/zbgg/A002004001001index_{page}.htm

匹配口径：标题命中医疗卫生机构词（医院/卫生/疾控/医保等）才进入详情，
再按数字化词、设备词给它打类型标签；本脚本不使用 utils 里的产业政策关键词表，
避免把"设备更新/以旧换新"这类政策口径混进招采结果。
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.extend(['.', '..'])

from utils import logger, now, year_month, write_file, sleep_time  # noqa: E402
from site_fetch import fetch, FetchError, USER_AGENT  # noqa: E402

GOVERMENT = "北京市政府采购网-医疗公告"
REGION = "市级"
BASE = "http://www.ccgp-beijing.gov.cn"

CHANNELS = [
    ("市级中标公告", "/xxgg/sjxxgg/zbggs/A002004001002index_%d.htm"),
    ("区级中标公告", "/xxgg/qjxxgg/qjzbggs/A002004002002index_%d.htm"),
    ("市级招标公告", "/xxgg/sjxxgg/zbgg/A002004001001index_%d.htm"),
]

MED_ORG = ["医院", "医疗", "卫生院", "卫生服务", "卫生健", "卫生", "疾控", "医保",
           "中医", "妇幼", "保健", "急救", "血液", "康复", "门诊", "诊所", "医学",
           "儿科", "妇产", "肿瘤", "口腔", "精神卫生", "计划生育"]
# 只有弱信号（基层/健康/养老）时，标题带这些行业词的按非医卫排除
WEAK_ORG = ["基层", "健康", "养老"]
DIGITAL = ["信息化", "信息系统", "智慧", "电子病历", "互联网医院", "互联网诊疗", "远程医疗",
           "大数据", "云计算", "云平台", "云服务", "数据中心", "算力", "超融合", "虚拟化",
           "服务器", "存储", "数据库", "机房", "灾备", "容灾", "网络安全", "信息安全",
           "等级保护", "密码应用", "电子签名", "无纸化", "运维", "软件", "系统集成",
           "系统升级", "接口改造", "中台", "数据治理", "健康档案", "区域卫生",
           "HIS", "LIS", "PACS", "EMR", "DRG", "DIP", "APP",
           "人工智能", "智能", "数据", "平台", "系统", "接口", "网络", "云"]
EQUIP = ["设备", "器械", "耗材", "试剂", "药品", "疫苗", "医用", "影像", "检验",
         "放射", "超声", "内镜", "心电", "监护", "核磁", "CT", "DR", "手术", "药房"]
NEGATIVE = ["保安", "派出所", "公安", "物业", "食堂", "学校", "学院", "大学", "监狱",
            "法院", "检察院", "税务", "环卫", "绿化", "道路", "公交", "地铁", "公园",
            "景区", "体育", "图书", "档案", "保险", "银行", "律师", "法律", "印刷",
            "车辆", "加油", "街道", "镇", "村"]

TAG_RE = re.compile(r"^\[[^\]]*\]")


def get_args():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--start_date", type=str, default=now,
                        help="只采集该日期及之后发布的公告")
    parser.add_argument("--max_pages", type=int, default=2,
                        help="每个栏目最多翻几页")
    return parser.parse_args()


def classify(title):
    """命中医疗卫生机构词才算相关；返回 (类型, 关键词)。"""
    org = [k for k in MED_ORG if k in title]
    if not org:
        weak = [k for k in WEAK_ORG if k in title]
        if not weak or any(k in title for k in NEGATIVE):
            return None, None
        org = weak
    if not org:
        return None, None
    dig = [k for k in DIGITAL if k in title]
    equip = [k for k in EQUIP if k in title]
    if dig:
        return "医卫数智", ",".join(list(dict.fromkeys(org + dig))[:6])
    if equip:
        return "医卫设备", ",".join(list(dict.fromkeys(org + equip))[:6])
    return "医卫其他", ",".join(list(dict.fromkeys(org))[:6])


def clean_title(text):
    text = TAG_RE.sub("", (text or "").strip())
    return re.sub(r"\s+", " ", text).replace("...", "").strip()


def parse_list(html, page_url):
    """返回 [(标题, 日期, 绝对链接)]。列表项：<li><a>标题</a><span class=datetime>日期</span></li>"""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for a in soup.select("li a[href]"):
        href = a.get("href") or ""
        if not re.search(r"/20\d{2}/\d{2}/[0-9a-f]{8,}\.htm", href):
            continue
        span = a.find_next_sibling("span", class_="datetime") or a.parent.select_one("span.datetime")
        date = span.get_text(strip=True) if span else ""
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date or ""):
            continue
        if href.startswith("//"):
            href = "http:" + href
        elif href.startswith("/"):
            href = BASE + href
        items.append((clean_title(a.get_text(" ", strip=True)), date, href))
    return items


def grab(pattern, text, flags=0):
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else ""


def parse_detail(html, list_title, list_date):
    soup = BeautifulSoup(html, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    # 列表页标题会被截断成“…”，详情页 <title> 是完整标题
    title = clean_title(soup.title.get_text(strip=True)) if soup.title else ""
    title = title if len(title) >= 8 else list_title
    supplier = grab(r"中标成交供应商名称[：:]\s*([^\s，,；;]{2,60})", text) or \
        grab(r"(?:成交|中标)供应商名称[：:]\s*([^\s，,；;]{2,60})", text)
    amount = grab(r"总中标成交金额[：:]\s*([\d.]+\s*万元)", text) or \
        grab(r"中标金额[：:]\s*([\d.]+\s*万元)", text) or \
        grab(r"(?:预算|最高限价)金额[：:]\s*([\d.]+\s*万元)", text)
    buyer = grab(r"采购人名称[：:]\s*([^\s，,；;]{2,50})", text)
    if not buyer:
        candidate = grab(r"采购单位[：:]\s*([^\s，,；;]{2,50})", text)
        buyer = candidate if candidate and "名单" not in candidate else ""
    return {
        "标题": title,
        "项目编号": grab(r"项目编号[：:]\s*([^\s，,；;]{4,60})", text),
        "采购人": buyer,
        "中标供应商": supplier,
        "金额": amount,
        "发布日期": list_date,
    }


def get_content(start_date=now, max_pages=2):
    rows, detail_rows, failures = [], [], []
    seen = set()
    for channel, template in CHANNELS:
        stop = False
        for page in range(1, max_pages + 1):
            if stop:
                break
            url = BASE + (template % page)
            try:
                status, html = fetch(url)
            except FetchError as exc:
                failures.append({"栏目": channel, "url": url, "阶段": "列表", "原因": str(exc)})
                logger.error(f"{channel} 第{page}页取页失败：{exc}")
                break
            if status != 200:
                failures.append({"栏目": channel, "url": url, "阶段": "列表",
                                 "原因": f"HTTP {status}"})
                break
            items = parse_list(html, url)
            if not items:
                logger.info(f"{channel} 第{page}页无有效列表项，停止翻页")
                break
            fresh = [row for row in items if row[1] >= start_date]
            if not fresh:
                logger.info(f"{channel} 第{page}页全部早于 {start_date}，停止翻页")
                break
            for title, date, href in fresh:
                kind, keywords = classify(title)
                if not kind or href in seen:
                    continue
                seen.add(href)
                record = {"来源": GOVERMENT, "栏目": channel, "类型": kind,
                          "关键词": keywords, "标题": title, "日期": date, "链接": href}
                try:
                    dstatus, dhtml = fetch(href)
                    if dstatus == 200:
                        record.update(parse_detail(dhtml, title, date))
                    else:
                        record["详情状态"] = f"HTTP {dstatus}"
                except FetchError as exc:
                    record["详情状态"] = f"详情取页失败：{exc}"
                    failures.append({"栏目": channel, "url": href, "阶段": "详情", "原因": str(exc)})
                detail_rows.append(record)
                rows.append(f"{GOVERMENT}\t{kind}\t{record['标题']}\t{date}\t{href}\n")
                logger.info(f"{kind}\t{date}\t{record['标题'][:40]}")
                time.sleep(sleep_time)

    write_file("".join(rows), now, GOVERMENT, REGION)
    write_sidecar(detail_rows, failures)
    logger.info(f"{GOVERMENT} 命中 {len(detail_rows)} 条，失败 {len(failures)} 项")


def write_sidecar(detail_rows, failures):
    folder = Path(f"files/{year_month}/{now}/{REGION}")
    folder.mkdir(parents=True, exist_ok=True)
    payload = {"来源": GOVERMENT, "采集时间": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "入口": BASE, "ua": USER_AGENT,
               "记录数": len(detail_rows), "失败数": len(failures),
               "记录": detail_rows, "失败": failures}
    (folder / f"{GOVERMENT}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    args = get_args()
    current = os.path.splitext(os.path.basename(__file__))[0]
    logger.info(f"{'-' * 20}{current} 开始抓取{'-' * 20}")
    attempts, max_attempts = 0, 3
    while attempts < max_attempts:
        try:
            get_content(args.start_date, args.max_pages)
            break
        except Exception as exc:  # 保持本库约定：脚本自身不因异常使调用方失败
            attempts += 1
            logger.error(f"{exc}")
            time.sleep(2)
            if attempts == max_attempts:
                logger.error("已达到最大尝试次数，程序终止。")
            else:
                logger.info(f"当前重试次数{attempts}...")
    logger.info(f"{'-' * 20}{current} 抓取完成{'-' * 20}\n\n")
