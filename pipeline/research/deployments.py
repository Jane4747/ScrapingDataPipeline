"""Build a conservative, offline deployment-claim index from saved crawl pages.

The rules retrieve source statements for human review; they do not establish
that an installation, deployment, or commercial result actually occurred.
Only Python's standard library is required, and input documents stay read-only.
"""

import csv
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re


TOPICS = {
    "医疗装备": ("医疗装备", "医疗设备", "医疗器械", "手术机器人", "医用机器人", "手术导航", "超声", "监护设备", "影像设备", "medical device", "surgical robot"),
    "智慧医疗": ("智慧医疗", "智慧医院", "数字医院", "互联网医院", "远程医疗", "医疗云"),
    "数字健康": ("数字健康", "智慧健康", "健康平台", "健康数据", "健康监测", "digital health", "onehealth"),
    "医疗健康服务": ("医院", "医疗", "诊疗", "健康管理", "健康服务", "公共卫生", "重症", "危重症", "病情", "临床", "护理", "medical", "hospital", "healthcare"),
    "康复辅助": ("康复", "外骨骼", "助行", "辅助行走", "rehabilitation", "exoskeleton"),
    "智慧康养": ("智慧康养", "智慧养老", "智能养老", "养老平台", "养老服务网", "智能照护", "智慧照护"),
    "医养与照护": ("康养", "养老", "医养", "照护", "照料", "eldercare", "elderly care"),
}

SIGNALS = {
    "operational_claim": ("投入运营", "已运营", "已经运营", "正在运营", "负责运营", "投入使用", "投入运行", "正式运营", "已应用", "已投运", "已投用", "正式投用", "部署", "落地", "上线", "建成", "启用", "开业", "installed", "deployed", "launched", "operational"),
    "pilot": ("试点", "试运行", "试用", "试验性应用", "示范应用", "临床试验", "试验验证", "pilot"),
    "collaboration": ("签署", "签约", "合作", "共建", "联合建设", "战略协议", "partnership", "collaboration"),
    "product_release": ("发布", "推出", "首发", "上市", "release", "unveil"),
    "plan": ("计划", "规划", "拟建", "拟开展", "拟部署", "拟推出", "拟发布", "拟合作", "拟投资", "将建设", "将打造", "布局", "筹建", "愿景", "plan to", "planned", "planning", "will deploy", "will launch"),
}

SIGNAL_LABELS = {
    "operational_claim": "运行或部署陈述", "pilot": "试点或试验", "collaboration": "合作线索",
    "product_release": "产品或方案发布", "plan": "计划或布局", "uncertain": "状态不确定",
}
NEGATION = re.compile(r"尚未|还未|暂未|未曾|没有|并未|未能|未予|未(?!来)|无法|不再|不具备|不能|不支持|not\b|never\b|no\s+longer", re.I)
FUTURE = re.compile(r"计划|规划|拟|未来|将|即将|预计|预期|有望|力争|争取|探索|旨在|希望|谋划|筹建|待|plan(?:ned|ning)?\b|will\b|intend\b|expected\b", re.I)
PRODUCT = re.compile(r"产品|设备|装备|器械|机器人|平台|系统|方案|模型|软件|仪器|服务|device|robot|platform|system|product|solution", re.I)
DOCUMENT = re.compile(r"报告|白皮书|蓝皮书|指南|倡议|榜单|政策|标准|新闻|report|white\s*paper", re.I)
PDF_MARKER = re.compile(r"^\s*\[第\s*(\d+)\s*页\]\s*$")
SENTENCES = re.compile(r"[^。！？!?\n]+(?:[。！？!?]+|$)")
NOISE = re.compile(r"人才招聘|社会招聘|校园招聘|招聘职位|职位要求|岗位职责|任职资格|招贤纳士|加入我们|版权所有|版权声明|隐私政策|法律声明|免责声明|cookie policy|privacy policy|all rights reserved", re.I)
FIELDNAMES = (
    "evidence_id", "source_run", "source_id", "source_name", "url", "title", "published_at", "collected_at",
    "paragraph_index", "fragment_index", "pdf_page", "evidence_text", "topic_tags", "signal_type",
    "matched_terms", "review_status", "evidence_basis", "text_file", "text_path", "raw_file", "raw_path",
)


