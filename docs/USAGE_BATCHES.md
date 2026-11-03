# 批次与工具使用手册

本页补充 README 的统一任务流程。所有命令在仓库根目录执行，`$py` 指向已安装依赖的 Python；`<...>` 代表必须准备的输入。日期、来源和预算属于任务契约，示例中的历史日期不随运行日期改变。

## 1. 通用调研与旧适配器

通用任务先执行 `run-local.ps1 check --profile research --json`，再 `task --spec <JSON> --dry-run --json`。使用 `tasks/example_search_plan.json` 可完全离线生成检索计划；`example_health_research.json` 需自己提供带 `pages.json` 的既有采集目录；`example_live_collection.json` 是有限联网示例。

旧 `plan/run` 适配器分别是政府站 `goverment_spider`、文章 `NewsCrawler`、动态页 `crawl4ai`、自定义爬虫 `feapder`、新闻提取 `news-please`。它们要求外部仓库与完整依赖；先 `check --profile full --json`，再查看 `plan --help` / `run --help`。政府采集必须指定真实站点脚本名片段，`--all-sites` 才运行全部站点。主题不会自动改写第三方脚本关键词，feapder 未验证交付文件时只能报告 partial。第三方基线见 [THIRD_PARTY_BASELINE.json](THIRD_PARTY_BASELINE.json)。

## 2. 北京一级医院与官网采购入口

医院名单是工作簿或 JSON，必须保留医院 ID、名称、层级与原始行关系。已有 `scripts/beijing_tenders.py` 分为 `roster / portal / scan / extract / verify / export`；联网部分和离线处理部分不能混淆。

```powershell
# 从自己的名单生成 roster；此步骤只读本地工作簿
& $py -B scripts/beijing_tenders.py roster --workbook '<名单.xlsx>' --output outputs/my-hospitals/roster.json

# 官网候选计划：不联网，输入需要 hospital_id/hospital_name/candidate_hosts
& $py -B scripts/hospital_site_probe.py --roster outputs/my-hospitals/roster.json --plan --output-dir outputs/my-hospitals/plan
# 有限联网探测
& $py -B scripts/hospital_site_probe.py --roster outputs/my-hospitals/roster.json --probe --allow-network --output-dir outputs/my-hospitals/probe

# 工作簿回写默认干跑；核对参数与计划后另加 --apply，建议指定新输出
& $py -B scripts/hospital_workbook_writer.py --workbook '<名单.xlsx>' --sheet '05-全量明细' --records outputs/my-hospitals/probe/probe_records.json
```

不同名单字段并不自动兼容：`beijing_tenders` 的 roster 与官网探针要求的字段应先按各自文档核对/转换。探针输出 `probe_plan.json`、`scope.json` 或 `probe_records.json`；后者有 `homepage_url`、`top_candidate`、`channel_status` 和证据列表。平台域名不会直接作为医院本级官网；栏目命中后仍需核对主体与实际采购公告。

`hospital_workbook_writer` 可指定表名、表头行和 S/T/U 等列；`--update-channel` 才更新采购栏目列。默认先备份，未命中不会覆盖已有人工结论。`scripts/tender_channel_merge.py`、`tender_audit.py`、`finalize_tender_workbook.py` 用于渠道补查、审计、终版收口，完整参数见 [渠道说明](BEIJING_TIER1_CHANNELS.md)。`build_tender_workbook.mjs` 需要专用 Artifact 模块，不能用普通 Node.js 环境直接保证运行。

`hospital_entry_probe.py`、`hospital_batch_crawl.py`、`hospital_render_probe.py`、`hospital_site_fix_crawl.py` 和 `hospital_projects_extract.py` 是医院批次辅助脚本；部分沿用历史路径与数据格式，先检查 `--help`/文件头，提供对应入口清单、探测记录和原文。不要把它们当作统一任务 `resume` 的替代。

## 3. 医疗数字化规则与单源采集

规则入口是 `configs/medical_digital_tender_rules.json`，来源、选择器、地区导航与缺口由配置记录。计划和保存原文重解析可离线运行：

```powershell
& $py -B -m pipeline.research.tenders plan --output outputs/my-tender-plan.json
& $py -B -m pipeline.research.tenders parse --source ccgp --input-file '<已保存公告.html>' --url 'https://www.ccgp.gov.cn/<原始详情路径>' --output outputs/my-notice.json
# 联网时显式限定来源、页数和深度；使用新的输出目录
& $py -B -m pipeline.research.tenders collect --source ccgp --output outputs/my-ccgp-smoke --allow-network --max-pages 3 --max-depth 1
```

