# ScrapingDataPipeline — 本地调研工具库

面向GPT与研究人员的公开资料采集、证据整理和可追溯交付工具。流程为：任务定义 → 来源发现 → 网页/PDF采集 → 线索提取 → 项目归并与核验记录 → 研究资料包。

统一任务流水线当前支持医疗装备、智慧医疗、健康服务与康养部署线索（health_deployment）。保留5类旧采集器适配器用于政策、文章和其他站点。核心筛选是可解释规则，不会自动核实企业陈述，也不会自动生成事实已确认的研究结论。

## GPT从这里开始

- [调研调用指南](docs/GPT_RESEARCH_GUIDE.md)：任务选择、证据阅读、核验与报告流程。
- [命令与任务协议](docs/COMMANDS.md)：JSON输入、返回值、退出码及恢复方式。
- [数据字典](docs/DATA_DICTIONARY.md)：资料/证据/项目、日期与状态的区分。
- [北京一级医院招采用法](docs/BEIJING_TIER1_TENDERS.md)：名单、词表、限定网址归档与七列导出。
- [本轮代码总结](docs/BEIJING_TIER1_CODE_SUMMARY.md)：模块职责、实际执行范围、审计和已知限制。
- [本轮想法树](idea-trees/beijing-tier1-tenders-20261027/tree.md)：检索、采集、核验、交付与缺口。
- [企业资料采集指南](COLLECTING_GUIDE.md)：分阶段搜索、采集和线索提取。
- [AGENTS.md](AGENTS.md)：以后GPT在本库工作的约束和默认操作方式。

## 直接运行

在本仓库目录打开PowerShell。启动器选择SCRAPING_PYTHON、.venv、.runtime.json、活动conda或系统Python；不会自动安装依赖。已有本机环境通过.runtime.json记录，避免代码写死盘符。

```powershell
.\run-local.ps1 check --profile research --json

# 离线搜索计划：只生成检索式，不调用搜索API。
.\run-local.ps1 task --spec tasks\example_search_plan.json --dry-run --json
.\run-local.ps1 task --spec tasks\example_search_plan.json --json

# 复用已有2026-10-22采集，原资料不被修改。
.\run-local.ps1 task --spec tasks\example_health_research.json --dry-run --json
.\run-local.ps1 task --spec tasks\example_health_research.json --json

.\run-local.ps1 status --task-id health-research-demo-20261022 --json
```

每次新研究复制示例并改task_id。已有任务用resume，不覆盖旧目录。任务中的相对文件路径以任务JSON位置解析。example_health_research依赖本机已有采集目录；其他机器需修改collection.input_dir。

需要实际联网时使用 `tasks/example_live_collection.json` 的结构，按范围设置来源、预算与allow_network=true。默认provider=plan仍不会实际搜索；可导入GPT搜索得到的候选，或显式使用自备密钥的Brave API。

## 输出和恢复

`outputs/<task_id>/` 保存task.json、status.json、inputs快照，以及discovery/collection/evidence/review/delivery阶段目录。派生结果使用attempt编号保留历史；最新路径以状态返回值为准。

```powershell
# 扩大同一采集任务，重试失败项；成功页面不重复访问。
.\run-local.ps1 resume --task-id health-live-example --max-pages 12 --retry-failed --json
# 核验模板由review阶段生成，填写后仅重建核验与交付。
.\run-local.ps1 resume --task-id health-research-demo-20261022 --review-file tasks\my-project-decisions.json --json
```

completed只表示所选阶段执行完成。partial表示存在失败或范围缺口；failed不能当作成功；stale是上游变化后的旧结果。线索数不能当作项目数，日期未知不计入限定年份。默认项目台账为空，需显式引用证据归并。交付report.md为机器资料包，供GPT继续综合分析。

## 分阶段工具

| 命令 | 能力 |
|---|---|
| discover | 检索计划、候选导入、可选Brave搜索；保留域名边界 |
| research | 21来源默认配置，可替换自定义来源；HTTP/可选浏览器/PDF，逐页检查点 |
| evidence | 从全部成功页面提取待核验线索，含原文位置及日期缺口 |
| review | 显式项目台账和核验队列，不自动把线索归并为事实项目 |
| task/status/resume | 统一任务输入、执行、查询及恢复 |

research遵守域名白名单、robots、限速、重定向校验、响应大小和页数/深度限制。访问拒绝、TLS错误、无正文和OCR需求单独记录。扫描PDF目前不执行OCR。这些边界不自动等同于旧第三方采集器的实现。

## 旧采集器仍可使用

| 需求 | 工具 | 必要输入 |
|---|---|---|
| 政府政策 | goverment_spider | 真实站点脚本名片段，或明确选择--all-sites |
| 已知文章 | NewsCrawler | URL |
| 动态网页 | crawl4ai | URL，可选结构化schema |
| 自定义长期采集 | feapder | 已编写的爬虫脚本 |
| 新闻提取 | news-please | 新闻文章URL |

先运行check --profile full，再使用plan/run。政府主题关键词仍由其第三方配置控制；本库theme不自动改写关键词。政府单站点仅导出本次新增/更新的TXT或XLSX；crawl4ai/news-please按成功/失败数报告；feapder输出未验证时为partial。默认子进程超时600秒，可通过--process-timeout或SCRAPING_PROCESS_TIMEOUT调整。

第三方仓库位置默认repos，可用SCRAPING_REPOS替换。当前第三方版本与本地Windows补丁需随部署记录保留，根Git不跟踪整个repos目录。

## 安装和测试

基础流程要求Python 3.10+及requirements-research.txt。JSON/Markdown/CSV无需pandas；Excel需要pandas/xlsxwriter。完整旧工具还需要已有repos及完整依赖。

```powershell
.\scripts\install.ps1 -Profile research -Python '完整的python.exe路径'
# full只在明确需要且repos已准备好时使用；浏览器下载另加-InstallBrowser。
.\run-local.ps1 --help
$testPython = (Get-Content .runtime.json -Raw | ConvertFrom-Json).python
$testPrefix = Split-Path -Parent $testPython
$env:PATH = "$testPrefix\Library\bin;" + $env:PATH
& $testPython -B -m unittest discover -s tests -v
```

安装脚本相对当前仓库定位，不自动克隆、隐式下载浏览器或切换到其他项目。基础依赖实测版本见constraints-research-tested.txt；使用前先核对Python版本。

测试使用模拟网络和临时文件，覆盖采集边界、恢复、导出、任务中断、核验及公式保护。离线通过不等于真实网站、浏览器或搜索API已验证。2026-10-22升级说明见 [CHANGELOG](CHANGELOG.md)。
