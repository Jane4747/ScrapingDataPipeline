import unittest

from pipeline.research.relevance import classify


class RelevanceTests(unittest.TestCase):
    def test_surgical_robot_features_are_direct_evidence(self):
        result = classify("骨科技术", "自主研发的手术机器人通过光学导航和自动配准，控制机械臂辅助医生精准定位。")
        self.assertEqual(result["relevance"], "direct_equipment")
        self.assertIn("surgical_robotics", result["categories"])
        self.assertIn("手术机器人", result["matched_terms"])
        self.assertIn("自动配准", result["evidence"][0]["text"])

    def test_rehabilitation_exoskeleton_requires_medical_context(self):
        positive = classify("训练系统", "外骨骼采用力控反馈算法，为脊髓损伤患者提供步态康复训练和运动评估。")
        negative = classify("工业外骨骼", "工业外骨骼采用力控传感器，用于工厂搬运和建筑施工，降低工人劳动强度。")
        self.assertEqual(positive["relevance"], "direct_equipment")
        self.assertFalse(negative["relevant"])

    def test_english_rehabilitation_technical_description(self):
        result = classify("Rehabilitation", "Our rehabilitation robotics use force sensors and adaptive control to support patient gait training.")
        self.assertEqual(result["relevance"], "direct_equipment")
        self.assertIn("rehabilitation_exoskeleton", result["categories"])

    def test_medical_ai_is_supporting_without_hardware(self):
        result = classify("影像算法", "医学影像AI模型通过深度学习识别病灶，辅助医生进行临床诊断和病例分析。")
        self.assertEqual(result["relevance"], "supporting_technology")
        self.assertIn("medical_ai", result["categories"])
        self.assertNotIn("medical_imaging", result["categories"])

    def test_cloud_infrastructure_is_supporting(self):
        result = classify("医疗云", "医院专属私有云采用超融合架构，为医学影像数据提供云存储、传输和互联互通服务。")
        self.assertEqual(result["relevance"], "supporting_technology")
        self.assertIn("medical_cloud_data", result["categories"])

    def test_imaging_and_diagnostic_hardware(self):
        cases = (
            ("CT设备采用智能重建算法，提高临床扫描速度并降低射线剂量。", "medical_imaging"),
            ("新型监护仪集成多参数传感器，实时监测患者生命体征并自动分析异常信号。", "monitoring_diagnostics"),
            ("自主研发的医疗设备集成智能控制与传感模块，可实现远程数据采集。", "intelligent_medical_equipment"),
        )
        for body, category in cases:
            with self.subTest(body=body):
                result = classify("技术资料", body)
                self.assertEqual(result["relevance"], "direct_equipment")
                self.assertIn(category, result["categories"])

    def test_generic_ai_healthy_development_and_operation_are_not_related(self):
        for text in (
            "集团运用AI技术推进企业数字化转型，推动产业健康发展和经济高质量增长。",
            "公司运营多家医疗机构，努力建设综合医疗服务体系，持续提升服务质量。",
            "集团发布新一代人工智能大模型，为工业生产提供质量检测和算法服务。",
            "企业聚焦医疗装备产业，携手合作伙伴推动产业健康发展和合作共赢。",
        ):
            with self.subTest(text=text):
                result = classify("集团新闻", text)
                self.assertEqual(result, {"relevant": False, "relevance": "none", "categories": [], "matched_terms": [], "evidence": []})

    def test_navigation_terms_do_not_contaminate_company_news(self):
        result = classify("公司周年活动", "首页 | 关于我们 | 手术机器人 | 医疗云 | 新闻中心 | 联系我们\n集团举行周年庆典，全体员工共同参与活动并交流未来发展愿景。")
        self.assertFalse(result["relevant"])

    def test_distant_mentions_do_not_combine_across_paragraphs(self):
        result = classify("公司简介", "公司拥有多家医院，为周边居民提供医疗服务，保障日常就医需求。\n公司人工智能平台采用深度学习算法，为工业制造提供数字化服务。")
        self.assertFalse(result["relevant"])

    def test_generic_vendor_industry_list_does_not_count_as_medical_cloud(self):
        result = classify("专属云", "云计算平台采用虚拟化技术，面向金融、教育、医疗等行业客户提供云服务和数据处理能力。")
        self.assertFalse(result["relevant"])

    def test_latin_abbreviations_have_word_boundaries(self):
        result = classify("Hospital administration", "Hospital retail mail services improve interaction between departments and streamline ordinary data collection.")
        self.assertFalse(result["relevant"])

    def test_title_only_and_short_navigation_do_not_qualify(self):
        self.assertFalse(classify("智能医疗装备技术研究", "")["relevant"])
        self.assertFalse(classify("手术机器人", "手术机器人\n产品中心\n医疗AI\n联系我们")["relevant"])

    def test_equipment_title_can_supply_subject_for_first_feature_paragraph(self):
        result = classify("天玑手术机器人", "该系统通过自动配准与光学定位，精确控制机械臂沿规划路径运动。")
        self.assertEqual(result["relevance"], "direct_equipment")

    def test_equipment_title_does_not_turn_corporate_slogan_into_evidence(self):
        for body in (
            "公司秉持创新理念，大力推动自主研发，携手行业伙伴健康发展。",
            "公司将持续推动平台应用，完善数据管理工作，努力实现经营目标。",
            "We invest in research and development to build a global platform and create value for partners.",
        ):
            with self.subTest(body=body):
                self.assertFalse(classify("手术机器人 Surgical robots", body)["relevant"])

    def test_evidence_is_bounded_and_contains_its_terms(self):
        text = "\n".join(f"第{i}项自主研发的手术机器人采用光学导航和自动配准，控制机械臂完成临床定位。" for i in range(12))
        result = classify("技术资料", text)
        self.assertLessEqual(len(result["evidence"]), 5)
        for item in result["evidence"]:
            self.assertLessEqual(len(item["text"]), 240)
            for term in item["terms"]:
                self.assertIn(term, item["text"].lower())

    def test_direct_evidence_survives_long_supporting_preamble(self):
        text = "\n".join(f"第{i}家医院采用私有云技术，为医疗数据提供云存储、传输与算法处理服务。" for i in range(60))
        text += "\n自主研发的手术机器人通过光学导航控制机械臂，实现实时定位与临床配准。"
        result = classify("年度研究进展", text)
        self.assertEqual(result["relevance"], "direct_equipment")
        self.assertIn("手术机器人", result["evidence"][0]["text"])

    def test_compact_chinese_technical_sentence_is_retained(self):
        result = classify("新品功能", "手术机器人采用智能导航技术。")
        self.assertEqual(result["relevance"], "direct_equipment")

    def test_english_plural_robots_and_industrial_hospital_exoskeleton(self):
        result = classify("Products", "Our surgical robots combine imaging sensors and navigation control for clinical procedures.")
        self.assertEqual(result["relevance"], "direct_equipment")
        unrelated = classify("后勤装备", "医院后勤仓库采用工业外骨骼搬运货物，通过传感控制减轻工人搬运压力。")
        self.assertFalse(unrelated["relevant"])


if __name__ == "__main__":
    unittest.main()