def register(sub):
    parser = sub.add_parser("evidence", help="从已抓取原文生成待人工核验的医疗健康部署线索")
    parser.add_argument("--input-dir", type=Path, required=True, help="包含 pages.json 的已有采集目录")
    parser.add_argument("--output-dir", type=Path, help="默认：输入目录/deployment-index")
    parser.add_argument("--max-per-page", type=int, default=30, help="每个网页或整份 PDF 最多保留条数，默认 30")
    parser.add_argument("--proximity", type=int, default=100, help="领域词与动作词的最大字符间隔，默认 100")
    parser.add_argument("--since", help="可选最早发布日期 YYYY-MM-DD；日期未知页面仍保留")
    parser.add_argument("--until", help="可选最晚发布日期 YYYY-MM-DD，含当天；日期未知页面仍保留")
    parser.set_defaults(func=run)


def run(args):
    summary = build_index(args.input_dir, args.output_dir, max_per_page=args.max_per_page,
                          proximity=args.proximity, since=args.since, until=args.until)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["processed_pages"] else 2


def _occurrences(text, terms):
    found = []
    for term in terms:
        # English matches must not be substrings of unrelated English words.
        pattern = re.escape(term)
        if term.isascii():
            pattern = r"(?<![A-Za-z])" + pattern + r"(?![A-Za-z])"
        found.extend((match.start(), match.end(), term) for match in re.finditer(pattern, text, re.I))
    return found


def _distance(left, right):
    return max(0, max(left[0], right[0]) - min(left[1], right[1]))


def _classify_signal(text, start, end, kind):
    # Restrict modifiers to the nearby clause, retaining the preceding comma
    # clause for constructions such as "计划在三家医院试点，并部署机器人".
    before = text[max(0, start - 75):start]
    after = text[end:min(len(text), end + 20)]
    clause_before = re.split(r"[；;。！？!?]", before)[-1]
    clause_after = re.split(r"[，,；;。！？!?]", after)[0]
    current_clause = re.split(r"[，,]", clause_before)[-1]
    # A completed claim in a new comma clause is independent of an earlier
    # plan: "计划扩大医院覆盖，目前已部署设备". Without an explicit
    # completion marker, keep inherited scope: "规划试点，并部署设备".
    if (current_clause != clause_before and re.search(r"已(?:经)?", current_clause)
            and not FUTURE.search(current_clause)):
        clause_before = current_clause
    if NEGATION.search(clause_before[-35:]) or NEGATION.search(clause_after):
        return "uncertain"
    # Postposed dates/modifiers ("部署将于明年完成", "上线时间预计…")
    # also describe a future action. A following comma ends this context so
    # "已部署，未来计划扩大覆盖" can retain the completed source claim.
    if kind == "plan" or FUTURE.search(clause_before) or FUTURE.search(clause_after):
        return "plan"
    if re.search(r"是否|能否|可否|能够|可以|可$|支持|适用于|可用于|有助于|建议|应当|应$|may\b|can\b|could\b", clause_before[-35:], re.I) or re.search(r"[？?]", text):
        return "uncertain"
    if kind == "operational_claim":
        vicinity = clause_before[-30:] + text[start:end] + clause_after[:35]
        if re.search(r"试点|试运行|试用|示范应用|pilot", vicinity, re.I):
            return "pilot"
        # Statements about an agreement/announcement do not by themselves
        # demonstrate deployment. Prefer the conservative collaboration label.
        if re.search(r"合作协议|签约|签署|拟议|意向", clause_before):
            return "collaboration"
        if re.match(r"(?:的)?(?:方案|能力|技术|架构|服务)", clause_after) and not re.search(r"已|正式|完成", clause_before[-12:]):
            return "uncertain"
    if kind == "product_release":
        release_context = text[max(0, start - 15):min(len(text), end + 80)]
        if DOCUMENT.search(release_context) or not PRODUCT.search(release_context):
            return "uncertain"
    return kind


