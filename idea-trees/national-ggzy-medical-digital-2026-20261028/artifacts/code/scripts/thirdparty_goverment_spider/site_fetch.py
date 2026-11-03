# -*- coding: utf-8 -*-
"""共享取页工具（新增站点脚本使用）。

为什么需要它：部分政府站点部署了国密（SM2）TLS 或证书链不完整，Python 的
OpenSSL 握手会直接失败（SSL: BAD_ECPOINT / unable to get local issuer
certificate），而 Windows 自带的系统 TLS 栈（Schannel）可以正常握手并完成校验。

取页顺序：先 requests；仅在 TLS/连接类失败时改用系统 curl。
**任何情况下都不关闭证书校验**：curl 退出码 60（证书不可信）按失败抛出，
不返回页面内容。也不设置伪造浏览器 UA，统一使用自报标识。
"""
import os
import shutil
import subprocess
import tempfile
import time
import random

import requests

USER_AGENT = "CAICTMedicalResearchBot/1.0 (public-source research)"
MIN_INTERVAL = 1.2          # 同一站点两次请求的最小间隔（秒）
# 本机环境注入了本地代理，代理对部分政务站点返回 502/CONNECT tunnel failed。
# 这些政务站点可直连，因此默认绕过代理；需要走代理时设 SITE_FETCH_USE_PROXY=1。
USE_PROXY = os.environ.get("SITE_FETCH_USE_PROXY") == "1"
_TIMEOUT_EXIT = (28,)
_TLS_EXIT = (35, 51, 53, 54, 58, 59, 60, 64, 66, 77, 80, 82, 83, 90, 91)

_last_hit = {}


class FetchError(RuntimeError):
    """取页失败。message 里保留可追溯的原始原因。"""


def _session():
    session = requests.Session()
    session.trust_env = USE_PROXY
    return session


def _throttle(url):
    host = url.split("/")[2] if "//" in url else url
    last = _last_hit.get(host)
    if last is not None:
        wait = MIN_INTERVAL - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait + random.uniform(0, 0.4))
    _last_hit[host] = time.monotonic()


def _curl_text(url, timeout):
    curl = shutil.which("curl")
    if not curl:
        raise FetchError("TLS 不兼容且本机没有 curl，无法改用系统 TLS 栈")
    handle, path = tempfile.mkstemp(suffix=".html")
    os.close(handle)
    try:
        command = [curl, "-sS", "--max-time", str(int(timeout)), "-A", USER_AGENT,
                   "-o", path, "-w", "%{http_code}"]
        if not USE_PROXY:
            command += ["--noproxy", "*"]
        command.append(url)
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout + 10)
        if done.returncode in _TLS_EXIT:
            raise FetchError(f"系统 TLS 校验证书失败(curl={done.returncode}): {done.stderr.strip()[:160]}")
        if done.returncode in _TIMEOUT_EXIT:
            raise FetchError(f"请求超时(curl=28)超过{int(timeout)}秒")
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


def fetch(url, timeout=25, retries=1):
    """返回 (status_code, text)。失败抛 FetchError，错误信息保留原因。"""
    headers = {"User-Agent": USER_AGENT,
               "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"}
    session = _session()
    problem = None
    for attempt in range(retries + 1):
        _throttle(url)
        try:
            response = session.get(url, headers=headers, timeout=timeout)
            return response.status_code, response.content.decode("utf-8-sig", "replace")
        except requests.exceptions.SSLError as exc:
            problem = f"TLS 握手失败(requests): {str(exc)[:140]}"
            return _curl_text(url, timeout)          # 国密/缺链站点改用系统 TLS
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            problem = f"连接失败(requests): {str(exc)[:140]}"
            if attempt < retries:
                time.sleep(1 + attempt)
                continue
            return _curl_text(url, timeout)          # 连接被重置或端口被拦时再试系统栈
    raise FetchError(problem or "取页失败")
