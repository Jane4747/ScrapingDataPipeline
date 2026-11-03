# -*- coding: utf-8 -*-
"""校验机构官网 URL 的实际可达性，结果回写进联系信息文件。

注意：返回非 200 **不等于** 域名错。医院站点普遍有 WAF/反爬（412/403）、
自定义证书（SSL 握手失败）、或仅允许浏览器访问。所以这里只记录"机器校验结果"，
作为交付前的人工复核线索，绝不据此删除或改写域名——域名的依据始终是官方原文。

用法：
  python scripts/verify_institution_urls.py --contact configs/institution_contact_20261101.json
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
# 老站点常只支持旧 TLS，放宽套件
try:
    CTX.set_ciphers("DEFAULT@SECLEVEL=1")
except Exception:
    pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 这些返回码说明站点有响应但拒绝自动化访问，通常不是域名错误
SOFT_BLOCK = {401, 403, 405, 412, 429, 458, 422, 400, 202}


def classify(code: int, err: str) -> str:
    if code == 200:
        return "可达（200）"
    if code in SOFT_BLOCK:
        return f"站点响应但拒绝自动访问（HTTP {code}）——多为反爬，域名本身未证伪"
    if code:
        return f"响应异常（HTTP {code}）"
    if "SSL" in err or "certificate" in err.lower():
        return "SSL/TLS 握手失败——站点证书配置问题，域名本身未证伪"
    if "Tunnel" in err or "timed out" in err or "Connection" in err:
        return "本机网络未能连通（超时/隧道失败）——未证伪，需换环境复核"
    return f"未能连接（{err[:40]}）"


def probe(url: str):
    for cand in (url, url.rstrip("/")):
        try:
            req = urllib.request.Request(cand, headers={"User-Agent": UA,
                                                        "Accept": "text/html"})
            with urllib.request.urlopen(req, timeout=15, context=CTX) as r:
                body = r.read(80000).decode("utf-8", "ignore")
                m = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
                return r.status, (m.group(1).strip() if m else "")
        except urllib.error.HTTPError as e:
            return e.code, ""
        except Exception as e:
            err = str(e)
    return 0, err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--contact", required=True)
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    p = Path(args.contact)
    data = json.loads(p.read_text(encoding="utf-8"))
    targets = [r for r in data["rows"] if r.get("官网")]
    print(f"待校验 {len(targets)} 条官网")

    def work(r):
        code, title = probe(r["官网"])
        return r, code, title

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for r, code, title in ex.map(work, targets):
            r["链接校验"] = classify(code, "")
            r["HTTP状态码"] = code
            r["首页title"] = title[:80]

    ok = sum(1 for r in targets if r.get("HTTP状态码") == 200)
    soft = sum(1 for r in targets
               if r.get("HTTP状态码") in SOFT_BLOCK)
    print(json.dumps({
        "官网总数": len(targets),
        "机器可达(200)": ok,
        "站点拒绝自动访问(多为反爬)": soft,
        "其余未连通": len(targets) - ok - soft,
    }, ensure_ascii=False, indent=2))

    data.setdefault("meta", {})["链接校验"] = {
        "校验时间": __import__("datetime").datetime.now().astimezone()
                    .isoformat(timespec="seconds"),
        "官网总数": len(targets),
        "机器可达(200)": ok,
        "站点拒绝自动访问": soft,
        "其余未连通": len(targets) - ok - soft,
        "说明": ("非 200 不等于域名错误。医院站点普遍部署 WAF/反爬或使用自签证书；"
                 "本校验仅供人工复核参考，域名的依据始终是官方页面原文。"),
    }
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已回写 -> {args.contact}")


if __name__ == "__main__":
    main()
