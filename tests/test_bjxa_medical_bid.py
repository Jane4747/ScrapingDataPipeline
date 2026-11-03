import unittest

from pipeline.research.bjxa import (
    COLUMNS,
    boundary_hint,
    collect_ccgp_supplement,
    is_xiongan_result,
    js_string,
    parse_beijing_detail,
    parse_beijing_list,
    parse_hebei_article,
    parse_hebei_packed,
    parse_xiongan_detail,
    parse_xiongan_list,
    region_guard,
    write_boundary_review,
    xiongan_list_url,
)
from pipeline.research.bid_common import build_row, classify_scope

BEIJING_LIST = """
<ul class="inner-ul">
<li><a href="//www.ccgp-beijing.gov.cn/xxgg/sjxxgg/zbggs/2026/10/aaa.htm" target="_parent">
[公开]首都医科大学附属北京天坛医院影像云平台扩容项目中标公告</a>
<span class="datetime" style="float: right">2026-10-27</span></li>
<li><a href="//www.ccgp-beijing.gov.cn/xxgg/qjxxgg/qjzbggs/2026/10/bbb.htm" target="_parent">
[朝阳区]某社区卫生服务中心电子病历系统升级项目成交公告</a>
<span class="datetime" style="float: right">2026-10-26</span></li>
<li><a href="//www.ccgp-beijing.gov.cn/xxgg/sjxxgg/zbggs/2026/10/ccc.htm" target="_parent">
[公开]某单位办公家具采购项目中标公告</a>
<span class="datetime" style="float: right">2026-10-25</span></li>
</ul>
"""

BEIJING_DETAIL = """
<html><body><div class="BodyLabel">
<p>首都医科大学附属北京天坛医院影像云平台扩容项目中标公告</p>
<p>一、项目编号：11000026210200186370-XM001</p>
<p>二、项目名称：首都医科大学附属北京天坛医院影像云平台扩容项目</p>
<p>三、中标（成交）信息</p>
<p>总中标成交金额：868.5 万元（人民币）</p>
<p>中标成交供应商名称：北京神州数码云计算有限公司</p>
<p>中标成交供应商地址：北京市海淀区上地九街9号</p>
<p>中标金额：868.5万元</p>
<p>四、主要标的信息</p>
<table>
<tr><td>供应商</td><td>商品名称</td><td>规格型号</td><td>数量</td><td>单价</td><td>总价</td><td>服务要求</td></tr>
<tr><td>北京神州数码云计算有限公司</td><td>医学影像云存储节点</td><td>H3C UniStor</td><td>3</td><td>120万元</td><td>360万元</td><td>详见文件</td></tr>
<tr><td>北京神州数码云计算有限公司</td><td>影像云平台软件</td><td>V3.2</td><td>1</td><td>508.5万元</td><td>508.5万元</td><td>详见文件</td></tr>
</table>
<p>1.采购人信息</p>
<p>名 称：首都医科大学附属北京天坛医院</p>
<p>2.采购代理机构信息</p>
<p>名 称：中技国际招标有限公司</p>
</div></body></html>
"""

XIONGAN_LIST = """
<ul>
<li><a href="https://www.xaprtc.com:443/jyxxzccg/10001.jhtml?token=a" title="【雄安新区】某医院信息系统采购项目招标公告">【雄安新区】某医院信息系统采购项目招标公告</a><p>2026-10-27</p></li>
<li><a href="https://www.xaprtc.com:443/jyxxzccj/10002.jhtml?token=b" title="【雄安新区】容西片区贤溪社区卫生服务中心2026年信息化提升项目成交公告">【雄安新区】容西片区贤溪社区卫生服务中心2026年信息化提升项目成交公告</a><p>2026-10-26</p></li>
<li><a href="https://www.xaprtc.com:443/jyxxzccj/10003.jhtml?token=c" title="【雄安新区容城县】容城县农村公路改造项目成交公告">【雄安新区容城县】容城县农村公路改造项目成交公告</a><p>2026-10-25</p></li>
</ul>
"""

