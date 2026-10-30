import unittest

from pipeline.research.zycg import (
    COLUMNS,
    amount_field,
    amount_wan,
    build_row,
    carrier_type,
    classify_scope,
    customer_tag,
    is_result_notice,
    parse_detail,
    parse_search_page,
    scene_of,
    search_url,
)

LIST_HTML = """
<ul class="vT-srch-result-list-bid">
<li><a href="http://www.ccgp.gov.cn/cggg/zygg/zbgg/202610/t20261022_27546527.htm">
中国医学科学院北京协和医院负载均衡更新及高阶云节点扩容采购项目中标公告</a>
<span>2026.10.22 16:30:01
| 采购人：中国医学科学院北京协和医院
| 代理机构： 中央国家机关政府采购中心 中标公告 | 北京
|</span></li>
<li><a href="http://www.ccgp.gov.cn/cggg/zygg/gkzb/202610/t20261027_27568371.htm">
北京大学第三医院医疗信息交换基础保障平台采购项目招标公告</a>
<span>2026.10.27 10:00:00 | 采购人：北京大学第三医院 | 代理机构： 中央国家机关政府采购中心 招标公告 | 北京 |</span></li>
<li><a href="http://www.ccgp.gov.cn/cggg/zygg/cjgg/202610/t20261027_27570000.htm">
某支队食堂劳务外包采购项目成交公告</a>
<span>2026.10.27 19:00:00 | 采购人：延边边境管理支队 | 代理机构： 中央国家机关政府采购中心 成交公告 | 吉林 |</span></li>
</ul>
"""

DETAIL_HTML = """
<html><body><div class="vF_detail_content">
<p>中国医学科学院北京协和医院负载均衡更新及高阶云节点扩容采购项目中标（成交）结果公告</p>
<p>一、项目基本情况</p>
<p>1．项目编号： GC-HGX261026</p>
<p>2．项目名称： 中国医学科学院北京协和医院负载均衡更新及高阶云节点扩容采购项目</p>
<p>3．采购方式： 公开招标</p>
<p>4．预算金额： 410.000000万元</p>
<p>二、中标（成交）信息</p>
<p>供应商名称： 北京神州数码云计算有限公司</p>
<p>中标（成交）金额： 人民币400.810000 万元</p>
<p>三、主要中标（成交）标的信息</p>
<table>
<tr><td>序号</td><td>主要投标标的名称</td><td>品牌</td><td>规格型号</td><td>数量</td><td>单价（元）</td></tr>
<tr><td>1</td><td>云计算节点扩容</td><td>H3C</td><td>R4900 G6</td><td>6</td><td>333800</td></tr>
<tr><td>2</td><td>服务器负载均衡</td><td>信安世纪</td><td>APV2860</td><td>2</td><td>296500</td></tr>
</table>
<p>1．采购人信息</p>
<p>名 称：中国医学科学院北京协和医院</p>
<p>2．采购执行机构信息</p>
<p>名 称：中央国家机关政府采购中心</p>
</div></body></html>
"""


class SearchPageTest(unittest.TestCase):
    def test_parses_buyer_agent_type_and_region(self):
        items = parse_search_page(LIST_HTML)
        self.assertEqual(len(items), 3)
        first = items[0]
        self.assertEqual(first["buyer"], "中国医学科学院北京协和医院")
        self.assertEqual(first["agent"], "中央国家机关政府采购中心")
        self.assertEqual(first["notice_type"], "中标公告")
        self.assertEqual(first["region"], "北京")
        self.assertEqual(first["published_at"], "2026-10-22")

    def test_only_result_notices_kept(self):
        items = parse_search_page(LIST_HTML)
        kept = [i for i in items if is_result_notice(i["url"])]
        self.assertEqual(len(kept), 2)
        self.assertFalse(any("/gkzb/" in i["url"] for i in kept))

    def test_search_url_locks_agent_and_window(self):
        url = search_url(3, "2026-01-01", "2026-10-27")
        self.assertIn("agentName=%E4%B8%AD%E5%A4%AE", url)
        self.assertIn("page_index=3", url)
        self.assertIn("start_time=2026%3A01%3A01", url)
        self.assertIn("timeType=6", url)


class ScopeTest(unittest.TestCase):
    def test_medical_digital_kept(self):
        ok, _ = classify_scope("中国医学科学院北京协和医院负载均衡更新及高阶云节点扩容采购项目", "中国医学科学院北京协和医院")
        self.assertTrue(ok)

    def test_medical_but_non_digital_rejected(self):
        ok, reason = classify_scope("北京中医药大学东直门医院通州院区餐饮服务", "北京中医药大学东直门医院")
        self.assertFalse(ok)
        self.assertIn("非数字化", reason)

    def test_non_medical_rejected(self):
        ok, reason = classify_scope("延边边境管理支队计算机网络设备采购项目", "延边边境管理支队")
        self.assertFalse(ok)
        self.assertIn("非医卫", reason)

    def test_medical_without_digital_words_rejected(self):
        ok, reason = classify_scope("某医院医用耗材配送服务采购项目", "某医院")
        self.assertFalse(ok)


