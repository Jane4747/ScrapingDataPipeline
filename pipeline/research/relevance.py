"""Explainable screening of equipment evidence and adjacent medical technology.

This is a retrieval filter, not a claim that a manufacturer or product is clinically
validated. Evidence must occur in the same short body passage; company names,
navigation labels and generic AI/health slogans are not sufficient.
"""

from __future__ import annotations

import re
import unicodedata


CATEGORY_TERMS = {
    "surgical_robotics": (
        "手术机器人", "腔镜机器人", "骨科机器人", "血管介入机器人", "穿刺机器人",
        "手术导航", "机器人辅助手术", "surgical robot", "surgical robotics", "robotic surgery",
        "surgical navigation", "robot-assisted surgery", "surgical robots", "surgical robotic system",
    ),
    "rehabilitation_exoskeleton": (
        "康复机器人", "康复外骨骼", "康复训练机器人", "rehabilitation robot",
        "rehabilitation robotics", "rehab robot", "rehabilitation robots", "rehab robots",
    ),
    "medical_imaging": (
        "医学影像设备", "医疗影像设备", "磁共振成像系统", "磁共振扫描", "超声诊断",
        "超声成像", "超声影像", "计算机断层扫描", "放射治疗系统", "医用直线加速器",
        "medical imaging equipment", "ultrasound imaging", "mri scanner", "ct scanner",
        "pet/ct", "pet/mr",
    ),
    "monitoring_diagnostics": (
        "监护仪", "心电图机", "除颤仪", "除颤监护", "呼吸机", "麻醉机", "输注泵",
        "血液分析仪", "血细胞分析仪", "血液细胞分析仪", "生化分析仪", "血糖仪",
        "生命体征监测", "可穿戴监测", "patient monitor", "vital sign", "ventilator",
        "defibrillator", "hematology analyzer", "infusion pump",
    ),
}
_GENERIC_EQUIPMENT = ("医疗装备", "医疗设备", "医疗器械", "医用设备", "medical device", "medical equipment")
_MEDICAL = (
    "医疗", "医学", "医院", "临床", "诊疗", "诊断", "患者", "病人", "康复", "照护",
    "医共体", "医联体", "病历", "手术", "healthcare", "medical", "clinical", "patient",
    "rehabilitation", "rehab", "hospital", "diagnostic", "surgical", "surgery",
)
_DETAIL = (
    "研发", "研制", "算法", "控制", "导航", "配准", "定位", "机械臂", "传感", "力控",
    "步态", "评估", "评测", "反馈", "临床", "试验", "训练", "检测", "监测", "采集",
    "成像", "分辨率", "重建", "探测器", "扫描", "剂量", "信号", "自动", "平台",
    "部署", "应用", "集成", "互联", "识别", "数据", "云端", "云存储", "云服务", "算力",
    "存储", "迁移", "传输", "超融合", "虚拟化", "模型", "隐私计算", "联邦学习",
    "algorithm", "sensor", "control", "navigation", "clinical", "training", "feedback",
    "imaging", "resolution", "scan", "reconstruction", "data", "deploy", "integration",
    "robotic", "develop", "gait", "force", "model", "cloud", "precision", "exoskeleton",
)
# Only concrete engineering features can borrow an equipment subject from the
# title. General corporate words such as R&D, application, data and platform
# would otherwise turn an unrelated mission statement into equipment evidence.
_TITLE_DETAIL = (
    "算法", "控制", "导航", "配准", "定位", "机械臂", "传感", "力控", "力反馈",
    "步态", "成像", "分辨率", "重建", "探测器", "扫描", "剂量", "信号",
    "临床验证", "临床试验", "algorithm", "sensor", "control", "navigation",
    "gait", "force", "imaging", "resolution", "reconstruction", "detector",
    "clinical trial", "clinical validation",
)
_SMART = (
    "智能", "机器人", "人工智能", "ai", "算法", "传感", "远程", "互联", "自动", "数字",
    "控制", "smart", "intelligent", "robot", "sensor", "digital", "automated",
)
_AI = (
    "人工智能", "ai", "大模型", "深度学习", "机器学习", "知识图谱", "自然语言",
    "智能诊断", "智能辅助", "智能体", "辅助诊断", "辅助决策",
    "artificial intelligence", "machine learning", "deep learning", "clinical decision support",
)
_CLOUD = (
    "医疗云", "医院云", "影像云", "云胶片", "云服务", "云计算", "云平台", "云存储",
    "私有云", "数据中心", "超融合", "医疗数据", "医学数据", "病历数据", "数据治理",
    "医疗大数据", "健康医疗大数据", "5g", "物联网", "远程医疗", "智慧医院", "互联互通",
    "cloud", "health data", "medical data", "hospital information", "telemedicine",
)
_HARDWARE = ("设备", "装备", "扫描仪", "探测器", "磁体", "射线", "探头", "扫描速度", "scanner", "detector", "hardware")
_EXOSKELETON = ("外骨骼", "exoskeleton")
_REHAB_CONTEXT = ("康复", "步态", "患者", "病人", "rehabilitation", "rehab", "patient", "gait", "therapy")
_MODALITY = ("医学影像", "医疗影像", "磁共振", "ct", "mri", "medical imaging")
_NAVIGATION = ("首页", "关于我们", "联系我们", "新闻中心", "加入我们", "招贤纳士", "隐私政策", "版权所有", "网站地图", "返回顶部")
_INDUSTRY_LIST = re.compile(r"(?:金融|交通|能源|教育|政务|工业)(?:[^。；\n]{0,25})医疗(?:[^。；\n]{0,25})(?:等行业|等领域|行业客户)")
_SPACE = re.compile(r"[\t \u3000]+")


