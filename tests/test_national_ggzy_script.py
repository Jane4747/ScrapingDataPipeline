# -*- coding:utf-8 -*-
"""全国公共资源交易平台（1600006）站点脚本的离线回归。

只测解析与口径，不联网：样本取自 2026-10-28 实测的接口响应结构
（WAF 404 静态页、code 400 日期校验、前端 JS 记载的 code 200 records 结构）。
"""
import unittest
from site_script_fixture import load_site_script

_SCRIPT = None

WAF_HTML = """<!DOCTYPE html>
<html><head><title>网页暂时无法访问</title></head><body>404</body></html>
"""

API_OK = """
{"code":200,"message":"success","usetime":12,"data":{
  "total":2,"pages":1,"current":1,
  "records":[
    {"DEALNAME":"某市第一医院电子病历系统升级采购项目中标公告",
     "DEALTIME":"2026-10-27","OPTURL":"/information/html/a/110000/0502/202610/27/abc.shtml",
     "PROVINCE":"110000","PLATFORMNAME":"北京市公共资源交易平台"},
    {"TITLE":"公安局设备采购公告","TIME":"2026-10-27","URL":"x"}
  ]}}
"""

API_CAPTCHA = """
{"code":829,"message":"请输入验证码","captchaToken":"t-1","captchaImage":"base64..."}
"""

API_DATE_ERR = """
{"code":400,"message":"结束时间错误！","data":null,"usetime":0}
"""


def setUpModule():
    global _SCRIPT
    _SCRIPT = load_site_script("1600006.全国公共资源交易平台-医卫数智.py", "national_ggzy_script")


class ClassifyTests(unittest.TestCase):
    def test_medical_digital_hit(self):
        kind, keywords = _SCRIPT.classify("某市第一医院电子病历系统升级采购项目中标公告")
        self.assertEqual(kind, "医卫数智")
        self.assertIn("医院", keywords)

    def test_negative_excluded(self):
        kind, _ = _SCRIPT.classify("公安局会议室大屏系统采购公告")
        self.assertIsNone(kind)

    def test_weak_signal_with_industry_word(self):
        # 注：共享词表 NEGATIVE 含「档案」，故「健康档案」类标题会被排除（与 1600005 口径一致）；
        # 这里用不含负向词的弱信号样例验证弱信号通路。
        kind, _ = _SCRIPT.classify("养老服务中心综合监管平台建设项目")
        self.assertEqual(kind, "医卫数智")

    def test_health_archive_title_excluded_by_shared_negative_list(self):
        kind, _ = _SCRIPT.classify("养老服务中心健康档案平台建设项目")
        self.assertIsNone(kind)

    def test_weak_signal_with_negative_word(self):
        kind, _ = _SCRIPT.classify("健康路街道治安监控采购")
        self.assertIsNone(kind)


class ApiResponseTests(unittest.TestCase):
    def test_waf_html_detected(self):
        kind, payload = _SCRIPT.parse_api_response(WAF_HTML)
        self.assertEqual(kind, "html")
        self.assertIn("WAF", payload)

    def test_ok_json_parsed(self):
        kind, payload = _SCRIPT.parse_api_response(API_OK)
        self.assertEqual(kind, "json")
        rows, meta = _SCRIPT.parse_records(payload)
        self.assertEqual(meta["total"], 2)
        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertIn("电子病历", first["标题"])
        self.assertEqual(first["日期"], "2026-10-27")
        self.assertTrue(first["链接"].startswith(_SCRIPT.BASE))
        self.assertEqual(first["省份"], "110000")

    def test_captcha_code_not_treated_as_records(self):
        kind, payload = _SCRIPT.parse_api_response(API_CAPTCHA)
        self.assertEqual(kind, "json")
        self.assertEqual(payload.get("code"), 829)
        rows, _ = _SCRIPT.parse_records(payload)
        self.assertEqual(rows, [])

    def test_date_error_json(self):
        kind, payload = _SCRIPT.parse_api_response(API_DATE_ERR)
        self.assertEqual(kind, "json")
        self.assertEqual(payload.get("message"), "结束时间错误！")


class FormTests(unittest.TestCase):
    def test_build_form(self):
        form = _SCRIPT.build_form("02", "医院", "2026-10-21", "2026-10-28", 3)
        self.assertEqual(form["DEAL_CLASSIFY"], "02")
        self.assertEqual(form["FINDTXT"], "医院")
        self.assertEqual(form["PAGENUMBER"], "3")
        self.assertEqual(form["TIMEBEGIN"], "2026-10-21")

    def test_endpoints_documented(self):
        names = {name for name, _ in _SCRIPT.ENDPOINTS}
        self.assertEqual(names, {"current", "history"})
        for _, path in _SCRIPT.ENDPOINTS:
            self.assertTrue(path.endswith("/pubTradingInfo/getTradList"))


if __name__ == "__main__":
    unittest.main()
