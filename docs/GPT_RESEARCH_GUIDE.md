# GPT调研调用指南

## 从需求到任务

1. 从用户要求提取研究问题、对象、来源、地域/场景、时间范围、输出格式与可接受的采集预算。不要把未说明的信息写成确定条件。
2. 判断已有资料是否足以复用。使用 `collection.mode=existing` 时，任务会复制所选来源的原文和元数据到独立任务目录，保留导入来源及文件哈希，不改动旧资料。
3. 新抓取使用 `collection.mode=crawl` 和 `allow_network=true`。程序仍受域名、页数、深度、体积、robots及请求间隔约束。
4. 将任务保存到独立JSON文件。先dry-run校验，再执行；通过返回值读取实际输出目录。

### 三个示例

- `tasks/example_search_plan.json`：21个来源的检索计划，完全离线，不会自动取得搜索结果。
- `tasks/example_health_research.json`：复用本机已有2026-10-22采集，生成部署线索与待核验资料包；没有该旧目录时需修改input_dir。
- `tasks/example_live_collection.json`：迈瑞、微创两来源的有限联网采集。它只使用现有种子，不会因为生成了计划就声称已执行搜索。

在代码库目录打开PowerShell：

```powershell
.\run-local.ps1 check --profile research --json
.\run-local.ps1 task --spec tasks\example_search_plan.json --dry-run --json
.\run-local.ps1 task --spec tasks\example_search_plan.json --json
```

复制示例后更换task_id、日期和研究问题。相对路径以JSON文件所在目录解析，output-root以命令调用时目录解析；启动器固定在代码库目录运行。

## 搜索候选与来源边界

`discover`生成检索式、可点击搜索入口及候选配置。由GPT可用的搜索工具取得网址后，将它们写为 `[{"source_id":"mindray","url":"https://...","title":"...","query":"..."}]`，在新任务的discovery.import_results指定该文件。

候选仅能进入对应来源的域名白名单。医院、政府、采购及交易所应作为独立来源加入自定义配置，不能为方便跳转而放开任意域名。新增来源配置需要新任务。

自定义 `topic_profile` 指向版本1 JSON，其中query_topics是1..30条 `{purpose, terms}`。它只修改搜索计划；医疗相关性和部署线索仍由现有医疗规则提取。地域和场景保留在任务/报告，须在项目核验时逐条检查。

使用Brave时显式指定provider=brave、allow_network=true及api_budget（1..30）。密钥只从BRAVE_SEARCH_API_KEY读取。预算是该发现阶段的请求上限，不意味着整个计划已搜索完。中断的付费搜索不会自动重新发起；检查状态后另建明确预算的新任务。

## 如何阅读结果

1. 先读命令返回的status、warnings和各阶段counts，遇到partial检查采集manifest/failures、未搜索查询、被截断的证据以及读取异常。
2. 从 `evidence` 的deployment_evidence.json读取原文片段、来源网址、原文行号/PDF页码、发布日期和抓取时间。不要仅凭自动标签写结论。
3. `review`默认projects为空并产生review_queue和review_template。逐条核实后，在模板projects中显式归并同一项目，引用evidence_ids。
4. 企业法人、应用机构、产品、地点、金额和事件日期不得从相近词语猜测。当前台账可记录主体、产品、机构、地点和事件日期；额外金额等事实先写带证据的notes，后续需要时再扩展版本化字段。
5. 核验人可记录实际执行者（研究人员或明确标识的GPT辅助核验），不要把自动规则写成人工核验。所有review_status都属于填写者声明。
6. 最后读取delivery/report.json或report.md，综合成用户要求的研究报告。机器资料包本身不包含自动确认的研究结论。

## 继续任务与提交核验

```powershell
.\run-local.ps1 status --task-id health-live-example --json
.\run-local.ps1 resume --task-id health-live-example --max-pages 12 --retry-failed --json
.\run-local.ps1 resume --task-id health-research-demo-20261022 --review-file tasks\my-project-decisions.json --json
```

只提高页数/深度，不减少；降低范围或变更主题/来源/日期时另建任务。resume复用成功抓取检查点；重跑上游前将下游标记stale，新的派生结果写入新的attempt目录，旧结果保留。新增核验文件只重建review和delivery，不重新抓取。

任务目录中的inputs保存来源、候选和核验文件快照及哈希；不直接修改这些文件。需要更正核验时通过新的review-file提交。任务已完成且没有新参数时，resume为无重复工作的查询式恢复。

`basis=publication`按已识别发布日期筛选线索，未知日期保留但明确计数。`basis=event`保留原文线索，交付按填写的event_date单独统计范围内/外/未知项目；程序不把发布日期转换成事件日期，也不会据日期匹配认定地域、场景或事实已核验。

## 状态与失效结果

执行完成不等于调研完整。`completed`表示本次选定阶段运行完成；没有核验文件时仍是待核验资料包。`partial`可能是来源失败、页数预算、搜索错误或原文读取缺口。`failed`不可当作有效交付；status查询成功返回0不代表被查询任务成功。

若出现stale，不使用其旧输出形成最新结论；先恢复完成下游阶段。进程意外终止留下task.lock/run.lock时，核实没有进程占用后再处理锁，程序不会抢占。

## 第三方工具

旧plan/run仍可用；运行前check --profile full。政府采集要选择真实存在的站点文件名片段；不要直接照抄原文档的“卫健”示例。政府脚本内部关键词来自其自己的key_words配置，theme目前主要用于任务记录。

NewsCrawler和news-please需要文章网址；crawl4ai用于动态页面；feapder需要已写好的脚本。feapder执行结束但未验证其交付文件时，结果为partial。不要把这些旧适配器视为与research相同的访问控制实现。
