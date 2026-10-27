import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOS = Path(os.environ.get("SCRAPING_REPOS", str(ROOT / "repos"))).expanduser().resolve()
OUTPUTS = ROOT / "outputs"
TREES = ROOT / "idea-trees"
PYTHON = Path(os.environ.get("SCRAPING_PYTHON", sys.executable)).expanduser()
ENV_PREFIX = PYTHON.parent


def runtime_env() -> dict:
    """conda 的 OpenSSL 等 DLL 在 Library\\bin，直接调用 python.exe 时要放进 PATH。"""
    env = os.environ.copy()
    prefix = str(ENV_PREFIX)
    leading = os.pathsep.join(
        [
            prefix,
            str(ENV_PREFIX / "Library" / "bin"),
            str(ENV_PREFIX / "Library" / "usr" / "bin"),
            str(ENV_PREFIX / "Scripts"),
        ]
    )
    env["PATH"] = leading + os.pathsep + env.get("PATH", "")
    if (ENV_PREFIX / "conda-meta").is_dir():
        env["CONDA_PREFIX"] = prefix
    env["PLAYWRIGHT_BROWSERS_PATH"] = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".playwright-browsers"))
    return env

TOOLS = {
    "goverment_spider": {
        "repo": "zou-you/goverment_spider",
        "path": REPOS / "goverment_spider",
        "use": "政府政策监测。按关键词、标题规则和日期抓取，汇总 Excel。",
        "needs": "主题对应的部门或站点脚本，以及交付字段。未指定站点时不会把 140 多个站点全部跑一遍。",
        "cues": ["政策", "政府", "卫健", "医保", "药监", "公文", "通知", "条例", "部门"],
    },
    "NewsCrawler": {
        "repo": "NanmiCoder/NewsCrawler",
        "path": REPOS / "NewsCrawler",
        "use": "已知文章链接的正文提取。支持微信、头条、网易、搜狐、腾讯等。",
        "needs": "至少一条文章 URL。这个仓库不负责发现链接。",
        "cues": ["微信", "公众号", "头条", "网易", "搜狐", "腾讯", "文章链接", "正文"],
    },
    "crawl4ai": {
        "repo": "unclecode/crawl4ai",
        "path": REPOS / "crawl4ai",
        "use": "需要浏览器渲染的动态页面。CSS 或 XPath 规则提取，不调用大模型。",
        "needs": "页面 URL。要结构化字段时另给 schema JSON。",
        "cues": ["动态", "官网", "产品列表", "渲染", "javascript", "翻页", "xpath", "css"],
    },
    "feapder": {
        "repo": "Boris-code/feapder",
        "path": REPOS / "feapder",
        "use": "多来源、要断点续爬或周期调度的采集框架。",
        "needs": "已经写好的爬虫脚本路径。框架本身没有业务站点。",
        "cues": ["长期", "多来源", "断点", "调度", "周期", "feapder"],
    },
    "news-please": {
        "repo": "fhamborg/news-please",
        "path": REPOS / "news-please",
        "use": "新闻站点的标题、正文、作者、日期提取，适合 RSS 或文章链接。",
        "needs": "新闻文章 URL，或明确的来源列表。不直接解析中文政策页。",
        "cues": ["新闻", "rss", "行业动态", "媒体", "报道"],
    },
}
