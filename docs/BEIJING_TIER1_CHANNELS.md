# 北京一级医院渠道补查用法

此流程复用已有搜索和人工核验记录，离线合并与审计。它不会重新搜索医院，不会登录采购平台，也不会把候选人报价转换成中标金额。

## 本机目录

- outputs/beijing-tier1-rerun-20261027：上一轮251家名单、逐院日志、14条主表和28条候选。
- outputs/beijing-hospital-channel-input-20261027：本轮central/beijing/enterprise/root分组输入、证据与review_decisions。
- outputs/beijing-hospital-channel-supplement-20261027：已交付16条主表、30条候选、149条补查查询及工作簿。
- outputs/beijing-hospital-channel-code-20261027：一次性历史脚本和哈希清单。

## 合并已有核验资料

```powershell
python -B scripts/tender_channel_merge.py --base-dir outputs/beijing-tier1-rerun-20261027 --supplement-dir outputs/beijing-hospital-channel-input-20261027 --output-dir outputs/channel-replay-new --since 2024-01-01 --until 2026-10-27
python -B scripts/tender_audit.py --input-dir outputs/channel-replay-new --output outputs/channel-replay-audit.json --min-queries 6
```

output-dir必须不存在。上一次已经使用的输出目录不能重复覆盖。JSON结果给出新旧统计；非零退出码表示校验或执行失败。没有inputs和evidence的公开仓库不能自行复现这批研究事实，可用离线测试验证通用逻辑。

base至少包含hospital_roster.json、hospital_search_log.json、records.validated.json、candidate_notices.json、collection_scope.json及引用证据。supplement每组需records_GROUP.json、candidates_GROUP.json、search_GROUP.json；可选review_decisions.json。证据路径必须相对输入目录且不得逃逸。查询文本要能在所引JSON证据中找到。

## 可选工作簿制作

需要外部已配置的Node和@oai/artifact-tool运行时。不会自动安装；本仓库基础Python依赖不含此库。

```powershell
node scripts/build_tender_workbook.mjs outputs/channel-replay-new outputs/channel-preview-new
python -B scripts/finalize_tender_workbook.py --book outputs/channel-replay-new/北京一级医院数智化招采_渠道补查版.xlsx --links-file outputs/channel-preview-new/hyperlinks.json --output outputs/channel-replay-new/北京一级医院数智化招采_带链接.xlsx
```

制作脚本输出工作簿及预览，仍须检查金额、空值和视觉排版。链接工具只写新文件，不能用输入原路径作为输出。普通Python环境可直接使用合并脚本产出的七列CSV和JSON。

## 需要新增网络采集时

继续使用仓库既有v1任务协议：check检查依赖，task --dry-run校验，再执行同一任务。plan只生成查询；搜索工具真实返回必须另行保存，才能计入执行数。新增来源或时间范围建立新任务。不要通过禁用robots、关闭TLS证书验证或绕过验证码补数据。

需要补的是扫描内容时，应保存附件和页码，再执行OCR或人工视觉核验；需要补的是日期、采购使用医院或技术参数时，应追溯相应原公告及附件。已成功读取但未披露的字段保持为空。