`parse` 无网络/DNS；`collect` 只运行支持的公开 HTML 模式，商业接口、会员导出和待建来源记 `attempted=false`。更多字段、八类金额/阶段边界、失败重放见 [规则说明](MEDICAL_DIGITAL_TENDER_RULES.md)。`scripts/thirdparty_goverment_spider/` 的三个站点脚本是外部政府爬虫适配，不代表已包含整个第三方库。

央采独立入口：

```powershell
& $py -B -m pipeline.research.zycg --start 2024-01-01 --end 2026-10-29 --output outputs/my-zycg --max-pages 100 --delay 3.5 --all-notices
```

这会联网，按月发现并保留缓存。`--dry-run` 仍请求列表，只省略详情；`--from-cache` 仅保证列表发现从已存目录合并，不能因此假设详情也永不联网。结果和失败记录随 `zycg_medical_bid.json` 等文件保留。央采是按采购代理机构字段筛出的公告，电子卖场、批量集采及其他代理机构不自动纳入。旧八列表与三平台的 22 字段表不能直接混为同一版本，详见 [央采规则](ZYCG_MEDICAL_BID_RULES.md)。

全国平台独立入口：

```powershell
& $py -B -m pipeline.research.national_ggzy --start 2024-01-01 --end 2026-10-29 --output outputs/my-national --business 02 --max-api-calls 200 --max-details 100 --delay 3.5 --dry-run
```

去掉 `--dry-run` 才采集；续跑同范围用 `--resume`。`--stage discover/details/reparse` 分别控制发现、详情和重解析，`reparse` 复用保存原文。默认政府采购代码 `02`，工程建设为不同业务范围，须新建任务。查询窗口、原文、失败和状态单独落盘，访问挑战或页数上限不能视为该时间窗已经穷尽。

## 4. 三平台与分省 Dagu 工作流

启动器要求显式提供本机 Python、Dagu、Node 和 Artifact 模块位置，不自动安装依赖。只需检查时使用 Python 的 `plan --dry-run`；PowerShell 启动器会继续生成 DAG、启动服务并入队，**不是只生成计划**。

```powershell
$dagu = 'C:\path\to\dagu.exe'
$node = 'C:\path\to\node.exe'
$artifactModules = 'C:\path\to\provided\node_modules'

# 三平台：离线范围校验
& $py -B -m pipeline.research.tender_update plan --task-id my-three-20261029 --start 2024-01-01 --end 2026-10-29 --dag-dir outputs/my-dags --python $py --node $node --artifact-modules $artifactModules --dry-run
# 准备开始联网采集时执行，-NoBrowser 仅控制是否打开进度页
.\scripts\start-tender-update.ps1 -TaskId my-three-20261029 -Start 2024-01-01 -End 2026-10-29 -Python $py -DaguExe $dagu -NodeExe $node -ArtifactModules $artifactModules -NoBrowser

# 分省第一批：同样先做离线范围校验
& $py -B -m pipeline.research.province_update plan --task-id my-province-b1 --batch 1 --start 2024-01-01 --end 2026-10-29 --dag-dir outputs/my-dags --python $py --node $node --artifact-modules $artifactModules --dry-run
.\scripts\start-province-update.ps1 -Batch 1 -TaskId my-province-b1 -Start 2024-01-01 -End 2026-10-29 -Python $py -DaguExe $dagu -NodeExe $node -ArtifactModules $artifactModules -NoBrowser
```

恢复同一请求时启动器加 `-Resume`。更改日期、来源或批次必须使用新 ID；不抢占仍在运行的来源锁。服务默认本机端口 8098，状态在 `outputs/dagu-runtime/`。`request.json` 保存范围和初始代码 SHA256，兼容修订记录在 `code-revisions/`，各次执行另存快照。

第一批九个区域：上海、北京、深圳、广州、江苏、浙江、湖北、四川、山东。第二批二十四个区域：广东、河南、福建、湖南、安徽、陕西、重庆、辽宁、天津、河北、江西、广西、山西、云南、贵州、黑龙江、吉林、内蒙古、新疆、甘肃、宁夏、青海、海南、西藏。第二批示例将 `--batch/-Batch` 改 2，并换 task ID。

