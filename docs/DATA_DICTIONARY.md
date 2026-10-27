# 字段与统计口径

## 三层数据

| 层级 | 主键/单位 | 内容 |
|---|---|---|
| 资料 | 页面请求记录、网页或PDF | pages.json包含成功和失败；records.json为原医疗技术规则筛出的资料 |
| 证据 | evidence_id | 原文片段、来源、行号/PDF页码、初步类型；一个网页可有多条 |
| 项目 | project_id | 填写者显式归并的项目，关联一条或多条evidence_ids |

线索不等于项目。原主题筛选未命中的成功页面也参与evidence，以保留健康服务/康养场景。复制已有采集时，collection/archive保存本次所用原文副本；import_provenance.json记录原目录、原pages哈希和副本文件哈希。

## 日期

- published_at：页面可识别的发布日期；未知留空，不使用URL年份、版权年份或采集时间代替。
- collected_at / fetched_at：采集时间；机器时间使用带时区ISO格式。
- event_date：填写者核验的项目事件日期；不会从published_at自动推断。
- reviewed_at：核验声明日期或时间；必须是有效ISO日期/时间。

publication口径过滤已知发布日期，保留未知页面并计数。event口径不据发布日期删原文；交付另算event_date_in_range_projects、event_date_out_of_range_projects、unknown_event_date_projects，未知日期不计入范围内，原项目列表不被删除。此统计仅匹配日期，不确认项目地域/场景/真实性。

## 线索类型

operational_claim为来源运行陈述；pilot为试点；collaboration为合作；product_release为产品/方案发布；plan为计划；uncertain为不确定或否定等。它们由规则提取，不是事实核查结果。

evidence_text为原文片段；paragraph_index是非空正文行号（排除PDF页码标记）；fragment_index是行内句子/窗口序号；pdf_page只来自显式页码；text_path/raw_path指向本次原文。evidence_id按来源、URL、位置与类型生成，用于同批次引用，不是跨任意重解析版本的永久ID。

## 项目台账

支持project_id、name、entity、product、application_org、location、event_date、stage、evidence_ids、review_status、reviewer、reviewed_at、notes。必填project_id/name/evidence_ids，缺失事实留空。多份原文涉及同一项目时由填写者合并，程序不根据相似名称自动合并。

| review_status | 含义 |
|---|---|
| pending | 待核验 |
| source_claim | 来源单方陈述 |
| corroborated | 填写者声明已交叉核验；需填写核验人/日期并引用不同来源及站点 |
| conflict | 来源或事实存在冲突 |
| insufficient_evidence | 证据不足 |

corroborated的结构检查不证明来源独立性或结论正确。不同主机可能属于同一集团，须阅读原文判断。程序不会自动把状态升级为已核实。

## 运行状态与统计

- completed：所选执行阶段完成；不是调研已完整或结论已核实。
- partial：存在失败、预算截断或其他执行缺口。
- failed：阶段执行失败或没有成功采集页。
- needs_input：继续操作需要补充明确输入。
- running：阶段正在执行，读取时结合lock_present判断，不自动抢锁。
- stale：上游变化后失效的旧阶段，必须重建后才能用于最新交付。

attempted_pages是不同请求页面记录数，不是底层HTTP总请求数（robots、重试、浏览器资源另有请求）。successful_pages与failed_pages按页面状态统计。record_count、evidence_count、project_count分别是资料筛选、线索、显式归并项目的数量。remaining_candidates为采集范围内尚待访问的候选，不代表企业全部资料。

review_queue中的linked只表示已关联项目，不等于已核验。delivery.analysis_status默认pending_gpt_synthesis；report.md/report.json是供GPT进一步分析的资料包。
