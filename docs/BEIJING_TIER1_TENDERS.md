# 北京一级医院数智化招采采集

本轮范围：提供的医院清单“03-一级医院”251家，2024-01-01至2026-10-27。后续任务须显式传入自己的起止日期。客户标签仅使用该清单的等级、类别和区县，不推断举办主体或运营商归属。

新增 `scripts/tender_tools.py` 复用现有任务流水线进行原文归档，不另建网络爬虫。公开公告的候选链接由真实检索导入；脚本不会把检索计划当作已经完成的搜索。

## 操作

1. 用 `python -B scripts/tender_tools.py prepare --workbook <医院清单.xlsx> --output <hospitals.json>` 提取检索名录。
2. 搜索并保存候选 JSON 数组，每条至少包含 `url`；保留查询词和未命中医院记录。使用医院全称、原名及官方确认的别名检索。
3. 用 `python -B scripts/tender_tools.py plan --candidates <candidates.json> --output <新目录> --task-id <新任务名> --since 2024-01-01 --until 2026-10-27` 生成采集任务和精确域名白名单。
4. 对生成的 task.json 先执行 `run-local.ps1 task --spec <task.json> --output-root <输出目录> --dry-run --json`，再去掉 `--dry-run` 执行同一任务。只运行 collection 阶段；页面正文与失败记录沿用现有流水线。
5. 阅读原文，填写记录后执行 `python -B scripts/tender_tools.py export --roster <hospitals.json> --records <records.json> --output <导出目录> --since 2024-01-01 --until 2026-10-27`。生成七列 CSV、通过字段校验的 JSON、待核 JSON。校验通过只表示字段口径符合要求，不等于程序核实事实。

## 记录结构

每行一份公告中的一个采购包。记录字段：`hospital_id, project_name, product, purchaser, winner, amount_wan, amount_quote, date, announcement_type, url, quote`。可选：`project_number, package, source_note`。

- date 必须为公告正文日期，不用抓取日、搜索引擎相对日期或 URL 年份替代。
- `amount_wan` 仅填明确人民币成交总额；预算、最高限价、候选报价不填此列。`amount_quote` 保存金额原文及单位。原值转万元使用 Decimal，元除以10000，保留分的精度。
- 招标公告、采购意向中的 winner 与 amount_wan 留空；单一来源拟定供应商不当作实际中标人。
- 同一项目的招标和结果公告分别保留，并按项目编号关联；不能直接对所有公告行加总项目数或金额。
- 无法取得完整公告、日期未知、付费遮挡、对象关系不清的材料放候选清单，不补猜金额或供应商。
- `quote` 留足支撑本行字段的正文片段，`source_note` 注明官方原文/公开转载、未披露字段和主体关系。
- 仅包含医疗数智化系统、软件、数据、AI、云、网络通信、安全及其配套和运维。混合工程或服务只有在正文/附件明确含网络、信息系统、数据接口等内容时纳入，并标明混合性质；不推算数字部分金额。设备名称含“数字”“系统”不自动满足范围。

## 扩词与执行留痕

词表位于 `configs/beijing_tier1_keywords_v2.json`：11组、277个去重主题词。每院至少6组基础查询，命中后按别名、上级采购单位、年份和具体产品补查。它是检索配置，不是自动执行证明。

本轮1629条逐院查询由会话中的搜索工具真实执行，另有28条专项查询。`tender_tools plan`只把已定位网址交给现有网页采集器；默认`discovery provider=plan`也只生成计划。仓库不能仅靠这个词表自动复现会话搜索服务。

## 离线审计

```powershell
python -B scripts/tender_audit.py --input-dir outputs/beijing-tier1-rerun-20261027 --output outputs/beijing-tier1-rerun-20261027/delivery_audit.json --min-queries 6
```

输入目录须含 `hospital_roster.json`、`hospital_search_log.json`、`records.validated.json`、`candidate_notices.json`、`collection_scope.json` 及其引用证据文件。每条检索日志提供 `hospital_id`、`queries`、`evidence_files`；原始JSON返回中须保留实际查询字符串。记录证据路径必须留在输入目录内。命令核对名单覆盖、查询留痕、字段、日期、计数及文件存在，发现问题返回2；通过返回0。候选可以缺日期或金额，不因此自动转为正式记录。

`scripts/beijing_tenders.py` 是独立的实验性门户发现/抽取入口，未用于本轮1629条检索。其自动抽取不构成事实核验，正式导出须提供医院名单及逐条核验声明，再通过`tender_tools`规则；网络可用性仍需针对实际站点验证。

离线测试：`python -B -m unittest discover -s tests -p test_tender_tools.py -v`。测试不能替代真实网络采集验证。