批次成员由 `province_update.py` 的 `BATCHES` 定义。深圳/广州是市级，广东是省级，汇总按网址去重；省平台收录不等于全省所有渠道。预算按每个区域计算，默认每区域 1600 次 API / 1400 条详情。跨进程共享节流、冷却与有界传输重试不改变请求范围；遇访问挑战仍保留 partial。

三平台 DAG 为校验 → 各来源采集 → 汇总 → 导出；分省为校验 → 各区域 → 汇总 → 导出。`records.json` / CSV 是 22 字段记录，字段来源见 `pipeline/research/tender_fields.py`；单源保留 `state.json`、`progress.json`、原文和失败。分省每个区域另有 `region-progress.json`，整体 `summary.json` 记录未检索窗口、去重与缺口。Excel 同时带数据和采集范围页，缺失 Artifact 模块时导出不可用。

离线读取已有任务或重新汇总：

```powershell
$env:PROVINCE_UPDATE_TASK_DIR = (Resolve-Path 'outputs/province-updates/<已有任务>').Path
& $py -B -m pipeline.research.province_update verify
& $py -B -m pipeline.research.province_update summarize
# publish 复制已生成交付件，会写入指定目录；不是新一轮采集
& $py -B -m pipeline.research.province_update publish --target '<自己的交付目录>'
```

`resume-province-batch.ps1` 和 `supervise_province_batches.py` 包含历史环境/批次约定，迁移时先核对路径和任务 ID；不直接删除锁“解决”运行冲突。更多恢复、文件被占用和风控历史见 [分省手册](PROVINCE_TENDER_UPDATE.md)、[三平台手册](TENDER_UPDATE_DAGU.md)。

## 5. 机构六表、数字化报道和养老批次

机构生成器只处理本地 JSON，不采集、不补造床位或资金等事实：

```powershell
& $py -B scripts/build_institution_registry.py --seed configs/institution_tables_seed_20261030.json --output outputs/my-registry/seed.xlsx
# 应用补正；仍保留原始 seed
& $py -B scripts/build_institution_registry.py --seed configs/institution_tables_seed_20261030.json --patch configs/institution_patch_20261030.json --domicile configs/institution_hospital_domicile_20261030.json --aliases configs/institution_aliases_20261030.json --contact configs/institution_contact_20261101.json --output outputs/my-registry/patched.xlsx
```

输出 10 Sheet，包含六张业务表、机构主表、证据、说明与统计。种子版 327 行、190 家唯一机构、22 组跨表重复与后来的 555 行主表是不同阶段。`--patch`、`--aliases`、`--domicile`、`--contact` 分别处理补正、名称归一、属地与联系方式，不把弱证据自动升级。

`institution_doc_extract.py --local <附件> --out <新JSON>` 可离线解析 PDF/Word；不带 `--local` 而给 `--url` 会下载。Word 格式需要 Windows Word 与 pywin32。`institution_contact_enrich.py probe --xlsx <工作簿> --out <JSON>`、`verify_institution_urls.py --contact <JSON>` 是联网工具；`institution_contact_enrich.py report --src <JSON>` 读取已存结果。

数字化报道 `digit_reports_batch1..15*.json` 与目标名单、养老 `agedcare_reports_p1..p9.json` 是整理后的批次输入。两个生成脚本当前没有通用命令行参数，在仓库根运行：

```powershell
& $py -B scripts/build_digitization_tables.py
& $py -B scripts/build_agedcare_tables.py
```

它们读取 `configs/` 的匹配文件并写固定历史命名的 `outputs/institution-registry-20261030/` 工作簿；运行前确认该目录不会覆盖需保留的版本，最好在独立工作副本中执行。数字化表 A 为报道分析（16 列），表 B 为项目明细（40 列），按机构+标题+链接去重报道；养老表按机构 ID 去重并保留来源与批次统计。文件名含“全量”或“162 家”是历史命名，不是实际全部完成的证明，应以读取到的批次、行数、失败和缺口为准。生成器不会重新搜索网页验证输入。

## 6. 传播网址与公众号归档

静态网址地图在 `docs/medical-digital-pr-url-map.html`，公众号矩阵和探针源码副本在 `idea-trees/medical-digital-pr-wechat-mapping-20261102/`。归档校验不联网：