class TaggingTest(unittest.TestCase):
    def test_customer_tags(self):
        cases = {
            "中国医学科学院北京协和医院": "国家级医学科研/医疗机构",
            "北京大学第三医院": "高校附属医院",
            "北京市疾病预防控制中心": "疾控机构",
            "国家医疗保障局": "医保机构",
            "中国中医科学院广安门医院": "国家级医学科研/医疗机构",
            "北京市肛肠医院": "专科医疗机构",
            "某区妇幼保健院": "妇幼保健机构",
            "某市卫生健康委员会": "卫生行政/监管",
        }
        for buyer, expected in cases.items():
            self.assertEqual(customer_tag(buyer), expected, buyer)

    def test_carrier_type(self):
        self.assertEqual(carrier_type("中移系统集成有限公司"), "中国移动")
        self.assertEqual(carrier_type("中国电信股份有限公司北京分公司"), "中国电信")
        self.assertEqual(carrier_type("联通数字科技有限公司"), "中国联通")
        self.assertEqual(carrier_type("北京神州数码云计算有限公司"), "非运营商")

    def test_scene_priority(self):
        self.assertEqual(scene_of("云平台扩容及虚拟化节点"), "云与算力")
        self.assertEqual(scene_of("网络安全设备更新和授权扩容"), "信息安全")
        self.assertEqual(scene_of("PACS影像系统升级"), "影像与检验")
        self.assertEqual(scene_of("电子病历系统升级改造"), "电子病历与HIS")
        self.assertEqual(scene_of("机房UPS改造"), "数据中心与机房")

    def test_amount_units(self):
        self.assertEqual(amount_wan("人民币400.810000 万元"), 400.81)
        self.assertEqual(amount_wan("人民币1,200,000.00元"), 120.0)
        self.assertEqual(amount_wan("人民币1.5亿元"), 15000.0)
        self.assertIsNone(amount_wan(""))

    def test_amount_across_newline(self):
        # 询价公告常见写法：成交金额：人民币\n697000.00元
        text = "成交金额：人民币\n697000.00元\n是否中小企业生产：\n是"
        self.assertEqual(amount_wan(amount_field(text, "(?:成交金额|中标金额)")), 69.7)

    def test_construction_and_maintenance_rejected(self):
        ok, _ = classify_scope("应急总医院安全改造项目(急诊中心、影像介入中心)施工采购", "应急总医院")
        self.assertFalse(ok)
        ok, _ = classify_scope("北京大学第六医院综合维修及配电运维专业外包服务采购项目", "北京大学第六医院")
        self.assertFalse(ok)

    def test_health_support_and_medical_education_tags(self):
        self.assertEqual(customer_tag("国家医学考试中心"), "卫生支撑机构")
        self.assertEqual(customer_tag("北京协和医学院"), "医学教育/科研机构")
        self.assertEqual(customer_tag("北京大学", "北京大学医学部人工智能辅助教学科研设备采购项目"),
                         "医学教育/科研机构")

    def test_scene_fallback_not_empty(self):
        self.assertEqual(scene_of("某项采购"), "其他数字化")


class DetailTest(unittest.TestCase):
    def setUp(self):
        self.detail = parse_detail(DETAIL_HTML, "http://x/detail.htm",
                                   {"title": "中国医学科学院北京协和医院负载均衡更新及高阶云节点扩容采购项目中标公告",
                                    "published_at": "2026-10-22", "region": "北京"})

    def test_core_fields(self):
        self.assertEqual(self.detail["项目编号"], "GC-HGX261026")
        self.assertEqual(self.detail["采购方式"], "公开招标")
        self.assertEqual(self.detail["预算金额（万元）"], 410.0)
        self.assertEqual(self.detail["中标金额（万元）"], 400.81)
        self.assertEqual(self.detail["招标单位"], "中国医学科学院北京协和医院")
        self.assertEqual(self.detail["中标单位"], "北京神州数码云计算有限公司")
        self.assertEqual(self.detail["采购执行机构"], "中央国家机关政府采购中心")

    def test_products_and_brands(self):
        self.assertIn("云计算节点扩容", self.detail["产品"])
        self.assertNotIn("序号", self.detail["产品"])
        self.assertEqual(self.detail["品牌"], "H3C、信安世纪")

    def test_row_matches_requested_columns(self):
        row = build_row(self.detail)
        self.assertEqual(list(row.keys()), COLUMNS)
        self.assertEqual(row["场景"], "云与算力")
        self.assertEqual(row["运营商类型"], "非运营商")
        self.assertEqual(row["中标金额（万元）"], 400.81)

    def test_missing_fields_do_not_crash(self):
        detail = parse_detail("<html><body><p>空公告</p></body></html>", "u", {"title": "某医院系统采购中标公告"})
        row = build_row(detail)
        self.assertEqual(row["招标单位"], "")
        self.assertIsNone(row["中标金额（万元）"])
        self.assertTrue(row["场景"])


if __name__ == "__main__":
    unittest.main()