XIONGAN_SHELL = """
<html><body><div class="er-title">交易公开详情</div>
<p>容西片区贤溪社区卫生服务中心2026年信息化提升项目成交公告</p>
<p>公告类型：中标成交公示</p>
<p>公告来源：http://www.ccgp-hebei.gov.cn/xazq/xaxq_xaxq/cggg/zhbggAAAS/202610/t20261027_2446781.html</p>
</body></html>
"""

HEBEI_SINGLE = """
<html><body><script>
var detail = {
  PurchaserName: `容西片区贤溪社区卫生服务中心`,
  PROJECTCODE: `HB2026097040010002`,
  PROJECTNAME: `容西片区贤溪社区卫生服务中心2026年信息化提升项目`,
  DOCTITLE: `容西片区贤溪社区卫生服务中心2026年信息化提升项目成交公告`,
  PURCHASEWAY: `竞争性磋商`,
  gpbudgetamt: `950000`,
  AGENCYFULLNAME: `河北某招标代理有限公司`,
  content: `null#detail#C#_@_@A#_@_@911101087481059966#_@_@中移建设有限公司#_@_@北京市海淀区北蜂窝路18号#_@_@卫生服务中心信息化系统#_@_@null#_@_@#_@_@#_@_@null#_@_@872000#_@_@null#_@_@合格，满足采购人需求#_@_@`
};
</script></body></html>
"""

HEBEI_MULTI = """
<html><body><script>
var detail = {
  PurchaserName: `雄安新区某医院`,
  PROJECTCODE: `HB2026097040010003`,
  PROJECTNAME: `某医院云平台扩容项目`,
  content: `null#detail#C#_@_@A#_@_@91110000MA00ANGQ9D#_@_@北京甲科技有限公司#_@_@北京市海淀区#_@_@云平台节点#_@_@null#_@_@#_@_@#_@_@null#_@_@1200000#_@_@null#_@_@ok#_@_@B#_@_@A#_@_@91310120MA1J0BR75U#_@_@上海乙信息技术有限公司#_@_@上海市闵行区#_@_@分布式存储#_@_@null#_@_@#_@_@#_@_@null#_@_@800000#_@_@null#_@_@ok#_@_@`
};
</script></body></html>
"""


class BeijingListTest(unittest.TestCase):
    def test_items_have_title_date_and_absolute_url(self):
        items = parse_beijing_list(BEIJING_LIST, "市级")
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["published_at"], "2026-10-27")
        self.assertTrue(items[0]["url"].startswith("http://www.ccgp-beijing.gov.cn/"))
        self.assertEqual(items[0]["channel"], "市级")

    def test_channel_prefix_is_stripped_into_hint(self):
        items = parse_beijing_list(BEIJING_LIST, "市级")
        self.assertEqual(items[0]["title_prefix"], "公开")
        self.assertEqual(items[1]["title_prefix"], "朝阳区")
        self.assertFalse(items[0]["title"].startswith("["))
        self.assertIn("天坛医院", items[0]["title"])


