# 企业智能医疗装备与智慧健康资料采集

这套流程帮助你把公开网页整理成可追溯的研究资料：**搜索候选链接 → 保存网页/PDF原文 → 提取部署线索 → 人工核验项目**。预置你提供的21个企业和平台；研究范围同时包含医疗装备、智慧医疗、数字健康、康复辅助、医疗健康服务、医养照护和智慧康养。

## 我如何寻找网页

先确认企业的官方名称、品牌和官网，再按不同问题组合关键词。集团、成员企业和医院名称可能不同，不能把集团所有业务都算给某个成员企业。

| 要了解的问题 | 可用检索式示例 |
|---|---|
| 有没有具体项目 | `site:gt.cn 医疗 智慧医院 项目` |
| 是否已经使用 | `site:sinopharm.com 智慧医疗 上线` |
| 装备进入了哪家医院 | `site:mindray.com/cn 瑞智 医院` |
| 手术机器人应用 | `site:medbotsurgical.com 手术机器人 医院` |
| 康养平台运营 | `site:powerbeijing.com 北京康养 智慧养老` |
| 建设和采购证据 | `企业名 医院名 中标 验收`，然后核对医院或采购公告原文 |
| 未来布局 | `企业名 年报 战略 研发 规划` |

搜索通常分三轮：

1. **企业官网**：新闻中心、客户案例、解决方案、产品、投资者关系、年报/ESG报告。
2. **应用方**：医院、康养机构、地方卫健/民政部门，核对项目是否试用、验收、投用。
3. **披露与采购**：交易所公告、招投标与政府采购文件，核对主体、时间、规模和金额。中标仍不能直接等于验收投用。

没有结果时，先删去部分限定词，再尝试简称、产品名、子公司名和年份。搜索引擎对引号、OR与括号的支持不同，界面里的检索式可以手动调整。检索时间窗口不等于项目发生时间。

聊天中的联网搜索由搜索工具完成；本地程序不会自动继承该工具的权限。这里提供两种本地发现方式：默认生成可点击搜索计划，手动导入链接；或自备密钥调用可选的Brave Search API。

## 在这台电脑上运行

在本代码库根目录打开PowerShell。`run-local.ps1` 会依次选择 `SCRAPING_PYTHON` 指定的解释器、本地 `.venv`、`.runtime.json` 记录的解释器、活动conda环境或系统Python，并为当前调用设置环境。

```powershell
# 1. 生成21家、126条可点击检索式；不访问网络，不需要密钥。
.\run-local.ps1 discover --output-dir outputs/my-search-plan

# 2. 按原始入口采集；初次每家最多尝试6页，含失败页面。
.\run-local.ps1 research --run-id my-health-crawl --max-pages 6 --max-depth 1 --workers 3 --delay 1

# 3. 从全部成功页面提取部署线索；不联网。
.\run-local.ps1 evidence --input-dir outputs/my-health-crawl --output-dir outputs/my-health-evidence
```

每次新任务请换一个输出目录/运行名。`discover` 和 `evidence` 不覆盖非空目录。抓取结果需要继续采集时，使用下文的 `--resume`。请等抓取命令结束后再生成线索索引，避免同时读取正在更新的资料。

也可以只采集一两家，先检查入口和正文质量：

```powershell
.\run-local.ps1 research --list-sources
.\run-local.ps1 research --source medbot --source cecloud --run-id my-two-companies --max-pages 6 --max-depth 1
```

更换电脑时需要Python 3.10及以上和 `requirements-research.txt` 中的依赖。这个最小依赖文件支持上述三个命令；可选的Excel导出、浏览器渲染和旧采集器使用原有较完整的依赖文件。

```powershell
python -m pip install -r requirements-research.txt
# 不使用PowerShell启动器时，在当前文件夹直接调用：
python -m pipeline discover --help
```

## 先找到具体案例，再采集

首页爬取适合初步摸底，但集团网站可能同时包含能源、地产、招聘等内容。具体案例链接通常比扩大首页爬取页数更有效。样例候选保存在 `configs/deployment_seed_candidates.json`，每条结构如下：

```json
[
  {
    "source_id": "mindray",
    "url": "https://www.mindray.com/cn/innovation/customer-stories/hospital-wide-critical-care-intelli-digital-taizhou",
    "title": "在台州，建一座全院危重症管理的数智长城",
    "query": "site:mindray.com/cn 台州 重症 案例"
  }
]
```

```powershell
# 导入候选并生成独立配置，原始配置不会被修改。
.\run-local.ps1 discover --import-results configs/deployment_seed_candidates.json --output-dir outputs/my-import

# max-depth=0 只访问种子链接，适合对已找到的文章做定向采集。
.\run-local.ps1 research --config outputs/my-import/config.discovered.json --source mindray --source beijing_elderly_care --source shandong_healthcare --run-id my-cases --max-pages 6 --max-depth 0

.\run-local.ps1 evidence --input-dir outputs/my-cases --output-dir outputs/my-case-evidence
```

导入只接受对应来源白名单内的网址，不会自动扩大域名范围。候选链接和搜索标题都只是线索，必须以成功获取的原文为准。新增种子在原有种子之后；页数上限至少要容纳准备访问的所有种子。

如果需要采集医院、交易所或采购网站，复制 `configs/medical_equipment_sources.json`，在副本中添加独立来源和经核实的官网域名，再通过 `--config` 使用副本。不要只为一个跳转链接放开所有域名。新配置要使用新的抓取运行目录；旧任务的断点恢复会校验来源配置是否一致。