def extract_evidence(text, *, proximity=100):
    """Return source excerpts with conservative signal labels and locations.

    Paragraphs are numbered by nonempty physical text line (excluding saved
    PDF page markers). Sentences/windows within a line have a fragment index.
    PDF page numbers refer to the extraction's explicit page markers only.
    """
    if proximity < 0 or proximity > 500:
        raise ValueError("proximity 必须在 0—500 之间")
    result = []
    paragraph_index, pdf_page = 0, None
    for line in text.splitlines():
        if not line.strip():
            continue
        marker = PDF_MARKER.fullmatch(line)
        if marker:
            pdf_page = int(marker.group(1))
            continue
        paragraph_index += 1
        fragment_index = 0
        for sentence_match in SENTENCES.finditer(line):
            sentence = sentence_match.group().strip()
            if not sentence or NOISE.search(sentence):
                continue
            # Common navigation labels or list headings lack a full statement.
            if len(sentence) < 20 and not re.search(r"[。！？!?，,；;]|已|正式|完成|启动|投入", sentence):
                continue
            if len(re.findall(r"\s[|/>]\s", sentence)) >= 2:
                continue
            # Long unpunctuated text is windowed for a usable review excerpt.
            # Classification retains preceding sentence context via offset.
            for offset in range(0, len(sentence), 600):
                excerpt = sentence[offset:offset + 800]
                fragment_index += 1
                domains = [(start, end, term, tag) for tag, terms in TOPICS.items()
                           for start, end, term in _occurrences(excerpt, terms)]
                if not domains:
                    continue
                grouped = {}
                for kind, terms in SIGNALS.items():
                    for start, end, term in _occurrences(excerpt, terms):
                        absolute_start, absolute_end = offset + start, offset + end
                        # These are descriptions of channels or physical
                        # form factors, not deployment actions.
                        if term == "上线" and sentence[max(0, absolute_start - 1):absolute_end + 1] == "线上线下":
                            continue
                        if term == "落地" and re.match(r"式|支架|稳定器|灯|窗|镜|风扇|机柜", sentence[absolute_end:]):
                            continue
                        # Administrative directives are not equipment or
                        # service installations; ignore only this action.
                        if term == "部署" and re.search(r"(?:决策|工作|安排)$", sentence[max(0, offset + start - 8):offset + start]):
                            continue
                        nearby = [domain for domain in domains if _distance(domain, (start, end)) <= proximity]
                        if not nearby:
                            continue
                        signal = _classify_signal(sentence, offset + start, offset + end, kind)
                        group = grouped.setdefault(signal, {"terms": set(), "topics": set()})
                        group["terms"].add(term)
                        group["terms"].update(domain[2] for domain in nearby)
                        group["topics"].update(domain[3] for domain in nearby)
                for signal, group in grouped.items():
                    result.append({
                        "paragraph_index": paragraph_index, "fragment_index": fragment_index,
                        "pdf_page": pdf_page, "evidence_text": excerpt,
                        "topic_tags": sorted(group["topics"]), "signal_type": signal,
                        "matched_terms": sorted(group["terms"]),
                        "review_status": "待人工核验", "evidence_basis": "来源原文陈述",
                    })
                if offset + 800 >= len(sentence):
                    break
    return result


def _inside_file(root, reference):
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("缺少有效的原文文件路径")
    candidate = Path(reference)
    path = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if not path.is_relative_to(root):
        raise ValueError("原文文件路径超出 input-dir")
    if not path.is_file():
        raise ValueError("原文文件不存在或不是文件")
    return path