```powershell
& $py -B scripts/archive_medical_pr_mapping_20261102.py --verify
```

不带 `--verify` 会重建归档，依赖原本机输出和移交目录，不用于普通阅读/验证。`wxnum_probe.py` 留作解析思路参考；其第三方收录源不足以证明官方主体和省级覆盖。`probe2.json` 只含广东、四川试跑；全量已中止，`candidates.json` 未生成，不能据此计算覆盖率。历史“8 格待核”与矩阵待核单元格数量不一致，完整说明见 README。

## 7. arXiv 与 DOI 文献

arXiv 使用版本 1 spec；先 dry-run，首次正式运行不加 resume，后续同输入续跑加 resume：

```powershell
& $py -B literature/collector.py --spec literature/rsi_2026.json --dry-run --json
# 确认该历史研究范围与输出目录后再实际联网
& $py -B literature/collector.py --spec literature/rsi_2026.json --json
# 继续同一任务时，在上述命令增加 --resume
& $py -B literature/verify.py --root '<已有文献采集目录>'
```

新研究复制 spec 并换 `task_id`、候选、截止日、输出目录。采集器核验官方元数据、固定 arXiv 版本、保存 PDF/文本哈希，不是搜索引擎。`queries` 只记录检索词，不意味着已执行搜索。

DOI 使用版本 2 spec（见 `literature/visual-servoing-20261101/spec.json`），必须自己提供其中引用的 `catalog`、`records` 与可选 `supplemental`：`catalog.rows` 每篇含 ID/DOI/题名等；`records` 保存每篇 `work`（DOI 为完整 `https://doi.org/...`）和 `crossref` 元数据。历史文献结果不随源码发布，缺少它们时 dry-run 也会明确失败，不能空造元数据。相对路径以 spec 所在目录解析。

```powershell
& $py -B literature/doi_collector.py --spec '<自己的spec.json>' --dry-run
& $py -B literature/doi_collector.py --spec '<自己的spec.json>'
# 后续同输入续跑增加 --resume
```

真实下载要求 `allow_network=true`。成功文件按哈希复用，失败默认不重试，明确需要才加 `--retry-failed`；输入指纹改变须另开任务。输出 `catalog.json`、`manifest.json`、`failures.json`、逐篇 receipts、PDF 和文本。访问拒绝、robots、无开放全文分别记录，不绕过付费或登录。

已有用户提供 PDF 可完全离线导入：

```powershell
& $py -B literature/doi_import.py --inbox '<PDF目录>' --catalog '<元数据catalog.json>' --out outputs/my-doi-local
& $py -B literature/doi_evidence.py --root outputs/my-doi-local
```

导入核对题名/DOI，歧义留在 `unmatched.json`，不移动或删除输入。`doi_evidence` 只提取带页码原文窗口，不自动判断论文架构。整理后的笔记用于 `doi_library.py --metadata <catalog> --sources <采集目录...> --notes <notes.json> --out <新目录>`，再用 `verify_doi_library.py --root <库目录>` 检查资源引用。

图片阶段须使用有 pypdfium2/Pillow/numpy 的解释器：

```powershell
& $py -B literature/run_doi_figures.py --root '<已下载文献目录>' --image-dir images-review --correct-captions
```

`run_doi_figures.py` 用当前解释器启动子任务，不能指望不存在的 `figure-runtime.json` 自动选择环境；`run-figures.ps1` 的本机路径配置应自己准备。输出图像、图注、页码、像素和 SHA256 清单；自动裁剪不等于逐图人工复核。`--reuse-assets` 只有在指定历史素材目录存在时使用，首次提取不要添加。PDF、学术图片及下载全文是本地研究材料，不随源码提交；没有全文的条目标 `fulltext_missing`，不凭题名推测实现。

## 8. 2026-11-03 与可选后端

后续批次单独见 [BATCHES_20261103.md](BATCHES_20261103.md)，避免把续跑、来源补查和全国覆盖混为一次任务。

`local-crawlers/` 是可选 browser-use/Skyvern/ScrapeGraphAI/Firecrawl 接入，依赖模型、浏览器或额外服务，按其 [README](../local-crawlers/README.txt) 配置。源码发布不包含本机部署状态 JSON、密钥、浏览器 profile、安装器及服务数据。示例 `.env.example` 只作字段模板；缺失模型/后端必须报未配置，不能声称已运行。它不是核心离线测试的必需服务。