def _contains(text: str, term: str) -> bool:
    # Latin abbreviations must not match inside e.g. retail, mail or interaction.
    if re.search(r"[a-z]", term):
        return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text, re.I) is not None
    return term in text


def _matches(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if _contains(text, term)]


def _passages(text: str) -> list[str]:
    """Keep paragraphs independent and cap context to 420 characters."""
    passages = []
    seen = set()
    for line in text.splitlines():
        line = _SPACE.sub(" ", line).strip()
        if not line or len(line) < 12:
            continue
        if sum(term in line for term in _NAVIGATION) >= 2:
            continue
        if (line.startswith(("版权所有", "Copyright", "copyright", "沪ICP备", "京ICP备"))
                or (line.count("|") >= 3 and not re.search(r"[。；.!?]", line))):
            continue
        # Long flattened documents are segmented at sentences before applying
        # the window so distant health and generic AI mentions cannot combine.
        sentences = re.split(r"(?<=[。！？!?；;])|(?<=\.)\s+", line)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 12:
                continue
            for start in range(0, len(sentence), 350):
                passage = sentence[start:start + 420]
                if len(passage) >= 12 and passage not in seen:
                    seen.add(passage)
                    passages.append(passage)
    return passages


def classify(title: str, text: str) -> dict:
    """Return relevance level, technical categories, keywords and short evidence.

    Categories and keyword lists preserve stable rule order. A title can clarify
    the first body passage only; a title alone never makes an empty page relevant.
    Up to five evidence excerpts (240 characters each) are returned.
    """
    if not isinstance(title, str) or not isinstance(text, str):
        raise TypeError("title and text must be strings")
    title = unicodedata.normalize("NFKC", title).strip()
    text = unicodedata.normalize("NFKC", text)
    passages = _passages(text)
    categories: list[str] = []
    matched_terms: list[str] = []
    evidence_candidates: list[tuple[bool, dict]] = []
    direct = False
    for index, passage in enumerate(passages):
        normalized = passage.lower()
        # A compact equipment title may supply the subject of a feature paragraph,
        # but must not contaminate all later, unrelated paragraphs.
        if index == 0 and len(title) <= 100 and _matches(normalized, _TITLE_DETAIL):
            title_has_equipment = any(_matches(title.lower(), terms) for terms in CATEGORY_TERMS.values())
            if title_has_equipment and title not in passage:
                passage = title + " — " + passage
                normalized = passage.lower()
        detail = _matches(normalized, _DETAIL)
        if not detail:
            continue
        local_categories: list[str] = []
        local_terms: list[str] = []
        local_direct = False
        for category, terms in CATEGORY_TERMS.items():
            hits = _matches(normalized, terms)
            if hits:
                local_categories.append(category)
                local_terms.extend(hits)
                local_direct = True
        medical = _matches(normalized, _MEDICAL)
        exoskeleton = _matches(normalized, _EXOSKELETON)
        rehab_context = _matches(normalized, _REHAB_CONTEXT)
        if exoskeleton and rehab_context and "rehabilitation_exoskeleton" not in local_categories:
            local_categories.append("rehabilitation_exoskeleton")
            local_terms.extend(exoskeleton + rehab_context)
            local_direct = True
        modality = _matches(normalized, _MODALITY)
        hardware = _matches(normalized, _HARDWARE)
        if modality and hardware and "medical_imaging" not in local_categories:
            local_categories.append("medical_imaging")
            local_terms.extend(modality + hardware)
            local_direct = True
        equipment = _matches(normalized, _GENERIC_EQUIPMENT)
        smart = _matches(normalized, _SMART)
        if equipment and smart and not local_direct:
            local_categories.append("intelligent_medical_equipment")
            local_terms.extend(equipment + smart)
            local_direct = True
        # A cloud/AI vendor merely enumerating healthcare among industries is not
        # medical-specific evidence. Dedicated passages still qualify separately.
        if medical and not _INDUSTRY_LIST.search(normalized):
            ai = _matches(normalized, _AI)
            cloud = _matches(normalized, _CLOUD)
            if ai:
                local_categories.append("medical_ai")
                local_terms.extend(ai + medical)
            if cloud:
                local_categories.append("medical_cloud_data")
                local_terms.extend(cloud + medical)
        if not local_categories:
            continue
        direct = direct or local_direct
        for category in local_categories:
            if category not in categories:
                categories.append(category)
        for term in local_terms + detail:
            if term not in matched_terms:
                matched_terms.append(term)
        if len(evidence_candidates) < 50 or (local_direct and not any(item[0] for item in evidence_candidates)):
            # Center the excerpt near its first primary hit and report only terms
            # present in that excerpt, keeping the explanation independently useful.
            primary = local_terms[0]
            pos = normalized.find(primary.lower())
            start = max(0, pos - 60)
            excerpt = passage[start:start + 240]
            excerpt_terms = list(dict.fromkeys(t for t in local_terms + detail if _contains(excerpt.lower(), t)))
            evidence_candidates.append((local_direct, {"text": excerpt, "terms": excerpt_terms}))
    relevance = "direct_equipment" if direct else "supporting_technology" if categories else "none"
    # Direct equipment evidence must remain visible even after many cloud/AI
    # passages at the beginning of a long corporate or sustainability report.
    evidence = [item for _, item in sorted(evidence_candidates, key=lambda item: not item[0])[:5]]
    return {"relevant": bool(categories), "relevance": relevance, "categories": categories,
            "matched_terms": matched_terms, "evidence": evidence}