def csv_safe(value):
    """Keep imported spreadsheet cells literal, including whitespace prefixes."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = "、".join(map(str, value))
    if not isinstance(value, str):
        return value
    if value.lstrip(" \t\r\n\ufeff").startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def _write_json(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _md(value):
    return str(value or "").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _known_date(value):
    """Use only the saved publication field, never a URL or collection date."""
    match = re.search(r"(?<!\d)(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})(?:日)?(?!\d)", str(value or ""))
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def build_index(input_dir, output_dir=None, *, max_per_page=30, proximity=100, since=None, until=None):
    """Build one index while exclusively owning its otherwise empty directory.

    The post-lock check closes the race between an initial empty-directory
    check and another run completing. Exclusive file creation also protects
    files added by other applications while this run is processing input.
    """
    root = Path(input_dir).resolve()
    target = Path(output_dir).resolve() if output_dir else root / "deployment-index"
    if target == root or root.is_relative_to(target):
        raise ValueError("output-dir 必须是独立输出目录，不能为输入目录或其父目录")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError("输出目录非空或不是目录，请更换 --output-dir，避免覆写已有索引")
    target.mkdir(parents=True, exist_ok=True)
    lock = target / "evidence.lock"
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ValueError("输出目录正在使用，请更换 --output-dir，避免并发覆写") from exc
    try:
        with handle:
            handle.write(str(os.getpid()))
        if any(path != lock for path in target.iterdir()):
            raise ValueError("输出目录非空，请更换 --output-dir，避免覆写已有索引")
        return _build_index(root, target, max_per_page=max_per_page,
                            proximity=proximity, since=since, until=until)
    finally:
        # Only the run that successfully created the lock may remove it.
        lock.unlink(missing_ok=True)


def _build_index(input_dir, output_dir, *, max_per_page, proximity, since, until):
    """Read every successful page, including pages excluded from records.json."""
    if max_per_page < 1:
        raise ValueError("max_per_page 必须大于零")
    if proximity < 0 or proximity > 500:
        raise ValueError("proximity 必须在 0—500 之间")
    try:
        lower = date.fromisoformat(since) if since else None
        upper = date.fromisoformat(until) if until else None
    except (TypeError, ValueError):
        raise ValueError("since/until 必须使用有效的 YYYY-MM-DD 日期") from None
    if lower and upper and lower > upper:
        raise ValueError("since 不得晚于 until")
    root = Path(input_dir).resolve()
    target = Path(output_dir).resolve() if output_dir else root / "deployment-index"
    if target == root or root.is_relative_to(target):
        raise ValueError("output-dir 必须是独立输出目录，不能为输入目录或其父目录")
    pages = json.loads((root / "pages.json").read_text(encoding="utf-8-sig"))
    if not isinstance(pages, list) or any(not isinstance(page, dict) for page in pages):
        raise ValueError("pages.json 必须是页面对象列表")
    rows, errors, truncated, sources, skipped = [], [], [], {}, []
    unknown_date_pages = 0
    processed, matched_pages, matched_sources = 0, 0, set()
    for page in pages:
        source_id = str(page.get("source_id") or "")
        source_name = str(page.get("source_name") or "")
        source_key = (source_id, source_name)
        source = sources.setdefault(source_key, {
            "source_id": source_id, "source_name": source_name, "total_pages": 0,
            "successful_pages": 0, "processed_pages": 0, "matched_pages": 0,
            "evidence_count": 0, "truncated_pages": 0,
        })
        source["total_pages"] += 1
        if page.get("status") != "ok":
            continue
        source["successful_pages"] += 1
        url = page.get("url") or page.get("requested_url") or ""
        if NOISE.search(str(page.get("title") or "")) or re.search(r"/(?:careers?|jobs?|recruit(?:ment)?)(?:[/.?]|$)", url, re.I):
            skipped.append({"source_id": source_id, "url": url, "reason": "招聘或法律导航页面"})
            continue
        publication = _known_date(page.get("published_at"))
        if publication and ((lower and publication < lower) or (upper and publication > upper)):
            skipped.append({"source_id": source_id, "url": url, "reason": "已知发布日期不在所选范围", "published_at": page["published_at"]})
            continue
        try:
            text_path = _inside_file(root, page.get("text_file"))
            body = text_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append({"source_id": source_id, "url": url, "field": "text_file", "error": str(exc)})
            continue
        raw_path = None
        if page.get("raw_file"):
            try:
                raw_path = _inside_file(root, page["raw_file"])
            except (OSError, ValueError) as exc:
                errors.append({"source_id": source_id, "url": url, "field": "raw_file", "error": str(exc)})
        processed += 1
        unknown_date_pages += publication is None
        source["processed_pages"] += 1
        candidates = extract_evidence(body, proximity=proximity)
        if candidates:
            matched_pages += 1
            matched_sources.add(source_key)
            source["matched_pages"] += 1
        if len(candidates) > max_per_page:
            truncated.append({"source_id": source_id, "url": url, "candidate_count": len(candidates),
                              "retained_count": max_per_page, "omitted_count": len(candidates) - max_per_page})
            source["truncated_pages"] += 1
        for candidate in candidates[:max_per_page]:
            identity = f"{source_id}|{url}|{candidate['paragraph_index']}|{candidate['fragment_index']}|{candidate['signal_type']}"
            rows.append({
                "evidence_id": hashlib.sha256(identity.encode()).hexdigest()[:24],
                "source_run": str(root), "source_id": source_id, "source_name": source_name, "url": url,
                "title": page.get("title") or "", "published_at": page.get("published_at") or "",
                "collected_at": page.get("fetched_at") or page.get("collected_at") or "", **candidate,
                "text_file": text_path.relative_to(root).as_posix(), "text_path": str(text_path),
                "raw_file": raw_path.relative_to(root).as_posix() if raw_path else "",
                "raw_path": str(raw_path) if raw_path else "",
            })
            source["evidence_count"] += 1
    summary = {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_dir": str(root), "output_dir": str(target),
        "scope_note": "仅对已抓取成功页面的原文按近邻词规则检索；线索类型不等于实际落地结论，全部待人工核验。未命中不代表企业没有相关部署。",
        "source_count": len(sources), "total_pages": len(pages),
        "successful_pages": sum(page.get("status") == "ok" for page in pages),
        "processed_pages": processed, "matched_pages": matched_pages,
        "matched_source_count": len(matched_sources), "evidence_count": len(rows),
        "max_per_page": max_per_page, "proximity_characters": proximity,
        "since": since, "until": until, "unknown_publication_date_pages": unknown_date_pages,
        "date_note": "只用页面保存的 published_at 筛选，未知或无法解析日期默认保留；不根据 URL 或采集时间推算发布日期。",
        "skipped_pages": skipped,
        "truncated_page_count": len(truncated), "omitted_evidence_count": sum(item["omitted_count"] for item in truncated),
        "truncated_pages": truncated, "read_errors": errors,
        "signal_counts": {kind: sum(row["signal_type"] == kind for row in rows) for kind in SIGNAL_LABELS},
        "sources": list(sources.values()),
        "location_note": "paragraph_index 为非空正文行序号（不计 PDF 页码标记），fragment_index 为该行句子/窗口序号；pdf_page 只来自原文显式页码标记。",
    }
    target.mkdir(parents=True, exist_ok=True)
    _write_json(target / "deployment_evidence.json", rows)
    _write_json(target / "summary.json", summary)
    with (target / "deployment_evidence.csv").open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows({key: csv_safe(row.get(key)) for key in FIELDNAMES} for row in rows)
    lines = ["# 医疗健康部署线索索引", "", summary["scope_note"], "",
             f"已读取成功页面 {processed} 个，检出 {matched_pages} 个页面、{len(matched_sources)} 个企业/平台的 {len(rows)} 条线索。", "",
             "所有类型均表示来源原文的陈述；合作、发布、试点与规划分别保留，不能直接视为已实际部署。日期缺失时留空。", "",
             f"发布日期筛选：{since or '不限'} 至 {until or '不限'}；保留日期未知页面 {unknown_date_pages} 个，跳过 {len(skipped)} 个不合日期范围或招聘/法律页面。", "",
             f"每个网页或整份 PDF 最多保留 {max_per_page} 条；截断 {len(truncated)} 个页面，省略 {summary['omitted_evidence_count']} 条候选。完整原文及截断明细保留在文件引用和 summary.json 中。", "",
             "| 企业或平台 | 已读页面 | 有线索页面 | 线索数 |", "|---|---:|---:|---:|"]
    for source in sources.values():
        lines.append(f"| {_md(source['source_name'] or source['source_id'])} | {source['processed_pages']} | {source['matched_pages']} | {source['evidence_count']} |")
    lines += ["", "## 文件", "", "- [逐条原文线索（CSV）](deployment_evidence.csv)",
              "- [结构化线索（JSON）](deployment_evidence.json)", "- [覆盖、截断与读取异常（JSON）](summary.json)", "",
              "## 首批线索预览", ""]
    for row in rows[:15]:
        lines += [f"- **{_md(row['source_name'])}｜{SIGNAL_LABELS[row['signal_type']]}｜待人工核验**：{_md(row['evidence_text'])[:220]}",
                  f"  来源：<{row['url']}>；正文行 {row['paragraph_index']}" + (f"；PDF 第 {row['pdf_page']} 页" if row['pdf_page'] else "") + "。"]
    with (target / "deployment_index.md").open("x", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return summary
