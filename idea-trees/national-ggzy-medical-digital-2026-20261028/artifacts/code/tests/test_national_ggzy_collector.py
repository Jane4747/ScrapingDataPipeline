import unittest
from pipeline.research.national_ggzy import months, split_window, in_scope, parse_article, classify_scene, carrier_label


class WindowTests(unittest.TestCase):
    def test_month_boundaries_inclusive(self):
        self.assertEqual(list(months("2026-01-20","2026-03-02")), [("2026-01-20","2026-01-31"),("2026-02-01","2026-02-28"),("2026-03-01","2026-03-02")])

    def test_split_no_gap(self):
        self.assertEqual(split_window("2026-01-01","2026-01-04"),[("2026-01-01","2026-01-02"),("2026-01-03","2026-01-04")])

    def test_single_day_not_split(self):
        self.assertEqual(split_window("2026-01-01","2026-01-01"),[])


class ScopeTests(unittest.TestCase):
    def test_explicit_software(self):
        self.assertTrue(in_scope("人民医院医疗设备管理信息系统采购"))

    def test_hvac_not_digital(self):
        self.assertFalse(in_scope("人民医院空调及暖通系统维护服务"))

    def test_medical_machine_not_computer_it(self):
        self.assertFalse(in_scope("人民医院单光子发射计算机断层扫描仪采购"))

    def test_network_storage(self):
        self.assertTrue(in_scope("第一医院影像系统存储资源扩容项目"))

    def test_non_health(self):
        self.assertFalse(in_scope("某法院信息化服务器采购"))

    def test_civil_construction_not_digital_budget(self):
        self.assertFalse(in_scope("智慧医院建筑施工总承包项目"))

    def test_yunnan_not_cloud(self):
        self.assertEqual(classify_scene("云南省人民医院网络安全建设",""),"信息安全")


class DetailTests(unittest.TestCase):
    def notice(self, kind="0202"):
        return {"url":"/information/deal/html/a/x.html","title":"人民医院信息化项目中标公告","publishTime":"2026-01-16","informationType":kind,"informationTypeText":"中标公告" if kind=="0202" else "采购公告"}

    def test_money_and_named_buyer(self):
        h='<div id="mycontent"><p>项目名称：人民医院信息化项目</p><p>供应商名称：中国电信某分公司</p><p>中标（成交）金额：22055416.00元</p><p>1.采购人信息</p><p>名称：人民医院</p></div>'
        row=parse_article(h,self.notice())
        self.assertEqual(row["中标金额（万元）"],2205.5416)
        self.assertEqual(row["招标单位"],"人民医院")
        self.assertEqual(row["运营商类型"],"中国电信")

    def test_budget_is_not_award(self):
        row=parse_article('<p>预算金额：200万元</p>',self.notice())
        self.assertIsNone(row["中标金额（万元）"])

    def test_multiple_lots_not_first_as_total(self):
        row=parse_article('<p>中标金额：100万元</p><p>中标金额：200万元</p>',self.notice())
        self.assertIsNone(row["中标金额（万元）"])

    def test_tender_does_not_invent_award(self):
        n=self.notice("0201");n["title"]="人民医院信息化项目公开招标公告"
        row=parse_article('<p>供应商名称：样例公司</p><p>中标金额：100万元</p>',n)
        self.assertEqual(row["中标单位"],"")
        self.assertIsNone(row["中标金额（万元）"])

    def test_table_award_and_units(self):
        h='<table><tr><td>中标（成交）金额（元）</td><td>中标供应商名称</td></tr><tr><td>报价：648000（元）</td><td>示例信息技术有限公司</td></tr></table>'
        row=parse_article(h,self.notice())
        self.assertEqual(row["中标金额（万元）"],64.8)
        self.assertEqual(row["中标单位"],"示例信息技术有限公司")

    def test_product_not_lot_title(self):
        h='<table><tr><td>标项名称</td><td>标的名称</td><td>品牌</td></tr><tr><td>医院机房建设</td><td>服务器机柜</td><td>某品牌</td></tr></table>'
        self.assertEqual(parse_article(h,self.notice())["产品"],"服务器机柜")

    def test_candidate_not_final_winner(self):
        n=self.notice();n["title"]="人民医院信息化中标候选人公示"
        row=parse_article('<p>中标人：示例公司</p><p>中标金额：100万元</p>',n)
        self.assertFalse(row["_is_final_award"])
        self.assertEqual(row["中标单位"],"")
        self.assertIsNone(row["中标金额（万元）"])

    def test_finance_generic_notice_class_uses_explicit_result_title(self):
        n=self.notice("0201");n["informationTypeText"]="公告信息";n["title"]="医院信息化中标(成交)结果公告"
        row=parse_article('<p>供应商名称：示例公司</p><p>中标金额：100万元</p>',n)
        self.assertTrue(row["_is_final_award"])
        self.assertEqual(row["中标金额（万元）"],100)

    def test_nested_layout_table_does_not_add_product_type_as_supplier(self):
        h='<table><tr><td><table><tr><td>供应商名称</td><td>中标金额（万元）</td></tr><tr><td>甲信息公司</td><td>18</td></tr></table><table><tr><td>类型</td><td>名称</td><td>品牌</td></tr><tr><td>货物类</td><td>服务器</td><td>甲牌</td></tr></table></td></tr></table>'
        row=parse_article(h,self.notice())
        self.assertEqual(row["中标单位"],"甲信息公司")
        self.assertEqual(row["中标金额（万元）"],18)
        self.assertEqual(row["产品"],"服务器")

    def test_malformed_product_cell_does_not_capture_contact_footer(self):
        h='<table><tr><td>标的名称</td><td>品牌</td></tr><tr><td>服务器</td><td>甲</td></tr><tr><td>1.代理服务收费标准：联系方式：12345 采购人信息</td><td>乙</td></tr></table>'
        row=parse_article(h,self.notice())
        self.assertEqual(row["产品"],"服务器")
        self.assertEqual(row["_products"],["服务器"])

    def test_item_number_is_not_product(self):
        h='<table><tr><td>货物名称</td><td>品牌</td></tr><tr><td>品目号</td><td>甲</td></tr><tr><td>1-1</td><td>乙</td></tr></table>'
        self.assertEqual(parse_article(h,self.notice())["产品"],"")

    def test_multiple_carrier_suppliers_preserve_mixed_types(self):
        self.assertEqual(carrier_label("中电信某公司；中国移动某公司；甲信息公司"),"中国电信；中国移动；非运营商")


if __name__ == "__main__":unittest.main()