class BeijingDetailTest(unittest.TestCase):
    def setUp(self):
        self.detail = parse_beijing_detail(BEIJING_DETAIL, "http://x/a.htm",
                                           {"title": "首都医科大学附属北京天坛医院影像云平台扩容项目中标公告",
                                            "published_at": "2026-10-27", "channel": "市级"})

    def test_core_fields(self):
        self.assertEqual(self.detail["项目编号"], "11000026210200186370-XM001")
        self.assertEqual(self.detail["招标单位"], "首都医科大学附属北京天坛医院")
        self.assertEqual(self.detail["中标单位"], "北京神州数码云计算有限公司")
        self.assertEqual(self.detail["中标金额（万元）"], 868.5)
        self.assertEqual(self.detail["采购执行机构"], "中技国际招标有限公司")

    def test_products_and_brands_from_main_goods_table(self):
        self.assertIn("医学影像云存储节点", self.detail["产品"])
        self.assertNotIn("供应商", self.detail["产品"])
        self.assertIn("H3C UniStor", self.detail["品牌"])

    def test_row_uses_shared_columns(self):
        row = build_row(self.detail)
        self.assertEqual(list(row.keys()), COLUMNS)
        self.assertEqual(row["客户标签"], "高校附属医院")
        self.assertEqual(row["场景"], "云与算力")
        self.assertEqual(row["运营商类型"], "非运营商")

    def test_missing_fields_do_not_crash(self):
        detail = parse_beijing_detail("<html><body><div class='BodyLabel'><p>空</p></div></body></html>",
                                      "http://x/b.htm", {"title": "某医院系统采购中标公告"})
        row = build_row(detail)
        self.assertEqual(row["招标单位"], "")
        self.assertIsNone(row["中标金额（万元）"])
        self.assertTrue(row["场景"])


class XionganListTest(unittest.TestCase):
    def test_list_parse_and_region_prefix(self):
        items = parse_xiongan_list(XIONGAN_LIST)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["region_hint"], "雄安新区")
        self.assertEqual(items[2]["region_hint"], "雄安新区容城县")
        self.assertEqual(items[0]["published_at"], "2026-10-27")

    def test_only_result_channel_kept(self):
        items = parse_xiongan_list(XIONGAN_LIST)
        kept = [i for i in items if is_xiongan_result(i["url"])]
        self.assertEqual(len(kept), 2)
        self.assertFalse(any("/jyxxzccg/" in i["url"] for i in kept))

    def test_pagination_url_shape(self):
        self.assertNotIn("queryContent_", xiongan_list_url(1))
        self.assertIn("queryContent_7-jyxx.jspx", xiongan_list_url(7))
        self.assertIn("channelId=273", xiongan_list_url(7))


class XionganDetailTest(unittest.TestCase):
    def test_source_url_extracted_and_forced_https(self):
        detail = parse_xiongan_detail(XIONGAN_SHELL, "https://x/1.jhtml",
                                      {"title": "容西…成交公告", "published_at": "2026-10-26"})
        self.assertTrue(detail["公告来源"].startswith("https://www.ccgp-hebei.gov.cn/"))
        self.assertIn("t20261027_2446781", detail["公告来源"])


class HebeiArticleTest(unittest.TestCase):
    def test_js_string_skips_empty_then_takes_value(self):
        self.assertEqual(js_string(HEBEI_SINGLE, "PROJECTCODE"), "HB2026097040010002")

    def test_single_package_fields(self):
        detail = parse_hebei_article(HEBEI_SINGLE, "https://hb/1.html",
                                     {"title": "容西…成交公告", "published_at": "2026-10-26",
                                      "region_hint": "雄安新区"})
        self.assertEqual(detail["招标单位"], "容西片区贤溪社区卫生服务中心")
        self.assertEqual(detail["中标单位"], "中移建设有限公司")
        self.assertEqual(detail["中标金额（万元）"], 87.2)
        self.assertEqual(detail["预算金额（万元）"], 95.0)
        self.assertEqual(detail["区县"], "雄安新区")

    def test_packed_multi_package_sums_amounts(self):
        suppliers, amounts, products = parse_hebei_packed(js_string(HEBEI_MULTI, "content"))
        self.assertEqual(suppliers, ["北京甲科技有限公司", "上海乙信息技术有限公司"])
        self.assertEqual(amounts, [1200000.0, 800000.0])
        self.assertEqual(products, ["云平台节点", "分布式存储"])

    def test_multi_package_article_total(self):
        detail = parse_hebei_article(HEBEI_MULTI, "https://hb/2.html", {"title": "某医院云平台扩容项目成交公告"})
        self.assertEqual(detail["中标金额（万元）"], 200.0)
        self.assertEqual(build_row(detail)["中标单位"], "北京甲科技有限公司；上海乙信息技术有限公司")

    def test_health_center_digital_kept_and_road_rejected(self):
        ok, _ = classify_scope("容西片区贤溪社区卫生服务中心2026年信息化提升项目", "雄安新区")
        self.assertTrue(ok)
        ok, reason = classify_scope("容城县农村公路改造项目", "雄安新区容城县")
        self.assertFalse(ok)
        self.assertIn("非医卫", reason)