## 可选：自动搜索

自动搜索使用[Brave官方Web Search API](https://api-dashboard.search.brave.com/app/documentation/web-search/codes)。需要你自己的 `BRAVE_SEARCH_API_KEY` 环境变量，服务可能收费；本次没有调用该API，默认流程不产生搜索API费用。

```powershell
# 先在本地设置 BRAVE_SEARCH_API_KEY 环境变量，再执行。
.\run-local.ps1 discover --source mindray --provider brave --api-budget 6 --results-per-query 5 --output-dir outputs/my-mindray-search
```

`--max-queries 6` 是每个来源的查询上限；`--api-budget 6` 是整次运行的API请求上限，最大30。全部21家同时运行但预算为6时，只会请求前6家各自的首条查询，其余标为未请求；不会自动分批补完。建议分企业运行；21家各执行6条查询合计126次请求，需要自行安排预算。认证失败、访问拒绝或限流后会停止后续请求，并保留状态。密钥不写入结果文件。

## 输出如何用于研究

| 阶段 | 文件 | 用途 |
|---|---|---|
| 搜索 | `query_plan.md / .csv / .json` | 每家企业的检索式、目的和搜索入口 |
| 搜索 | `search_results.json / rejected_results.json / query_status.json` | 候选、拒绝原因、是否真的执行搜索 |
| 搜索 | `config.discovered.json` | 保留原配置并加入允许的候选种子 |
| 抓取 | `pages.json / failures.json / manifest.json` | 全部尝试页面、失败原因、范围与覆盖 |
| 抓取 | `sources/<来源ID>/` | 本轮抓取的原始HTML/PDF及TXT正文；具体路径见页面记录，与项目根目录的只读参考资料 `sources/` 不同 |
| 抓取 | `records.json / research.md` | 旧的装备/数字技术主题筛选，不能当作全部健康场景 |
| 线索 | `deployment_evidence.csv / .json` | 可用Excel查看的原文片段和初步类型 |
| 线索 | `summary.json / deployment_index.md` | 各企业覆盖、未知日期、截断条数及读取异常 |

线索索引读取 `pages.json` 中的全部成功页面，因此能补充旧主题筛选漏掉的智慧健康、康养和健康管理材料。每条保留企业、网址、标题、已识别发布日期、抓取时间、原文片段、行号、主题、初步状态、原始文件路径和原采集目录。PDF页码只取原文中的显式页码标记。

| 自动标签 | 阅读方式 |
|---|---|
| `operational_claim` | 来源出现运行/部署陈述；仍需核验主体和实际状态 |
| `pilot` | 试点、试用或试验；不直接推断常规商业使用 |
| `collaboration` | 合作、签约或共建线索 |
| `product_release` | 产品/方案发布；不等于有客户采用 |
| `plan` | 计划、未来动作或战略布局 |
| `uncertain` | 否定、能力描述或状态不明确 |

这些是近邻关键词规则生成的待核验线索，不是经过事实核查的项目数据库。同一句可能涉及多个动作、同一项目可能出现在多个网页，**线索条数不能当作项目数**。默认每网页或整份PDF保留30条，省略数量会写入摘要，可用 `--max-per-page` 调整。`医疗健康服务` 和 `医养与照护` 标签包括较宽的背景线索；只关注智能装备/智慧健康时，应结合其他主题标签及原文筛选，不能把普通康养合作都当作智能化项目。

建议人工核验后另建项目台账：**项目名、企业法人/成员企业、产品或技术、应用机构、地点、场景、项目阶段、事件日期、发布日期、投资/采购规模、效果指标、证据链接、核验状态**。当前代码不自动猜测医院、地点、金额或项目事件日期，也不把企业宣传效果当作独立验证结果。

做五年回顾时，可按已知发布日期筛选：

```powershell
.\run-local.ps1 evidence --input-dir outputs/my-health-crawl --output-dir outputs/my-five-year-evidence --since 2021-10-22 --until 2026-10-22
```

日期未知页面会保留并计数，不能据此认定属于该五年。发布日期、项目发生日期和抓取日期必须分别看待。网页可能在2026年介绍2019年的项目；未来布局则要保存来源的规划期限和承诺措辞，而不能作为确定预测。

## 继续采集与边界

```powershell
# 在相同来源配置和原目录续采，提高累计上限。
.\run-local.ps1 research --run-id my-health-crawl --resume --max-pages 12

# 重试失败仍受网站访问规则限制，不保证成功。
.\run-local.ps1 research --run-id my-health-crawl --resume --retry-failed --max-pages 12
```

遇到网站访问拒绝、robots规则无法读取或禁止、超时，会记录失败并继续其他来源。动态页面、搜索结果中有正文但直接访问失败、扫描PDF都可能造成缺失。现有 `--browser` 只用于允许访问的JavaScript空壳页，需另有浏览器依赖；扫描PDF本版不做OCR。HTTP成功或抓取状态 `completed` 只说明本轮抓取结果，不表示企业调研已经完整。

默认对同一来源串行，限制页数、深度、响应体积和请求间隔；新发现的站外链接不会自动抓取。没有抓到资料不能推断企业没有相关部署。

## 验证

自动测试覆盖候选导入、域名范围、搜索请求预算、未来/否定表述、日期未知、原文路径边界、重复输出目录保护及原有抓取行为。升级后的统一任务还验证中断恢复、项目引用和交付完整性，见 [验证记录](docs/VALIDATION.md)。本次升级没有重新联网采集。
