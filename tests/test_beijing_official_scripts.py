# -*- coding:utf-8 -*-
"""北京两条官方线（政采网、公共资源交易平台）站点脚本的离线回归。

只测解析与筛选口径，不联网：样本取自 2026-10-27 实际抓到的页面结构。
从本仓库跟踪的站点脚本加载；日志/输出依赖使用测试夹具，无需第三方目录。
"""
import unittest
from site_script_fixture import load_site_script

_CCGP = None
_GGZY = None

CCGP_LIST = """
<ul>
<li><a href="//www.ccgp-beijing.gov.cn/xxgg/sjxxgg/zbggs/2026/10/7b0c1fa444254c6490f88ac0f6ad3ce6.htm" target="_parent">[公开]海淀医院信息化升级改造项目中标公告</a><span class="datetime" style="float: right">2026-10-27</span></li>
<li><a href="//www.ccgp-beijing.gov.cn/xxgg/sjxxgg/zbggs/2026/10/6e9c14eed8774ef780c1bdb73605573f.htm" target="_parent">北京市公安局朝阳分局2026年能力提升设备采购项目中标公告</a><span class="datetime" style="float: right">2026-10-27</span></li>
</ul>
"""

CCGP_DETAIL = """
<html><head><title>[公开]海淀医院信息化升级改造项目中标公告</title></head><body>
<div>当前位置 ： 首页 -&gt; 信息公告 -&gt; 市级信息公告 -&gt; 中标公告</div>
<div>一、项目编号：11010826210200059969-XM001 二、项目名称：海淀医院信息化升级改造项目
三、中标（成交）信息 总中标成交金额：1169.582022 万元（人民币）
中标成交供应商名称：北京鑫博腾飞科技有限公司 中标成交供应商地址：北京市海淀区某路1号</div>
</body></html>
"""

GGZY_LIST = """
<ul>
<li><a target="_blank" href="/jyxxcggg/20261027/5763638.html" title="市属医院2026年医用设备带量采购放射组第二批次（国产部分）第1包至第4包公开招标公告"><span></span></a><div class="list-times1">2026-10-27</div></li>
<li><a target="_blank" href="/jyxxcggg/20261027/5763679.html" title="2026年潘家园街道十五五街区控规编制服务项目竞争性磋商公告"><span></span></a><div class="list-times1">2026-10-27</div></li>
</ul>
"""

GGZY_DETAIL = """
<html><body>
<div class="div-title">市属医院2026年医用设备带量采购放射组第二批次（国产部分）第1包至第4包公开招标公告 交易项目编号：S110000C005114400001</div>
<div class="div-title2">发布时间：2026-10-27 &nbsp;&nbsp;浏览次数： 0</div>
<div>采购人信息 名 称：北京市医院管理中心(本级) 预算金额：11182 万元（人民币）</div>
</body></html>
"""


def setUpModule():
    global _CCGP, _GGZY
    _CCGP = load_site_script("1600004.北京市政府采购网-医疗中标.py", "beijing_ccgp_spider")
    _GGZY = load_site_script("1600005.北京公共资源交易平台-医疗中标.py", "beijing_ggzy_spider")


class BeijingCcgpScriptTest(unittest.TestCase):
    def test_list_items_use_http_entry_and_keep_date(self):
        # 该站 443 不可达、80 可达，所以协议相对链接必须落回 http
        items = _CCGP.parse_list(CCGP_LIST, "http://www.ccgp-beijing.gov.cn/xxgg/x.htm")
        self.assertEqual(len(items), 2)
        title, date, href = items[0]
        self.assertTrue(href.startswith("http://www.ccgp-beijing.gov.cn/"))
        self.assertEqual(date, "2026-10-27")
        self.assertTrue(title.startswith("海淀医院"))

    def test_bracket_prefix_removed(self):
        items = _CCGP.parse_list(CCGP_LIST, "http://www.ccgp-beijing.gov.cn/xxgg/x.htm")
        self.assertFalse(items[0][0].startswith("[公开]"))

    def test_digital_medical_classified(self):
        kind, keywords = _CCGP.classify("海淀医院信息化升级改造项目中标公告")
        self.assertEqual(kind, "医卫数智")
        self.assertIn("医院", keywords)

    def test_equipment_medical_classified(self):
        kind, _ = _CCGP.classify("市属医院2026年医用设备带量采购放射组第二批次公开招标公告")
        self.assertEqual(kind, "医卫设备")

    def test_non_medical_title_excluded(self):
        self.assertEqual(_CCGP.classify("北京市公安局朝阳分局2026年能力提升设备采购项目中标公告"), (None, None))

    def test_strong_organ_signal_beats_negative_word(self):
        # "街道"在排除词里，但"社区卫生服务中心"是强医卫信号，不能误杀
        kind, _ = _CCGP.classify("某街道社区卫生服务中心医疗设备采购项目公开招标公告")
        self.assertIsNotNone(kind)

    def test_detail_fields_extracted(self):
        detail = _CCGP.parse_detail(CCGP_DETAIL, "列表标题", "2026-10-27")
        self.assertEqual(detail["标题"], "海淀医院信息化升级改造项目中标公告")
        self.assertEqual(detail["项目编号"], "11010826210200059969-XM001")
        self.assertEqual(detail["中标供应商"], "北京鑫博腾飞科技有限公司")
        self.assertIn("1169.582022", detail["金额"])


class BeijingGgzyScriptTest(unittest.TestCase):
    def test_list_items_parsed_from_static_html(self):
        items = _GGZY.parse_list(GGZY_LIST)
        self.assertEqual(len(items), 2)
        title, date, href = items[0]
        self.assertEqual(date, "2026-10-27")
        self.assertTrue(href.startswith("https://ggzyfw.beijing.gov.cn/jyxxcggg/"))

    def test_pagination_url_pattern(self):
        self.assertEqual(_GGZY.page_url("/jyxxcggg/index.html", 1),
                         "https://ggzyfw.beijing.gov.cn/jyxxcggg/index.html")
        self.assertEqual(_GGZY.page_url("/jyxxcggg/index.html", 2),
                         "https://ggzyfw.beijing.gov.cn/jyxxcggg/index_2.html")

    def test_detail_title_strips_project_code(self):
        detail = _GGZY.parse_detail(GGZY_DETAIL, "列表标题", "2026-10-27")
        self.assertTrue(detail["标题"].endswith("公开招标公告"))
        self.assertNotIn("交易项目编号", detail["标题"])
        self.assertEqual(detail["交易项目编号"], "S110000C005114400001")
        self.assertEqual(detail["采购人"], "北京市医院管理中心(本级)")
        self.assertIn("11182", detail["金额"])

    def test_non_medical_skipped(self):
        self.assertEqual(_GGZY.classify("2026年潘家园街道十五五街区控规编制服务项目竞争性磋商公告"), (None, None))


if __name__ == "__main__":
    unittest.main()
