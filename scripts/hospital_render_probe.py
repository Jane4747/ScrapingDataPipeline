"""One-shot render probe for the 4 JS-rendering-needed hospital sites.

Uses the same crawl4ai + system Chrome pattern as the gtbjah tree
(BrowserConfig chrome_channel='chrome', CrawlerRunConfig wait_for/delay,
save rendered html). Checks whether hospital_batch_crawl.extract_items can
parse the rendered pages, and reports pagination/detail link availability.
"""
import asyncio, json, os, sys
from pathlib import Path

ROOT = Path(r'E:\CAICTBigData\coding')
sys.path.insert(0, str(ROOT / 'scripts'))
import hospital_batch_crawl as hbc  # noqa: E402

OUT = ROOT / 'outputs/hospital-site-crawl-90-20261028/render-probe'
OUT.mkdir(parents=True, exist_ok=True)
(OUT / 'runtime-temp').mkdir(exist_ok=True)
(OUT / 'runtime-cache').mkdir(exist_ok=True)
os.environ['TEMP'] = os.environ['TMP'] = str(OUT / 'runtime-temp')
os.environ['CRAWL4AI_NO_CLOUD_NOTICE'] = '1'

SITES = {
    'C0003': 'https://zbcg.301hospital.com.cn/admin-portal-index.html',
    'C0067': 'https://www.mtgqyy.cn/index.php?c=article&a=type&tid=77',
    'C0077': 'https://www.pkuih.edu.cn/news-announcement/hospital-announcement.html',
    'C0082': 'http://www.gamhnq.cn/common/index.aspx?nodeid=81',
}


async def main():
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
    OUT.mkdir(parents=True, exist_ok=True)
    report = []
    async with AsyncWebCrawler(config=BrowserConfig(
            chrome_channel='chrome', headless=True, ignore_https_errors=False,
            verbose=False, viewport_width=1440, viewport_height=1000),
            base_directory=str(OUT / 'runtime-cache')) as crawler:
        for tid, url in SITES.items():
            r = await crawler.arun(url=url, config=CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS, wait_for='css:body',
                wait_for_timeout=25000, delay_before_return_html=4,
                page_timeout=60000, verbose=False))
            html = r.html or ''
            items = hbc.extract_items(html, r.url)
            pgs = hbc.find_list_pages(html, r.url, {r.url})
            iframes = html.lower().count('<iframe')
            rec = {'task_id': tid, 'success': r.success, 'status': r.status_code,
                   'error': r.error_message, 'final_url': r.url,
                   'html_len': len(html), 'iframes': iframes,
                   'items': len(items), 'sample': [i['title'][:30] for i in items[:5]],
                   'pagination_links': pgs[:4]}
            report.append(rec)
            (OUT / f'{tid}.html').write_text(html, encoding='utf-8', errors='ignore')
            print(json.dumps(rec, ensure_ascii=False), flush=True)
    (OUT / 'probe_report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

asyncio.run(main())