class RegionGuardTest(unittest.TestCase):
    """检索站是全文命中，`雄县`会命中云南`镇雄县`，入表前必须过地域校验。"""

    def test_platform_notice_passes_by_domain(self):
        ok, _ = region_guard("xa", {"title": "某医院系统采购项目成交公告",
                                    "url": "https://www.xaprtc.com:443/jyxxzccj/1.jhtml"})
        self.assertTrue(ok)
        ok, _ = region_guard("bj", {"title": "某医院系统采购项目中标公告",
                                    "url": "http://www.ccgp-beijing.gov.cn/xxgg/a.htm"})
        self.assertTrue(ok)

    def test_yunnan_zhenxiong_rejected_for_xiongan(self):
        notice = {"title": "镇雄县中医医院网络改造建设项目（二次）中标公告",
                  "url": "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202601/t1.htm",
                  "region_label": "云南"}
        ok, reason = region_guard("xa", notice)
        self.assertFalse(ok)
        self.assertIn("云南", reason)

    def test_hebei_rongcheng_accepted_for_xiongan(self):
        notice = {"title": "容城县人民医院信息系统运维服务项目成交公告",
                  "url": "http://www.ccgp.gov.cn/cggg/dfgg/cjgg/202601/t2.htm",
                  "region_label": "河北"}
        self.assertTrue(region_guard("xa", notice)[0])

    def test_beijing_labelled_xiongan_hospital_accepted(self):
        # 雄安宣武医院的公告由首都医科大学宣武医院代发，检索站标“北京”
        notice = {"title": "雄安宣武医院（新区投资部分）项目信息化工程（一期）中标公告",
                  "url": "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202603/t9.htm",
                  "region_label": "北京"}
        self.assertTrue(region_guard("xa", notice)[0])

    def test_zhenxiong_rejected_even_if_label_says_hebei(self):
        notice = {"title": "镇雄县中医医院网络改造建设项目（二次）中标公告",
                  "url": "http://www.ccgp.gov.cn/cggg/dfgg/cjgg/202604/t5.htm",
                  "region_label": "河北"}
        self.assertFalse(region_guard("xa", notice)[0])

    def test_highlight_spaces_do_not_block_local_name(self):
        # 检索结果把关键词包进高亮标签，get_text 会拆出“安新 县”
        notice = {"title": "安新 县医院电梯设备采购项目中标公告",
                  "url": "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202604/t6.htm",
                  "region_label": "河北"}
        self.assertTrue(region_guard("xa", notice)[0])

    def test_bare_anxin_substring_in_other_places_rejected(self):
        for title, label in (("浙江展图工程咨询有限公司关于磐 安新 城区2026年市政设施运维服务项目中标公告", "浙江"),
                             ("营口市西市区华 安新 邨小区老旧改造工程施工图设计结果公告", "辽宁")):
            notice = {"title": title, "url": "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202603/t7.htm",
                      "region_label": label}
            self.assertFalse(region_guard("xa", notice)[0], title[:20])

    def test_out_of_region_beijing_notice_rejected(self):
        notice = {"title": "辽宁省朝阳市中心医院信息化项目中标公告",
                  "url": "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202601/t3.htm",
                  "region_label": "辽宁"}
        self.assertFalse(region_guard("bj", notice)[0])

    def test_region_label_alone_is_not_enough_for_xiongan(self):
        # 河北其他地市的项目不该进雄安表
        notice = {"title": "石家庄市人民医院his系统升级项目中中标公告",
                  "url": "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202601/t4.htm",
                  "region_label": "河北"}
        self.assertFalse(region_guard("xa", notice)[0])


