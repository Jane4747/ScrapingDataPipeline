# -*- coding:utf-8 -*-
"""全国公共资源交易平台（www.ggzy.gov.cn）医卫类交易公告。

入口说明（2026-10-28 实测，想法树 national-ggzy-medical-digital）：
- 旧入口 deal.ggzy.gov.cn 已停（全局 NXDOMAIN），新前端为 https://www.ggzy.gov.cn，
  列表页 /deal/dealList.html 是 Vue 壳，数据来自 POST 接口。
- 接口契约取自前端 JS（dealList.html / history/dealList.html 内联脚本）：
    POST /information/pubTradingInfo/getTradList     近一年数据（本机网络实测 404）
    POST /his/information/pubTradingInfo/getTradList 历史数据（可达，但日期窗校验
      返回 code:400 "结束时间错误"，早于近一年下限的窗口被前置 WAF 以 404 静态页拦截）
  表单参数：DEAL_CLASSIFY(02=政府采购,23=药品采购)、TIMEBEGIN/TIMEEND(yyyy-MM-dd,
  前端限一年内)、FINDTXT(关键词)、PAGENUMBER。
- 响应约定（前端 JS）：code 200 正常（data.records/total/pages）；829 需要验证码
  （/information/captcha 获取，X-Pass-Token 头传 "token#code"，本脚本不做验证码识
  别，记录后停止该检索式）；804 提示细化条件；800 过频；801/400 参数或服务错误。
- WAF：API 路径间歇性返回 404 静态页（"网页暂时无法访问"），与 UA 无关、请求过密
  时更频繁；脚本将其按失败留痕，并保持 ≥NATIONAL_MIN_INTERVAL 秒的请求间隔。
- robots.txt 未测试通过（站点对 API 路径返回 404 静态页）；UA 沿用库内自报标识，
  不伪装浏览器；证书始终校验；默认直连（SITE_FETCH_USE_PROXY=1 可走代理）。

输出：
- 5 列 TSV（部门名称/类型/标题/日期/链接）：files/<年月>/<日期>/国家级/<来源>.txt
- 同名 .json 旁证：解析后的记录、失败明细、每页原始响应摘要（供核查接口真实行为）
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.extend(['.', '..'])

from utils import logger, now, year_month, write_file, sleep_time  # noqa: E402
from site_fetch import FetchError, USER_AGENT  # noqa: E402

GOVERMENT = "全国公共资源交易平台-医卫公告"
REGION = "国家级"
BASE = "https://www.ggzy.gov.cn"

# 列表接口：近一年在前端文档里是 /information/...，本网络 404；历史线 /his/... 可达。
ENDPOINTS = [
    ("current", "/information/pubTradingInfo/getTradList"),
    ("history", "/his/information/pubTradingInfo/getTradList"),
]
# DEAL_CLASSIFY：02 政府采购、23 药品采购（其余为工程/土地/矿产/产权等，与本主题无关）
CHANNELS = [
    ("政府采购", "02"),
    ("药品采购", "23"),
]

NATIONAL_MIN_INTERVAL = 3.0   # 全国平台 API 对请求频率敏感，比库内 1.2s 更保守
PAGE_SIZE_HINT = 20           # 前端每页条数（用于判断翻页收益，非接口参数）

MED_ORG = ["医院", "医疗", "卫生院", "卫生服务", "卫生健", "卫生", "疾控", "医保",
           "中医", "妇幼", "保健", "急救", "血液", "康复", "门诊", "诊所", "医学",
           "儿科", "妇产", "肿瘤", "口腔", "精神卫生", "计划生育"]
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

# 默认检索词：FINDTXT 单次只支持一个词，逐词检索后本地再按医卫/数字化口径过滤
DEFAULT_KEYWORDS = ["医院", "卫生", "医保", "妇幼", "疾控", "卫生院"]

_last_hit = {"at": 0.0}


def get_args():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--start_date", type=str, default=now,
                        help="只保留发布日期不早于该值的公告（yyyy-MM-dd）")
    parser.add_argument("--end_date", type=str, default="",
                        help="窗口结束日期（默认今天）；接口限制窗口须在近一年内")
    parser.add_argument("--max_pages", type=int, default=2,
                        help="每个检索式最多翻几页")
    parser.add_argument("--keywords", type=str, default="",
                        help="逗号分隔的 FINDTXT 检索词，覆盖默认词表")
    return parser.parse_args()


def classify(title):
    org = [k for k in MED_ORG if k in title]
    if not org:
        weak = [k for k in WEAK_ORG if k in title]
        if not weak or any(k in title for k in NEGATIVE):
            return None, None
        org = weak
    dig = [k for k in DIGITAL if k in title]
    equip = [k for k in EQUIP if k in title]
    if dig:
        return "医卫数智", ",".join(list(dict.fromkeys(org + dig))[:6])
    if equip:
        return "医卫设备", ",".join(list(dict.fromkeys(org + equip))[:6])
    return "医卫其他", ",".join(list(dict.fromkeys(org))[:6])


def build_form(classify_id, keyword, start_date, end_date, page):
    form = {
        "DEAL_CLASSIFY": classify_id,
        "TIMEBEGIN": start_date,
        "TIMEEND": end_date,
        "FINDTXT": keyword,
        "PAGENUMBER": str(page),
    }
    return form


def _throttle():
    wait = NATIONAL_MIN_INTERVAL - (time.monotonic() - _last_hit["at"])
    if wait > 0:
        time.sleep(wait)
    _last_hit["at"] = time.monotonic()


def _curl_post(url, form, timeout):
    curl = shutil_which()
    if not curl:
        raise FetchError("本机没有 curl，无法改用系统 TLS 栈")
    handle, path = tempfile.mkstemp(suffix=".json")
    os.close(handle)
    try:
        fields = []
        for key, value in form.items():
            fields += ["--data-urlencode", f"{key}={value}"]
        command = [curl, "-sS", "--noproxy", "*", "--max-time", str(int(timeout)),
                   "-A", USER_AGENT,
                   "-H", "Content-Type: application/x-www-form-urlencoded",
                   "-H", f"Origin: {BASE}",
                   "-H", f"Referer: {BASE}/deal/dealList.html",
                   "-o", path, "-w", "%{http_code}"] + fields + [url]
        done = subprocess.run(command, capture_output=True, text=True,
                              timeout=timeout + 10)
        if done.returncode != 0:
            raise FetchError(f"curl 取页失败({done.returncode}): {done.stderr.strip()[:160]}")
        with open(path, "rb") as stream:
            body = stream.read()
        return int(done.stdout.strip() or 0), body.decode("utf-8-sig", "replace")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def shutil_which():
    import shutil
    return shutil.which("curl")


def post_json(url, form, timeout=25):
    """POST 表单并返回 (status, text)。TLS/连接失败时改用系统 curl，证书始终校验。"""
    import requests
    _throttle()
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": BASE,
        "Referer": f"{BASE}/deal/dealList.html",
        "X-Pass-Token": "",
    }
    try:
        response = requests.post(url, data=form, headers=headers, timeout=timeout)
        return response.status_code, response.content.decode("utf-8-sig", "replace")
    except Exception:
        return _curl_post(url, form, timeout)


def parse_api_response(text):
    """把接口响应解析为 (kind, payload)。

    kind: "json" | "html"（WAF/404 静态页）| "other"
    json payload 是 dict；html payload 是说明字符串。
    """
    stripped = (text or "").lstrip()
    if stripped.startswith("<"):
        return "html", "非 JSON 响应（疑为 WAF/404 静态页「网页暂时无法访问」）"
    try:
        return "json", json.loads(text)
    except (ValueError, TypeError):
        return "other", "无法解析为 JSON"


_RECORD_URL_KEYS = ("url", "link", "href")
_RECORD_TITLE_KEYS = ("title", "name", "dealname")
_RECORD_DATE_KEYS = ("date", "time")


def _pick(record, keys):
    for key in keys:
        for name, value in record.items():
            if key in str(name).lower() and isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def parse_records(data):
    """从接口 JSON 中提取 (rows, meta)。rows: [dict(标题/日期/链接/省/平台/原始)]。"""
    payload = data.get("data") if isinstance(data, dict) else None
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return [], {"total": None, "pages": None, "current": None}
    rows = []
    for item in records:
        if not isinstance(item, dict):
            continue
        title = _pick(item, _RECORD_TITLE_KEYS)
        link = _pick(item, _RECORD_URL_KEYS)
        date = _pick(item, _RECORD_DATE_KEYS)
        date_match = re.search(r"\d{4}-\d{2}-\d{2}", date or "")
        rows.append({
            "标题": re.sub(r"\s+", " ", title),
            "日期": date_match.group(0) if date_match else "",
            "链接": link if link.startswith("http") else (BASE + link if link else ""),
            "省份": str(item.get("PROVINCE", "") or item.get("DEAL_PROVINCE", "") or ""),
            "平台": str(item.get("PLATFORMNAME", "") or item.get("PLATFORM", "") or ""),
            "原始": item,
        })
    meta = {
        "total": payload.get("total") if isinstance(payload, dict) else None,
        "pages": payload.get("pages") if isinstance(payload, dict) else None,
        "current": payload.get("current") if isinstance(payload, dict) else None,
    }
    return rows, meta


def grab(pattern, text):
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def parse_detail(html, list_title, list_date):
    soup_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    return {
        "交易项目编号": grab(r"交易项目编号[：:]\s*([A-Z0-9]{6,40})", soup_text) or
        grab(r"项目编号[：:]\s*([A-Z0-9]{6,40})", soup_text),
        "采购人": grab(r"采购人信息\s*名\s*称[：:]\s*([^\s，,；;]{2,50})", soup_text),
        "中标供应商": grab(r"中标(?:成交)?供应商名称[：:]\s*([^\s，,；;]{2,60})", soup_text) or
        grab(r"成交供应商名称[：:]\s*([^\s，,；;]{2,60})", soup_text),
        "金额": grab(r"(?:中标|成交)金额[：:]\s*([\d.]+\s*万元)", soup_text) or
        grab(r"预算金额[：:]\s*([\d.]+\s*万元)", soup_text),
        "发布日期": grab(r"发布时间[：:]\s*(\d{4}-\d{2}-\d{2})", soup_text) or list_date,
    }


def query_once(endpoint_url, classify_id, keyword, start_date, end_date, page,
               failures, page_evidence):
    """单次检索：返回本页命中 rows；失败写 failures 并返回 []。"""
    form = build_form(classify_id, keyword, start_date, end_date, page)
    label = f"{keyword} 第{page}页"
    try:
        status, text = post_json(endpoint_url, form)
    except FetchError as exc:
        failures.append({"检索式": label, "url": endpoint_url, "原因": str(exc)})
        logger.error(f"{label} 取页失败：{exc}")
        return []
    kind, payload = parse_api_response(text)
    if kind != "json":
        failures.append({"检索式": label, "url": endpoint_url,
                         "原因": f"HTTP {status}：{payload}"})
        logger.error(f"{label} HTTP {status}：{payload}")
        return []
    code = payload.get("code")
    page_evidence.append({"检索式": label, "http": status, "code": code,
                          "message": payload.get("message", ""),
                          "total": (payload.get("data") or {}).get("total")
                          if isinstance(payload.get("data"), dict) else None})
    if code == 200:
        rows, meta = parse_records(payload)
        logger.info(f"{label} 命中 {len(rows)} 条（total={meta['total']}）")
        return rows
    if code == 829:
        failures.append({"检索式": label, "url": endpoint_url,
                         "原因": "接口要求验证码(code 829)；本脚本不做识别，需人工或浏览器会话"})
        logger.error(f"{label} 需要验证码，停止该检索式")
        return []
    if code == 800:
        failures.append({"检索式": label, "url": endpoint_url, "原因": "接口提示操作过频(code 800)"})
        logger.error(f"{label} 操作过频，停止该检索式")
        return []
    failures.append({"检索式": label, "url": endpoint_url,
                     "原因": f"code {code}：{payload.get('message', '')}"})
    logger.error(f"{label} code {code}：{payload.get('message', '')}")
    return []


def get_content(start_date, end_date, max_pages, keywords):
    rows, detail_rows, failures = [], [], []
    page_evidence = []
    seen = set()
    end_date = end_date or time.strftime("%Y-%m-%d")
    for endpoint_name, endpoint_path in ENDPOINTS:
        endpoint_url = BASE + endpoint_path
        endpoint_alive = False
        for channel, classify_id in CHANNELS:
            for keyword in keywords:
                for page in range(1, max_pages + 1):
                    hits = query_once(endpoint_url, classify_id, keyword,
                                      start_date, end_date, page, failures,
                                      page_evidence)
                    if not hits:
                        break
                    endpoint_alive = True
                    fresh = [row for row in hits
                             if row["标题"] and row["日期"] >= start_date
                             and row["链接"] not in seen]
                    for row in fresh:
                        kind, kw = classify(row["标题"])
                        if not kind:
                            continue
                        seen.add(row["链接"])
                        record = {"来源": GOVERMENT, "栏目": channel,
                                  "检索词": keyword, "接口": endpoint_name,
                                  "类型": kind, "关键词": kw,
                                  "标题": row["标题"], "日期": row["日期"],
                                  "链接": row["链接"], "省份": row["省份"],
                                  "平台": row["平台"]}
                        detail_rows.append(record)
                        rows.append(f"{GOVERMENT}\t{kind}\t{record['标题']}\t{record['日期']}\t{record['链接']}\n")
                        logger.info(f"{kind}\t{record['日期']}\t{record['标题'][:40]}")
                    if page >= max_pages:
                        break
                    time.sleep(sleep_time)
        logger.info(f"接口 {endpoint_name}（{endpoint_url}）"
                    f"{'有可用响应' if endpoint_alive else '未获得任何 code=200 响应'}")
    write_file("".join(rows), now, GOVERMENT, REGION)
    write_sidecar(detail_rows, failures, page_evidence, start_date, end_date,
                  keywords, max_pages)
    logger.info(f"{GOVERMENT} 命中 {len(detail_rows)} 条，失败 {len(failures)} 项")


def write_sidecar(detail_rows, failures, page_evidence, start_date, end_date,
                  keywords, max_pages):
    folder = Path(f"files/{year_month}/{now}/{REGION}")
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "来源": GOVERMENT,
        "采集时间": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "入口": BASE,
        "接口": [{"name": name, "path": path} for name, path in ENDPOINTS],
        "窗口": {"begin": start_date, "end": end_date},
        "检索词": keywords,
        "max_pages": max_pages,
        "ua": USER_AGENT,
        "记录数": len(detail_rows),
        "失败数": len(failures),
        "记录": detail_rows,
        "失败": failures,
        "页面证据": page_evidence,
    }
    (folder / f"{GOVERMENT}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    args = get_args()
    keywords = ([k.strip() for k in args.keywords.split(",") if k.strip()]
                if args.keywords else list(DEFAULT_KEYWORDS))
    current = os.path.splitext(os.path.basename(__file__))[0]
    logger.info(f"{'-' * 20}{current} 开始抓取{'-' * 20}")
    attempts, max_attempts = 0, 3
    while attempts < max_attempts:
        try:
            get_content(args.start_date, args.end_date, args.max_pages, keywords)
            break
        except Exception as exc:  # 库内约定：脚本自身不因异常使调用方失败
            attempts += 1
            logger.error(f"{exc}")
            time.sleep(2)
            if attempts == max_attempts:
                logger.error("已达到最大尝试次数，程序终止。")
            else:
                logger.info(f"当前重试次数{attempts}...")
    logger.info(f"{'-' * 20}{current} 抓取完成{'-' * 20}\n\n")
