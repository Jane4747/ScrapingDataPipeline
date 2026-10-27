"""Portable research records, coverage reports and optional spreadsheet export."""

from pathlib import Path

from .crawler import now, write_json

CATEGORY_LABELS = {
    "surgical_robotics": "手术与导航机器人", "rehabilitation_exoskeleton": "康复与外骨骼",
    "medical_imaging": "医疗影像装备", "monitoring_diagnostics": "监测与诊断装备",
    "intelligent_medical_equipment": "智能医疗装备", "medical_ai": "医疗人工智能",
    "medical_cloud_data": "医疗云与数据技术",
}


def export_results(results, output_dir, topic, deliveries=("json", "markdown")):
    output_dir = Path(output_dir)
    records = [record for result in results for record in result.get("records", [])]
    records.sort(key=lambda row: (row["source_id"], row.get("relevance", ""), row.get("title", "")))
    pages = [dict(page, source_id=result["source_id"], source_name=result["source_name"])
             for result in results for page in result.get("pages", [])]
    failures = [page for page in pages if page["status"] != "ok"]
    coverage = []
    for result in results:
        source_pages = result.get("pages", [])
        coverage.append({
            "source_id": result["source_id"], "source_name": result["source_name"],
            "status": result["status"], "attempted_pages": len(source_pages),
            "successful_pages": sum(page["status"] == "ok" for page in source_pages),
            "relevant_records": len(result.get("records", [])),
            "direct_equipment": sum(row["relevance"] == "direct_equipment" for row in result.get("records", [])),
            "supporting_technology": sum(row["relevance"] == "supporting_technology" for row in result.get("records", [])),
            "remaining_candidates": result.get("remaining_candidates", 0),
            "stop_reason": result.get("stop_reason", "source_error"),
            "error": result.get("error", ""),
        })
    status = "failed" if not any(row["successful_pages"] for row in coverage) else (
        "partial" if any(row["status"] != "completed" for row in coverage) else "completed")
    manifest = {
        "schema_version": 1, "topic": topic, "generated_at": now(), "status": status,
        "scope_note": "按配置入口、域名、页数及深度上限采集；未命中不代表该平台没有相关研究。",
        "source_count": len(coverage), "attempted_pages": len(pages),
        "successful_pages": sum(row["successful_pages"] for row in coverage),
        "failed_pages": len(failures), "record_count": len(records), "sources": coverage,
    }
    # Machine-readable records and coverage are also the audit contract of Markdown-only runs.
    for name, value in (("records.json", records), ("manifest.json", manifest),
                        ("pages.json", pages), ("failures.json", failures)):
        write_json(output_dir / name, value)
    if "markdown" in deliveries:
        (output_dir / "research.md").write_text(render_markdown(manifest, records, failures), encoding="utf-8")
    if "excel" in deliveries:
        import pandas as pd
        flat = []
        for record in records:
            row = dict(record)
            row["categories"] = "、".join(row["categories"])
            row["matched_terms"] = "、".join(row["matched_terms"])
            row["evidence"] = "\n".join(item["text"] for item in row["evidence"])
            flat.append(row)
        with pd.ExcelWriter(output_dir / "research.xlsx", engine="xlsxwriter",
                            engine_kwargs={"options": {"strings_to_formulas": False, "strings_to_urls": False}}) as writer:
            pd.DataFrame(flat).to_excel(writer, sheet_name="资料", index=False)
            pd.DataFrame(coverage).to_excel(writer, sheet_name="平台覆盖", index=False)
            pd.DataFrame([{key: page.get(key) for key in ("source_name", "requested_url", "status", "error")}
                          for page in failures]).to_excel(writer, sheet_name="采集失败", index=False)
    return manifest


def safe(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def render_markdown(manifest, records, failures):
    lines = [f"# {manifest['topic']}资料索引", "", manifest["scope_note"], "",
             f"采集时间（UTC）：{manifest['generated_at']}；平台 {manifest['source_count']} 个；"
             f"成功页面 {manifest['successful_pages']}；失败页面 {manifest['failed_pages']}；"
             f"相关资料 {manifest['record_count']} 条。", "",
             "## 平台覆盖", "", "| 平台 | 成功页面 | 装备直接相关 | 医疗数字技术相关 | 状态 |",
             "|---|---:|---:|---:|---|"]
    for source in manifest["sources"]:
        lines.append(f"| {safe(source['source_name'])} | {source['successful_pages']} | {source['direct_equipment']} | "
                     f"{source['supporting_technology']} | {source['status']} |")
    for level, label in (("direct_equipment", "装备直接相关"), ("supporting_technology", "医疗数字技术相关")):
        lines += ["", f"## {label}", ""]
        selected = [record for record in records if record["relevance"] == level]
        if not selected:
            lines.append("本次采集未获得符合规则的资料。")
        for record in selected:
            title = safe(record["title"] or record["url"]).replace("[", "\\[").replace("]", "\\]")
            lines += [f"### {safe(record['source_name'])} · {title}", "",
                      f"来源：<{record['url']}>", "",
                      f"发布日期：{record.get('published_at') or '页面未提供可识别日期'}；"
                      f"技术分类：{'、'.join(CATEGORY_LABELS.get(category, category) for category in record['categories'])}；"
                      f"命中词：{'、'.join(record['matched_terms'])}。", ""]
            for evidence in record["evidence"][:2]:
                lines.append(f"> {safe(evidence['text'])[:350]}")
                lines.append("")
            lines += [f"[本地正文]({record['text_file']})", ""]
    if failures:
        lines += ["## 未成功采集的页面", "", "失败、禁止访问、空正文等均单独记录，不作为企业技术能力的判断依据。", ""]
        for page in failures:
            lines.append(f"- {safe(page['source_name'])}：{page['status']}，{safe(page.get('error', ''))}；<{page['requested_url']}>")
    return "\n".join(lines) + "\n"