SEARCH_PAGE = """
<html><body><ul class="vT-srch-result-list-bid">
<li><a href="http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202601/tA.htm">镇雄县中医医院网络改造建设项目 中标 公告</a>
<span>2026.01.20 10:00:00 | 中标公告 | 云南 | 采购人：镇雄县中医医院 | 代理机构：某代理 中标公告</span></li>
<li><a href="http://www.ccgp.gov.cn/cggg/dfgg/cjgg/202601/tB.htm">容城县人民医院信息系统运维项目 成交 公告</a>
<span>2026.01.19 10:00:00 | 成交公告 | 河北 | 采购人：容城县人民医院 | 代理机构：某代理 成交公告</span></li>
</ul></body></html>
"""


class FakeRunner:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, domains, tag, offline=False):
        self.calls.append(tag)
        return self.pages.pop(0) if self.pages else None

    def log(self, message):
        pass


class SupplementRegionFilterTest(unittest.TestCase):
    def test_supplement_drops_off_region_rows(self):
        runner = FakeRunner([SEARCH_PAGE])
        notices, stats = collect_ccgp_supplement(
            runner, "雄安", "2026-01-01", "2026-01-31", ["雄安"], "", 3, "",
            r"雄安|容城|安新|(?<!镇)雄县", ["河北", "雄安", "雄安新区"])
        titles = [n["title"] for n in notices]
        self.assertEqual(len(notices), 1)
        self.assertIn("容城县人民医院", titles[0])
        self.assertEqual(notices[0]["region_label"], "河北")
        self.assertGreaterEqual(stats["off_region"], 1)


class BoundaryReviewTest(unittest.TestCase):
    """口径边界：命中数字化词但标的其实是硬件维保/设备购置，单列复核清单而不是直接改共享口径。"""

    def test_device_maintenance_flagged(self):
        self.assertEqual(boundary_hint("北京天坛医院大型医疗设备维保项目"), "医工设备维保")
        self.assertEqual(boundary_hint("北京市大兴区人民医院购买放射类及超声类设备维保"), "医工设备维保")

    def test_device_bulk_purchase_flagged(self):
        self.assertEqual(boundary_hint("北京市属医院2026年医用设备集中带量采购项目超声组"), "医用设备购置")

    def test_it_maintenance_not_flagged(self):
        # IT 设备维保属于数字化，不能被边界规则误伤
        self.assertEqual(boundary_hint("北京儿童医院存储设备维保及安全服务项目"), "")
        self.assertEqual(boundary_hint("友谊医院信息基础设施设备维保及驻场服务运维"), "")

    def test_medical_device_package_flagged_but_system_not(self):
        self.assertEqual(boundary_hint("雄安宣武医院补充医疗设备项目第十二包（C臂、输注系统等）"), "医用设备购置")
        self.assertEqual(boundary_hint("某医院医疗设备管理系统采购项目"), "")

    def test_review_csv_written(self):
        import tempfile
        from pathlib import Path as _Path
        from pipeline.research.bjxa import write_boundary_review
        records = [
            {"row": {"项目名称": "北京天坛医院大型医疗设备维保项目", "招标单位": "北京天坛医院",
                     "中标单位": "某公司", "中标金额（万元）": 9735.62}, "detail": {"公告链接": "http://x/1"}},
            {"row": {"项目名称": "某医院信息系统升级项目", "招标单位": "某医院",
                     "中标单位": "某公司", "中标金额（万元）": 100.0}, "detail": {"公告链接": "http://x/2"}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _Path(tmp) / "口径边界复核.csv"
            count = write_boundary_review(records, path)
            self.assertEqual(count, 1)
            text = path.read_text(encoding="utf-8-sig")
            self.assertIn("医工设备维保", text)
            self.assertNotIn("信息系统升级项目", text)


if __name__ == "__main__":
    unittest.main()
