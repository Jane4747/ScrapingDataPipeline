"""Offline regression checks for six-province buyer attribution and evidence gates."""
from pathlib import Path
import hashlib
import json
import tempfile
import unittest

import extractor as e


class SixProvinceExtractorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.entities = [
            {'id': '11', 'name': '苏州市示范人民医院', 'province': '江苏省'},
            {'id': '12', 'name': '苏州市另一人民医院', 'province': '江苏省'},
        ]

    def tearDown(self):
        self.temp.cleanup()

    def page(self, body, title='网络安全系统采购公告', entities=None, nav='', dated=True):
        raw = ('<html><head><title>' + title + '</title></head><body><nav>' + nav + '</nav>'
               '<article><h1>' + title + '</h1>'
               + ('<p>发布日期：2026-11-02</p>' if dated else '')
               + ''.join('<p>' + line + '</p>' for line in body.split('\n'))
               + '<p>本次采购的服务期限为一年，具体内容以正式采购文件和技术要求为准。</p>'
               + '</article></body></html>').encode()
        path = self.base / 'notice.html'
        path.write_bytes(raw)
        return {'url': 'https://example.org/news/1001.html', 'title': title,
                'hospital': '苏州市示范人民医院；苏州市另一人民医院', 'hospital_ids': '11；12',
                'hospital_entities': entities if entities is not None else self.entities,
                'raw_path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(),
                'province': '江苏省', 'task_id': 'S001', 'status': 'ok',
                'association_verified': True, 'entrance_verified': True}

    def extract(self, page, review=None):
        return e.extract_one(page, self.base, 'digital', review)

    def test_shared_entry_only_attributes_explicit_buyer(self):
        row, reason = self.extract(self.page('采购人：苏州市另一人民医院\n项目编号：SZ-2026-101\n采购内容：网络安全系统建设'))
        self.assertEqual(reason, '')
        self.assertEqual(row['医院ID'], '12')
        self.assertEqual(row['医院名称'], '苏州市另一人民医院')
        self.assertEqual(row['省份'], '江苏省')
        self.assertEqual(row['招标单位'], '苏州市另一人民医院')

    def test_external_repost_with_own_hospital_navigation_is_rejected(self):
        page = self.page('采购人：南京市外部医院\n采购内容：网络安全系统建设', nav='苏州市示范人民医院')
        row, reason = self.extract(page)
        self.assertIsNone(row)
        self.assertIn('不匹配入口医院', reason)

    def test_navigation_and_trusted_entry_do_not_fill_missing_buyer(self):
        row, reason = self.extract(self.page('采购内容：网络安全系统建设\n申请人资格要求：具备履约能力。', nav='苏州市示范人民医院'))
        self.assertIsNone(row)
        self.assertIn('不以导航院名或入口归属代填', reason)

    def test_buyer_information_section(self):
        row, reason = self.extract(self.page('一、采购内容：网络安全系统建设\n1.采购人信息\n名称：苏州市示范人民医院\n地址：江苏省苏州市'))
        self.assertEqual(reason, '')
        self.assertEqual(row['医院ID'], '11')

    def test_numbered_name_labels_reconcile_to_formal_buyer(self):
        entities = [{'id': '71', 'name': '嘉祥县人民医院', 'province': '山东省'}]
        body = '采购人： （一）名称： 嘉祥县人民医院\n采购人信息\n名称：嘉祥县人民医院\n采购内容：软件建设'
        row, reason = self.extract(self.page(body, entities=entities))
        self.assertEqual(reason, '')
        self.assertEqual(row['招标单位'], '嘉祥县人民医院')

    def test_parenthesized_name_subsection(self):
        entities = [{'id': '71', 'name': '嘉祥县人民医院', 'province': '山东省'}]
        row, reason = self.extract(self.page('采购人信息\n（一）名称：嘉祥县人民医院\n采购内容：软件建设', entities=entities))
        self.assertEqual(reason, '')
        self.assertEqual(row['医院ID'], '71')

    def test_contact_hospital_never_becomes_buyer(self):
        entities = [{'id': '72', 'name': '曲阜市人民医院', 'province': '山东省'}]
        row, reason = self.extract(self.page('采购人\n联 系 人：曲阜市人民医院\n采购内容：软件建设', entities=entities))
        self.assertIsNone(row)
        self.assertIn('未取得', reason)

    def test_spaced_repeated_buyer_label_is_only_a_prefix(self):
        entities = [{'id': '73', 'name': '日照市妇幼保健院', 'province': '山东省'}]
        body = '采购人： 采 购 人：日照市妇幼保健院\n采 购 人：日照市妇幼保健院\n采购内容：软件建设'
        row, reason = self.extract(self.page(body, entities=entities))
        self.assertEqual(reason, '')
        self.assertEqual(row['招标单位'], '日照市妇幼保健院')

    def test_benji_suffix_needs_same_document_formal_buyer(self):
        entities = [{'id': '74', 'name': '东营市人民医院', 'province': '山东省'}]
        body = '采购人：东营市人民医院本级\n采购人信息\n名称：东营市人民医院\n采购内容：软件建设'
        row, reason = self.extract(self.page(body, entities=entities))
        self.assertEqual(reason, '')
        self.assertEqual(row['招标单位'], '东营市人民医院')
        self.assertIn('本级', row['采购人依据'])
        row, reason = self.extract(self.page('采购人：东营市人民医院本级\n采购内容：软件建设', entities=entities))
        self.assertIsNone(row)
        self.assertIn('不匹配', reason)

    def test_complete_dual_labels_same_entity_ids_are_not_a_conflict(self):
        entities = [{'id': '75', 'name': '东营市中医院（东营市胜利医院）', 'province': '山东省'}]
        body = '采购人：东营市中医院\n招标人：东营市胜利医院\n采购内容：软件建设'
        row, reason = self.extract(self.page(body, entities=entities))
        self.assertEqual(reason, '')
        self.assertEqual(row['医院ID'], '75')
        self.assertIn('同一组', row['采购人依据'])

    def test_distinct_buyer_entity_ids_remain_conflict(self):
        body = '采购人：苏州市示范人民医院\n招标人：苏州市另一人民医院\n采购内容：软件建设'
        row, reason = self.extract(self.page(body))
        self.assertIsNone(row)
        self.assertIn('冲突', reason)

    def test_group_and_branch_label_not_reconciled_with_parent(self):
        for other in ['苏州市示范医疗集团', '苏州市示范人民医院南院区', '示范医院']:
            with self.subTest(other=other):
                body = '采购人：苏州市示范人民医院\n招标人：' + other + '\n采购内容：软件建设'
                row, reason = self.extract(self.page(body, entities=self.entities[:1]))
                self.assertIsNone(row)
                self.assertIn('冲突', reason)

    def test_body_procurement_subject_without_label(self):
        row, reason = self.extract(self.page('苏州市示范人民医院拟对网络安全系统开展采购，欢迎合格供应商参与。\n项目编号：SZ-2026-101'))
        self.assertEqual(reason, '')
        self.assertEqual(row['医院ID'], '11')
        self.assertIn('采购主体原文', row['采购人依据'])

    def test_explicit_external_buyer_overrides_matching_title(self):
        title = '苏州市示范人民医院网络安全系统采购公告'
        row, reason = self.extract(self.page('采购人：南京市外部医院\n采购内容：网络安全系统建设', title=title))
        self.assertIsNone(row)
        self.assertIn('不匹配入口医院', reason)

    def test_listing_date_prefix_and_procedural_buyer_mentions(self):
        body = '报价应考虑招标单位\n的规章管理制度。除非招标人\n同意，不得向第三方透露。\n采购内容：网络安全系统建设'
        row, reason = self.extract(self.page(body, title='2026-11-02 苏州市示范人民医院网络安全系统采购公告'))
        self.assertEqual(reason, '')
        self.assertEqual(row['医院ID'], '11')
        self.assertEqual(row['招标单位'], '苏州市示范人民医院')

    def test_branch_never_matches_parent_alias(self):
        entities = [{'id': '21', 'name': '苏州市示范人民医院（南院区）', 'province': '江苏省', 'aliases': ['苏州市示范人民医院']}]
        row, reason = self.extract(self.page('采购人：苏州市示范人民医院\n采购内容：网络安全系统建设', entities=entities))
        self.assertIsNone(row)
        self.assertIn('不匹配入口医院', reason)

    def test_parent_title_does_not_absorb_branch(self):
        row, reason = self.extract(self.page('采购内容：网络安全系统建设\n报名和采购要求请阅读文件。', title='苏州市示范人民医院（南院区）网络安全系统采购公告'))
        self.assertIsNone(row)
        self.assertIn('未取得', reason)

    def test_unparenthesized_branch_does_not_match_parent_alias(self):
        entities = [{'id': '21', 'name': '苏州市示范人民医院南院区', 'province': '江苏省', 'aliases': ['苏州市示范人民医院']}]
        row, reason = self.extract(self.page('采购人：苏州市示范人民医院\n采购内容：网络安全系统建设', entities=entities))
        self.assertIsNone(row)
        self.assertIn('不匹配入口医院', reason)

    def test_exact_verified_alias_keeps_original_roster_ids(self):
        entities = [{'id': '31', 'name': '苏州市原名人民医院', 'province': '江苏省', 'aliases': ['苏州市示范人民医院']},
                    {'id': '32', 'name': '苏州市示范人民医院', 'province': '江苏省'}]
        row, reason = self.extract(self.page('采购人：苏州市示范人民医院\n采购内容：网络安全系统建设', entities=entities))
        self.assertEqual(reason, '')
        self.assertEqual(row['医院ID'], '31；32')

    def test_fujian_province_from_entity_not_hospital_name(self):
        entities = [{'id': '41', 'name': '示范专科医院', 'province': '福建省'}]
        row, reason = self.extract(self.page('采购人：示范专科医院\n采购内容：网络安全系统建设', entities=entities))
        self.assertEqual(reason, '')
        self.assertEqual(row['省份'], '福建省')

    def test_complete_dual_roster_name_matches_one_explicit_name(self):
        entities = [{'id': '51', 'name': '上海市儿童医院（上海交通大学医学院附属儿童医院）', 'province': '上海市'}]
        row, reason = self.extract(self.page('采购单位：上海市儿童医院 采购项目：桌面管理软件维保\n采购内容：软件升级维护', entities=entities))
        self.assertEqual(reason, '')
        self.assertEqual(row['医院ID'], '51')
        self.assertEqual(row['招标单位'], '上海市儿童医院')
        self.assertIn('双挂牌', row['采购人依据'])

    def test_explicit_dual_buyer_matches_named_roster_hospital(self):
        entities = [{'id': '52', 'name': '东营市中医院', 'province': '山东省'}]
        row, reason = self.extract(self.page('三、采购人：东营市中医院(东营市胜利医院）\n采购内容：网络安全系统建设', entities=entities))
        self.assertEqual(reason, '')
        self.assertEqual(row['医院ID'], '52')

    def test_verified_single_hospital_self_procurement(self):
        page = self.page('我院拟对网络安全系统开展公开采购，欢迎具备条件的供应商参加。', entities=self.entities[:1])
        page['listing_url'] = 'https://example.org/procurement/'
        row, reason = self.extract(page)
        self.assertEqual(reason, '')
        self.assertEqual(row['医院ID'], '11')
        self.assertIn('我院拟', row['采购人依据'])
        self.assertIn(page['listing_url'], row['采购人依据'])

    def test_shared_entry_self_procurement_stays_unattributed(self):
        page = self.page('我院拟对网络安全系统开展公开采购，欢迎具备条件的供应商参加。')
        page['listing_url'] = 'https://example.org/procurement/'
        row, reason = self.extract(page)
        self.assertIsNone(row)
        self.assertIn('未取得', reason)

    def test_unverified_or_cross_domain_self_procurement_rejected(self):
        for verified, listing in [(False, 'https://example.org/list/'), (True, 'https://other.org/list/')]:
            with self.subTest(verified=verified, listing=listing):
                page = self.page('我院拟对网络安全系统开展公开采购，欢迎具备条件的供应商参加。', entities=self.entities[:1])
                page.update(entrance_verified=verified, listing_url=listing)
                row, reason = self.extract(page)
                self.assertIsNone(row)

    def test_clipped_title_restored_from_main_heading(self):
        page = self.page('采购人：苏州市示范人民医院\n采购内容：软件建设维护', title='医院网络安全系统升级服务比价结果公告')
        page['title'] = '医院网络安全系统升级服务'
        page['procurement_context'] = True
        row, reason = self.extract(page)
        self.assertEqual(reason, '')
        self.assertEqual(row['项目名称'], '医院网络安全系统升级服务比价结果公告')

    def test_navigation_heading_cannot_replace_non_notice_title(self):
        page = self.page('采购人：苏州市示范人民医院\n采购内容：软件建设维护', title='医院网络安全知识介绍')
        path = Path(page['raw_path'])
        path.write_bytes(path.read_bytes().replace(b'<article>', '<h2>医院网络安全知识介绍采购公告</h2><article>'.encode()))
        page['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        page['procurement_context'] = True
        row, reason = self.extract(page)
        self.assertIsNone(row)
        self.assertEqual(reason, '未确认是采购公告')

    def test_numbered_procurement_sections_are_not_conflicting_titles(self):
        page = self.page('采购人：苏州市示范人民医院\n采购内容：软件建设维护')
        path = Path(page['raw_path'])
        raw = path.read_bytes().replace('<h1>网络安全系统采购公告</h1>'.encode(), '<div>网络安全系统采购公告</div><h2>五、评审专家（单一来源采购人员）名单</h2>'.encode())
        raw = raw.replace('<title>网络安全系统采购公告</title>'.encode(), '<title>全国公共资源交易平台</title>'.encode())
        path.write_bytes(raw)
        page['sha256'] = hashlib.sha256(raw).hexdigest()
        row, reason = self.extract(page)
        self.assertEqual(reason, '')
        self.assertEqual(row['医院ID'], '11')

    def test_date_unknown_stays_excluded(self):
        row, reason = self.extract(self.page('采购人：苏州市示范人民医院\n采购内容：网络安全系统建设', dated=False))
        self.assertIsNone(row)
        self.assertIn('未取得明确发布日期', reason)

    def test_award_amount_not_filled_from_budget(self):
        row, reason = self.extract(self.page('采购人：苏州市示范人民医院\n预算金额：100万元\n采购内容：网络安全系统建设'))
        self.assertEqual(reason, '')
        self.assertIsNone(row['中标金额（万元）'])

    def test_sha_mismatch_excluded(self):
        page = self.page('采购人：苏州市示范人民医院\n采购内容：网络安全系统建设')
        page['sha256'] = '0' * 64
        row, reason = self.extract(page)
        self.assertIsNone(row)
        self.assertIn('SHA256', reason)

    def test_opaque_challenge_body_is_not_an_announcement(self):
        page = {'url': 'https://example.org/news/1002.html', 'title': '苏州市示范人民医院网络安全系统采购公告',
                'text': "var arg1='1234567890';" + 'aG9zcGl0YWw=' * 100,
                'hospital_entities': self.entities, 'date': '2026-11-02', 'date_basis': 'exact_listing_row'}
        row, reason = self.extract(page)
        self.assertIsNone(row)
        self.assertIn('挑战页', reason)

    def test_body_only_digital_subject_requires_matching_scope_review(self):
        page = self.page('采购人：苏州市示范人民医院\n采购内容：\n采购服务器和软件授权，提供部署服务。', title='设备购置采购公告')
        row, reason = self.extract(page)
        self.assertIsNone(row)
        self.assertIn('逐条业务复核', reason)
        review = {'url': page['url'], 'raw_sha256': page['sha256'], 'decision': 'keep',
                  'quote': '采购服务器和软件授权，提供部署服务。'}
        row, reason = self.extract(page, review)
        self.assertEqual(reason, '')
        self.assertIn('原文逐条复核', row['数字化标签'])

    def test_observed_amount_label_variants(self):
        for text, expected in [
            ('供应商名称：示范科技有限公司\n中标金额：123.45（万元）', 123.45),
            ('供应商名称：示范科技有限公司\n中标（成交）金额(元)：报价：4276500（元）', 427.65),
            ('供 应商名称：示范科技有限公司\n成交 金额：139000.00元', 13.9),
            ('供应商名称：示范科技有限公司\n中标（成交）价：小写：64800.00元', 6.48),
            ('供应商名称：示范科技有限公司\n中标/成交金额：3098000元', 309.8),
            ('供应商名称：示范科技有限公司\n成交金额：大写：壹拾伍万陆仟柒佰元整；小写：156700 .00 元。', 15.67),
        ]:
            with self.subTest(text=text):
                winner, amount, quote, gaps = e.award_details(text, '网络系统中标公告')
                self.assertEqual(winner, '示范科技有限公司')
                self.assertAlmostEqual(amount, expected)
                self.assertTrue(quote)

    def test_result_section_excludes_fee_and_appendix_pseudo_suppliers(self):
        text = ('三、中标（成交）信息\n供应商名称：真实科技有限公司\n中标金额：49.6万元\n'
                '四、主要标的信息\n名称：服务器\n六、代理服务费\n中标（成交）供应商\n七、公告期限\n'
                '八、附件\n成交供应商为中小企业的，应公告其《中小企业声明函》。')
        winner, amount, quote, gaps = e.award_details(text, '服务器中标公告')
        self.assertEqual(winner, '真实科技有限公司')
        self.assertEqual(amount, 49.6)

    def test_standalone_final_price_before_result_section(self):
        text = ('五、成交价格：62000元\n六、采购结果：经招标采购小组评定\n'
                '本项目中标单位为：江苏康凯通信技术有限公司')
        winner, amount, quote, gaps = e.award_details(text, '核心交换机维保成交公告')
        self.assertEqual(winner, '江苏康凯通信技术有限公司')
        self.assertEqual(amount, 6.2)
        self.assertIn('62000元', quote)
        self.assertIsNone(e.award_details('四、候选供应商报价\n' + text, '核心交换机维保成交公告')[1])

    def test_tender_quote_requires_explicit_final_award_section(self):
        quote = '中标金额(元)：投标报价：993000（元）'
        final = '三、中标信息\n1.中标结果：\n' + quote + '\n四、主要标的信息\n名称：预警平台'
        self.assertEqual(e.award_details(final, '预警平台中标结果公告')[1], 99.3)
        self.assertIn('投标报价：993000（元）', e.award_details(final, '预警平台中标结果公告')[2])
        self.assertIsNone(e.award_details(quote, '预警平台中标结果公告')[1])
        self.assertIsNone(e.award_details(final, '预警平台中标候选人公示')[1])
        self.assertIsNone(e.award_details('三、中标信息\n预算' + quote, '预警平台中标结果公告')[1])

    def test_result_announcement_requires_procurement_result_evidence(self):
        title = '医院信息化运维服务结果公告'
        body = ('采购人：苏州市示范人民医院\n三、采购结果\n供应商名称：示范科技有限公司\n'
                '中标（成交）金额：100万元\n四、主要标的信息\n信息化运维服务')
        row, reason = self.extract(self.page(body, title=title))
        self.assertEqual(reason, '')
        self.assertEqual(row['中标金额（万元）'], 100.0)
        for invalid in [body.replace('三、采购结果', '三、考核结果'),
                        body.replace('供应商名称：示范科技有限公司', '服务评价：优秀'),
                        body.replace('中标（成交）金额：100万元', '年度预算：100万元')]:
            with self.subTest(body=invalid):
                row, reason = self.extract(self.page(invalid, title=title))
                self.assertIsNone(row)
                self.assertEqual(reason, '未确认是采购公告')

    def test_umbrella_programme_name_is_not_it_scope(self):
        for item in ['高档四维彩色超声多普勒诊断仪', 'MRI(3.0T)核磁共振', '自动容积乳腺超声系统']:
            title = '福田区妇儿医院医疗配套设备及信息化建设项目' + item + '采购中标结果公告'
            with self.subTest(item=item):
                self.assertFalse(e.digital_evidence(title, title, '', '六、主要标的信息\n' + title, '', ''))
        title = '福田区妇儿医院医疗配套设备及信息化建设项目临床预警软件平台采购中标结果公告'
        self.assertIn('软件', e.digital_evidence(title, title, '', '六、主要标的信息\n临床预警软件平台', '', ''))

    def test_clinical_workflow_system_name_does_not_imply_ct_device(self):
        title = '移动CT卒中急救信息管理系统采购项目结果公告'
        self.assertNotIn('混合', e.digital_evidence(title, title, '', '', '', ''))
        device_title = 'CT设备及附带移动CT卒中急救信息管理系统采购项目结果公告'
        self.assertIn('混合', e.digital_evidence(device_title, device_title, '', '', '', ''))

    def test_medical_laser_fibre_is_not_communications_fibre(self):
        title = '一次性使用无菌医用激光光纤采购公告'
        self.assertFalse(e.digital_evidence(title, title, '', '', '', ''))
        self.assertIn('网络', e.digital_evidence(title + '及网络交换机', title, '', '', '', ''))

    def test_unaligned_amount_header_never_uses_row_number(self):
        text = '服务商名称\n成交价格（元）\n1\n示范科技有限公司\n70000'
        self.assertIsNone(e.award_details(text, '服务器中标公告')[1])

    def test_annual_price_keeps_period_and_does_not_become_contract_total(self):
        text = ('三、成交信息\n供应商名称：东软集团股份有限公司\n成交金额：798800.00 元 /年\n'
                '四、主要标的信息\n服务期：服务期3年，采用1+1+1模式，第一期合同期限1年。')
        winner, amount, quote, gaps = e.award_details(text, 'HIS运维成交公告')
        self.assertIsNone(amount)
        self.assertIn('/年', quote)
        self.assertTrue(any('1+1+1' in gap and '按年报价' in gap for gap in gaps))

    def test_header_and_procedural_phrases_never_become_winners(self):
        for fake in ['中标供应商地址', '采购数量', '社会信用代码', '七、公告期限', '中小企业的，应公告其《中小企业声明函》']:
            with self.subTest(fake=fake):
                winner, _, _, _ = e.award_details('供应商名称：' + fake, '服务器中标公告')
                self.assertEqual(winner, '')

    def test_qualification_cross_reference_does_not_append_contact_sections(self):
        text = ('二、申请人的资格要求：\n1.具有有效的安全生产许可证。\n三、获取招标文件\n时间：五个工作日。\n'
                '六、其他补充事宜\n未依照要求取得文件，不具备质疑权利，但因供应商资格条件或获取招标文件时间设置不符合规定的除外。\n'
                '七、联系方式\n采购代理机构信息：示范公司，电话025-12345678')
        got = e.section(text, e.QUAL_LABELS)
        self.assertIn('安全生产许可证', got)
        self.assertNotIn('025-12345678', got)
        self.assertNotIn('其他补充', got)
        self.assertNotIn('获取招标文件', got)

    @classmethod
    def saved_pages(cls):
        if not hasattr(cls, '_saved_pages'):
            root = Path(__file__).parent
            fixture = root.parent/'six-province-tenders-20261103'
            files = [fixture/'public/pages.json', fixture/'public/live-pages.json'] + list((fixture/'run/sites').glob('*/pages.json'))
            cls._saved_pages = {p['url']: p for f in files if f.is_file() for p in json.loads(f.read_text(encoding='utf-8-sig'))}
        return cls._saved_pages

    def test_observed_real_announcement_regressions(self):
        cases = [
            ('0044a350db5343984c2ca888f2b1298603f1', '广东骏思信息科技有限公司', 49.6495),
            ('0033f9734fe938f340459e44758178c42a89', '杭州网世科技有限公司', 427.65),
            ('0037c5213cfcccf144298d26fb6c83bc14a4', '创业慧康科技股份有限公司', 13.9),
            ('0031611a3d517d1c4ad89a560cb64ca649b1', '中国电信股份有限公司上海分公司', 2565.1419),
            ('00370b7b23deef1f4d8b81d3913d7bc4da01', '常州疆跃科技有限公司', 8.151),
            ('0044d9a8e03292da4b8cb55836fa3c0c85bc', '广东基准软件有限公司', 296.646),
            ('t20261016_27504137.htm', '中电鸿信信息科技有限公司', 309.8),
            ('dyszyy.com.cn/list_39/1968.html', '东营宝维信息科技有限公司', 11.1792),
            ('dyszyy.com.cn/list_39/1971.html', '东营大恒数码科技有限公司', 0.4796),
            ('dyszyy.com.cn/list_39/1970.html', '东营大恒数码科技有限公司', 0.905),
            ('jnspfbfzy.com/show/news-1361.html', '新潮睿石信息技术有限公司', 6.48),
            ('shchildren.com.cn/contents/641/12155.html', '南京中科华赛科技有限公司', None),
            ('0033d7f9576b6c864497aa5c51080f0c9723', '浙江网新健康科技有限公司', 99.3),
            ('00445efc1c7529624231a2bf73e9daf6e5e0', '北创动力（北京）科技发展有限公司', 100.0),
            ('0044de5d3d665a2e466689d5736b5354ecb8', '武汉在水医方智能科技有限公司', 159.98),
            ('0044276bf76c36104b67a5686a5a043090ea', '联通（广东）产业互联网有限公司', 137.6),
            ('00325fb76bb16bad4a8cab4fb5259970b9b0', '联通（江苏）产业互联网有限公司', None),
            ('hxkq.net/Tender/2025-03-21/2735.html', '江苏康凯通信技术有限公司', 6.2),
            ('jnspfbfzy.com/show/news-916.html', '山东松威电子工程有限公司', 15.67),
            ('dzsey.com/index.php?m=content&c=index&a=show&catid=216&id=3928', '山东安可质量检测有限公司', 7.0),
            ('shchildren.com.cn/contents/641/12153.html', '上海阿杰康德信息技术有限公司', None),
            ('shchildren.com.cn/contents/641/12146.html', '卫宁健康科技集团股份有限公司', None),
            ('qfsrmyy.com/wNewsView/?3623.html', '东软集团股份有限公司', None),
        ]
        pages = self.saved_pages()
        if not pages:
            self.skipTest('Task-local immutable announcement archive is not present')
        for fragment, winner, amount in cases:
            with self.subTest(url_fragment=fragment):
                page = next(p for url, p in pages.items() if fragment in url)
                row, reason = e.extract_one(page, Path(__file__).parent, 'digital')
                self.assertEqual(reason, '')
                self.assertEqual(row['中标单位'], winner)
                if amount is None:
                    self.assertIsNone(row['中标金额（万元）'])
                else:
                    self.assertAlmostEqual(row['中标金额（万元）'], amount)

    def test_observed_real_umbrella_clinical_lots_are_excluded(self):
        pages = self.saved_pages()
        if not pages:
            self.skipTest('Task-local immutable announcement archive is not present')
        for fragment in ['0044cff71df28efa4e1cbe6063caa12e6048', '004463b74ffdf3df4ff18206df778ee79678',
                         '0044aa076ea7c5534494abb6ce5d63631589', '0044927cd89038cb4af2be60c2bafc7e7bb3']:
            with self.subTest(url_fragment=fragment):
                page = next(p for url, p in pages.items() if fragment in url)
                row, reason = e.extract_one(page, Path(__file__).parent, 'digital')
                self.assertIsNone(row)
                self.assertIn('未确认采购标的', reason)

    def test_observed_real_qualification_boundary(self):
        pages = self.saved_pages()
        if not pages:
            self.skipTest('Task-local immutable announcement archive is not present')
        page = next(p for url, p in pages.items() if '003273c77a7d4206436bb818f50190778e54' in url)
        row, reason = e.extract_one(page, Path(__file__).parent, 'digital')
        self.assertEqual(reason, '')
        qualification = row['响应人资格要求（对供应商基本要求）']
        self.assertIn('安全生产许可证', qualification)
        self.assertNotIn('025-52875983', qualification)
        self.assertNotIn('获取招标文件', qualification)
        self.assertNotIn('代理机构信息', qualification)

    def test_observed_real_recommendations_do_not_supply_project_name(self):
        pages = self.saved_pages()
        if not pages:
            self.skipTest('Task-local immutable announcement archive is not present')
        page = next(p for url, p in pages.items() if 'xyfsy.com/article/2925.html' in url)
        row, reason = e.extract_one(page, Path(__file__).parent, 'digital')
        self.assertEqual(reason, '')
        self.assertIn('院感信息系统维保', row['项目名称'])
        self.assertNotIn('GPRS', row['项目名称'])

    def test_observed_table_headers_and_clinical_laser_scope(self):
        pages = self.saved_pages()
        if not pages:
            self.skipTest('Task-local immutable announcement archive is not present')
        expected = [('id=3928', 'SDDZ-DERMYYZBB-2026010'),
                    ('641/12153.html', '2026-ETLXXX-003 （第二次）'),
                    ('641/12146.html', '2026-ETLXXX-004')]
        for fragment, number in expected:
            with self.subTest(fragment=fragment):
                page=next(p for url,p in pages.items() if fragment in url)
                row,reason=e.extract_one(page,Path(__file__).parent,'digital')
                self.assertEqual(reason,'')
                self.assertEqual(row['项目编号'],number)
        page=next(p for url,p in pages.items() if 'wzyfy.cn/?m=home&c=View&a=index&aid=1115' in url)
        row,reason=e.extract_one(page,Path(__file__).parent,'digital')
        self.assertEqual(reason,'')
        self.assertIn('杀毒软件',row['项目名称'])
        self.assertNotEqual(row['项目名称'],'采购需求概况')
        page=next(p for url,p in pages.items() if '641/12159.html' in url)
        row,reason=e.extract_one(page,Path(__file__).parent,'digital')
        self.assertIsNone(row)

    def test_same_document_dedup_requires_all_identity_fields_and_ggzy(self):
        base={'网址':'https://www.ggzy.gov.cn/information/deal/html/a/310000/0202/20260101/a.html',
              '原文SHA256':'a'*64,'医院ID':'2；1','时间':'2026-01-01','项目名称':'医院网络项目',
              '公告类型':'中标或成交公告','项目编号':'A-01','采集来源':'历史留存原文',
              '原文路径':'archive/a.html','公告ID':'a','抓取时间':'2025-01-01','入口任务ID':'A'}
        alias=dict(base,网址='https://www.ggzy.gov.cn/his/information/deal/html/a/310000/0202/20260101/a.html',
                   医院ID='1；2',采集来源='本轮网络采集',公告ID='b',原文路径='archive/b.html',抓取时间='2026-11-03')
        rows,evidence=e.deduplicate_same_document([base,alias])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['公告ID'],'b')
        self.assertIn(base['网址'],rows[0]['采集来源'])
        self.assertEqual(evidence[0]['aliases'][0]['原文路径'],'archive/a.html')
        for field,value in [('原文SHA256','b'*64),('医院ID','3'),('时间','2026-01-02'),
                            ('项目名称','另一个项目'),('公告类型','更正公告'),('项目编号','A-02'),
                            ('网址','https://hospital.example/information/deal/html/a/notice.html')]:
            with self.subTest(field=field):
                changed=dict(alias);changed[field]=value
                self.assertEqual(len(e.deduplicate_same_document([base,changed])[0]),2)


if __name__ == '__main__':
    unittest.main()
