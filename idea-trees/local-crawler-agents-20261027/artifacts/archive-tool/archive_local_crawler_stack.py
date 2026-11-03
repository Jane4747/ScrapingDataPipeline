"""Archive the deployed crawler stack into this repository's existing idea-tree format.

Creates a new, immutable snapshot, then validates tree rendering, source hashes,
links, ZIP members and secret exclusion. Does not start crawlers or call a model.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIVE = REPO / "local-crawlers"
TREE_ID = "local-crawler-agents-20261027"
DEST = REPO / "idea-trees" / TREE_ID
ZIP_NAME = "local-crawlers-source-and-records-20261027.zip"
sys.path.insert(0, str(REPO))
from scripts.idea_tree_writer import read_tree, render_tree, render_markdown, validate

PURPOSES = {
    "gateway.py": "六个 MCP 工具、输入检查、并发入口和后台任务提交",
    "common.py": "相对目录定位、环境变量、模型配置检查、TLS、URL校验与原子写入",
    "worker.py": "browser-use / Skyvern / ScrapeGraphAI / Firecrawl 及渲染适配器",
    "job_runner.py": "后台监督、任务时限、日志和超时进程树清理",
    "Install.ps1": "创建四个独立 Python 环境并安装固定顶层版本",
    "Register-Codex.ps1": "注册 local_crawlers MCP，不包含全局配置或密钥",
    "Start-Firecrawl.ps1": "Docker 或专用 WSL 环境中的服务启动/停止",
    "Complete-FirecrawlWSL.ps1": "手动重启后的专用 Ubuntu 导入、Docker 安装与容器启动",
    "Configure-WSLHost.ps1": "管理员系统准备，启用功能且不自动重启",
    "download_wsl.py": "WSL 安装包下载与摘要校验辅助",
    "download_ubuntu.py": "Ubuntu WSL 镜像下载与摘要校验辅助",
    "migrate_runtime.py": "E盘迁移后重新生成虚拟环境命令入口",
    "migration_validation.py": "迁移后依赖和功能验证辅助",
    "report_status.py": "生成部署状态报告，不返回密钥值",
    "verify_stack.py": "MCP握手、工具发现、HTML/JS渲染和缺失模型验证",
    "verify_browser_use.py": "browser-use 导入、本地浏览器启动和DOM读取验证",
    "verify_skyvern.py": "Skyvern嵌入式运行库、本地Chrome/CDP与页面读取验证",
    "verify_scrapegraph.py": "ScrapeGraphAI导入与上游ChromiumLoader验证",
    ".env.example": "空配置模板；真实 .env 明确不归档",
    ".gitignore": "部署目录运行数据、环境、缓存和密钥文件忽略规则",
    "requirements-gateway.txt": "MCP网关固定顶层依赖",
    "firecrawl/compose.yaml": "五服务自托管容器配置，API仅绑定回环地址",
    "firecrawl/install-docker-wsl.sh": "在专用Ubuntu内安装并启动Docker与Compose",
}
DOCS = ["README.txt", "WORK-SUMMARY-20261027.txt", "TASK-CAPABILITIES-20261027.txt"]
EVIDENCE = [
    "deployment-status.json", "host-setup-status.json", "verification.json",
    "browser-use-verification.json", "skyvern-verification.json",
    "scrapegraphai-verification.json", "dependency-checks.json",
    "migration-dependency-checks.json", "migration-verification.json",
    "migration-runtime.json", "migration-report.json", "ubuntu-image.json",
]
LOCKS = [f"{name}.lock.txt" for name in ("gateway", "browser-use", "skyvern", "scrapegraphai")]

DETAILS = r"""# 本地爬虫智能体与 Harness：代码、能力与部署档案

这是2026-10-27部署工作的归档快照。**归档完成；部署整体仍为 partial**：三个模型后端尚未配置用户指定的 DeepSeek V4.1 Flash，Firecrawl 尚待手动重启后安装容器并验收。执行新任务前以 `crawler_status` 和实际调用为准；本页记录的验收不是未来运行状态保证。

| 入口 | 用途 |
| --- | --- |
| [想法树](tree.md) / [结构化记录](tree.json) | 需求、方案、能力、决策、完成情况、缺口、下一步和原始项目链接 |
| [代码索引](CODE-INDEX.md) / [源文件清单及SHA256](SOURCE-MANIFEST.json) | 按功能找到真实代码副本，并核对来源与完整性 |
| [代码和记录压缩包](__ZIP__) | 本轮集成源码、依赖快照、说明、验收记录及想法树的便携快照 |
| [任务模板](TASK-TEMPLATES.json) | 六个工具的调用示例和适用场景；模板需补充实际网址再用 |
| [归档校验](ARCHIVE-VERIFICATION.json) | 树结构、文件哈希、ZIP完整性、链接及敏感项排除检查 |
| [原工作总结](artifacts/docs/WORK-SUMMARY-20261027.txt) / [原能力清单](artifacts/docs/TASK-CAPABILITIES-20261027.txt) | 保留本轮已交付的完整文字记录 |

代码实际运行目录为 `E:\CAICTBigData\coding\local-crawlers`。本树的 `artifacts/` 保存独立副本，便于以后源目录变化时追溯。归档内容是本轮编写的集成、部署和验证代码；上游框架通过固定版本的软件包及依赖快照定位，不把整个第三方环境误作自研源码。没有在本轮归档中执行 Git 提交、远程推送或云端发布。

## 1. 需求与已确定的决定

- 网页类型很多，采集程序部署到本机，统一提供给 Codex 使用。
- 选择 browser-use、Skyvern、ScrapeGraphAI、Firecrawl 四个后端；基础读取尽量先用无需后端模型的工具。
- 用户指定模型为 DeepSeek V4.1 Flash，明确稍后配置。供应商实际模型ID、接口地址、密钥、工具调用与图片兼容性尚未确认。
- 代码和独立Python环境迁到E盘；WSL镜像和后续Linux容器数据保留D盘。
- 用户批准现在准备WSL，但明确不自动重启；本轮没有自动重启Windows。
- 复用父项目现有 `idea-trees/<id>/tree.json + tree.md` 体系，使用已有 `scripts/idea_tree_writer.py` 渲染。本次保存详细代码和记录，不改动其他想法树。

## 2. 当前结构与 Harness 到底做什么

```mermaid
flowchart TD
  A[Codex] --> B[local_crawlers MCP / gateway.py]
  B --> C[fetch_page: HTTP与HTML解析]
  B --> D[job_runner.py: 后台监督与时限]
  D --> E[worker.py: 独立环境中的后端]
  E --> F[browser-use / Skyvern / ScrapeGraphAI / Chrome渲染]
  E --> G[本机Firecrawl API]
  C --> H[runs: 来源、结果、状态和日志]
  E --> H
```

本轮自建 Harness 是统一入口和执行外壳：验证参数、检查后端和模型是否准备好、控制默认并发、启动隔离进程、记录输入与状态、限制执行时间、保存结果及日志、校验JSON结构，并让Codex查询。它没有另造一个替代四个框架的“通用智能体”。复杂任务的逐步决策仍由相应上游框架与之后配置的模型完成。

默认同时一个后台任务，默认15分钟；失败明确返回错误，不自动切换到厂商云爬虫。网页文字被视为不可信资料。浏览器按任务新建独立资料目录，不继承用户日常Chrome登录态。程序使用Windows可信证书存储，保持TLS校验；本机回环访问绕过环境代理。远端模型接入后，提交给模型的页面内容会经模型API离开本机。

## 3. 现在可用与尚待验收

| 组件/阶段 | 快照状态 | 本轮验证范围 | 尚未完成 |
| --- | --- | --- | --- |
| MCP统一入口 | 已注册；基础验证通过 | 握手、六工具发现、HTML提取、JS渲染、后台查询、未配模型时明确报错 | 新聊天需重新加载MCP；配置模型后重验 |
| browser-use 0.13.14 | 独立环境安装完成 | 导入、本地Chrome启动、导航和DOM读取 | 模型连续决策和实际采集端到端验收 |
| Skyvern 1.0.56 `[local]` | 嵌入式库安装完成 | 本地运行库、专用Chrome/CDP连接、导航读取 | 模型多步骤任务；凭据、视觉及业务流程验收 |
| ScrapeGraphAI 2.3.1 | 独立环境安装完成 | 核心导入、上游ChromiumLoader读取 | 模型字段提取及多页合并验收 |
| Firecrawl | 配置与系统准备完成，服务未运行 | WSL签名与安装、Windows功能启用、Ubuntu摘要校验 | 手动重启、导入专用发行版、装Docker、启动并验证map/crawl |
| E盘迁移 | 完成，迁移后基础验证通过 | 49,106文件复制校验、92个命令入口重建、4环境依赖检查 | 底层Python仍依赖C盘Codex运行时，不能把venv当完全独立便携包 |

证据文件为 [deployment-status.json](artifacts/evidence/deployment-status.json)、[verification.json](artifacts/evidence/verification.json)、[迁移复测](artifacts/evidence/migration-verification.json) 和 [迁移后依赖检查](artifacts/evidence/migration-dependency-checks.json)。这些是历史报告，本次归档只核验记录和文件完整性，没有重新进行联网采集或调用模型。

## 4. browser-use：需要随页面变化操作的任务

**适合交付：** 搜索、筛选、点击展开、翻页、进入详情、切换标签页后提取信息或下载公开附件。例：从医院采购栏目按关键词找到公告，逐条读取标题、日期、采购人、金额、正文依据和原文链接。

**本地实现：** `worker.py::browser_use_task` 建立 `Browser` 与 `Agent`，配置兼容模型接口，以自然语言任务和起始URL清单驱动执行；`max_steps` 传给Agent。使用本机Chrome、独立 `browser-profile`、任务内 `downloads`，明确 `use_cloud=False`。默认不启用视觉和扩展。

**产物：** `result.json`；`browser-history.json`；下载目录；公共输入、状态和日志。历史成功状态必须通过，否则任务失败。传入schema时在最终结果上检查结构。

**能力边界：** 保存执行历史已接入；当前六个统一工具没有单独的历史重放、文件上传、跨任务登录态管理接口。不能仅根据原项目README就认为这些功能已开放给Codex。模型尚未接入，自动点击/翻页/下载仍未完成本地端到端验收。`max_pages`不构成访问页数硬上限，操作预算用步数和时间约束。

## 5. Skyvern：在一个起点完成多步骤流程

**适合交付：** 在一个网站按流程检索、选择公告类型/年份、打开详情、提取字段或下载。例：进入某省采购站点，选择公告类型，限定时间和关键词，再提取采购人、预算、日期与附件链接。

**本地实现：** `worker.py::skyvern_task` 使用 `Skyvern.local(..., use_in_memory_db=True)`，为每个任务启动本机Chrome，通过仅回环地址的临时CDP端口连接；调用 `run_task`，传入自然语言、唯一的起始URL、schema、步数和时限。模型通过LiteLLM兼容配置连接。

**产物：** `result.json`、`skyvern-run.json`、artifacts及通用日志。只有后端明确completed才接受成功。

**能力边界：** 上游有登录、填表、文件下载及更完整工作流；本地入口目前只暴露run_task。没有装完整Web管理平台，没有命名工作流管理、调度和直播工具。内存SQLite不保存跨任务业务状态。凭据、验证码、视觉和复杂流程仍未验收；不能声称包含上游云端全部反自动化能力。

## 6. ScrapeGraphAI：已知页面中的统一字段提取

**适合交付：** 多个网址已知、排版不一致但字段相同的页面。例：给出医院/机构/项目详情页列表，提取名称、产品、公告日期、原文依据和来源链接；缺失字段留空。

**本地实现：** `worker.py::scrapegraph_task` 单URL使用 `SmartScraperGraph`，多个URL使用 `SmartScraperMultiGraph`；接收提取要求、URL清单和可选schema。浏览器加载器复用本机Chrome，`loader_kwargs`中直接设置 `executable_path`。schema目前加入提示并在任务结束后统一校验，并非强制模型生成时约束。

**产物：** JSON格式结果和通用输入、状态、日志。模型图节点处理网页内容与提取要求，具体字段正确性需核对原文。

**能力边界：** 当前没有接入SearchGraph、采集脚本生成、音频生成、本地文档输入、扫描PDF或OCR。按钮交互交给browser-use/Skyvern。JSON结构通过不等于事实核验通过；多页提取和实际模型兼容仍待验收。

## 7. Firecrawl：发现链接和批量采集原文

**适合交付：** 以一个站点入口发现URL、抓取最多指定数量页面，收集Markdown和来源信息，再由Codex分析。例：抓一个政策库/产品文档站点最多100页，之后筛选主题并整理字段。

**本地实现：** `firecrawl_map` 调用回环地址 `/v2/map`；`worker.py::firecrawl_task` 调用 `/v2/crawl`，传入一个起点、页数limit和Markdown格式，轮询完成后跟随结果分页。后端返回分页地址时仍强制使用本机服务地址，不跟随到托管服务。

**容器方案：** `firecrawl/compose.yaml` 组合 api、playwright-service、Redis、RabbitMQ、PostgreSQL 五项服务，API仅绑定 `127.0.0.1:3002`；队列任务和抓取并发设低值。镜像尚未真实拉取和运行，部分标签为latest，首次成功后须记录/固定digest。

**能力边界：** 当前只接map/crawl。自然语言task不会自动转换为主题、年份或栏目过滤；具体过滤需增加规则或后处理。当前拒绝非空output_schema。官方云Agent、搜索、监控、托管反自动化能力均不计入本地已实现能力。服务尚未启动，因此当前不能安排实际Firecrawl采集。

## 8. 六个Codex工具的准确接口

| 工具 | 主要参数/默认值 | 返回与边界 |
| --- | --- | --- |
| `crawler_status()` | 无 | 安装版本、配置布尔状态、Firecrawl可达性与目录；不返回密钥；配置齐全标记不是模型调用成功 |
| `fetch_page(url, selector="", max_chars=12000)` | HTTP(S)页面，可选CSS区域 | 同步返回标题、正文、来源、最多100个链接；完整正文写result.json；单页HTML最多5,000,000字节；回复正文上限夹在100..50,000字符；不执行JS、不读PDF |
| `render_page(url, timeout_seconds=120)` | 单URL；允许时限30..1800秒 | 后台任务ID；用本机Chrome等待DOM加载及额外1.5秒，保存正文、链接、HTML、整页截图；不自动点击/滚动/翻页；慢加载内容需专门策略 |
| `start_crawl(engine, task, urls, output_schema=None, max_pages=20, max_steps=30, timeout_seconds=900)` | engine四选一；页数1..500、步数1..200、时限30..1800秒 | 后台任务ID；URL数不能超过max_pages；Skyvern/Firecrawl一次只接一个起点；三个模型后端必须先配模型 |
| `job_status(job_id, include_result=True, max_chars=12000)` | 后台16位十六进制ID | 状态、可选结果、结果/日志路径；回复上限100..50,000字符，超出为预览，完整结果仍在文件中 |
| `firecrawl_map(url, limit=100)` | limit夹在1..1000 | 本机服务原始JSON；服务未启动即报错；没有托管兜底 |

`fetch_page`的fetch-*目录没有后台state，直接使用同步返回的 `saved_result`；不要把它当16位后台job_id再交给job_status。URL检查只保证HTTP(S)、有主机且无内嵌凭据，没有自动实施父研究项目的来源域名白名单、robots规则或证据核验规则。正式研究须继续遵守父项目规则，并按任务控制来源和范围。

## 9. 任务预算、输出及如何安排任务

先查状态，再按复杂度选择：普通HTML→fetch_page；JS内容→render_page；已知页面统一字段→ScrapeGraphAI；不确定交互→browser-use；单站流程→Skyvern；批量站点原文→Firecrawl。后四项受前述待配置/待启动状态限制。

任务至少提供：目标、起始URL/来源清单、域名/栏目范围、关键词和时间口径、字段、页数或记录数目标、操作步数、时限、交付格式，以及是否保留正文/附件。缺失字段留空，事实保留原文链接和依据。年份条件应区分发布日期、事件日期和抓取时间。

`max_pages`只硬约束Firecrawl的limit和输入URL数量；对browser-use/Skyvern不保证实际只访问这些页数。若要严格的域名、深度、请求频率、去重和累计页数管理，需要显式扩展适配器，当前不能靠一句提示当强制保证。

后台任务保存在 `E:\CAICTBigData\coding\local-crawlers\runs\<job_id>`：`input.json`、`state.json`、`supervisor.json`、`supervisor.log`、`worker.log`、成功时的 `result.json` 及后端额外产物。状态queued/running/completed/failed；超时任务失败并尝试清理worker进程树。当前没有统一取消工具和崩溃后遗留running状态的自动修复；若显示一直有活动任务，先核实进程与日志，不能直接删锁或改状态强行续跑。

基础交付是JSON、正文或Markdown，CSV/Excel由Codex后处理。周期任务、代理池、通用OCR、跨任务登录态复用和验证码处理均尚未接入。不能把采集器的“成功”当作事实已证实、站点已全覆盖或研究阶段已完成。

## 10. 版本、目录及恢复定位

| 内容 | 快照位置/版本 |
| --- | --- |
| 部署代码/环境/配置 | `E:\CAICTBigData\coding\local-crawlers` |
| Gateway Python | `E:\CAICTBigData\coding\local-crawlers\envs\gateway\Scripts\python.exe` |
| 顶层固定包 | mcp2.3.0 / httpx0.28.1 / beautifulsoup4 4.15.0 / psutil7.2.2 / truststore0.10.5 |
| 三个框架 | browser-use0.13.14 / skyvern[local]1.0.56 / scrapegraphai2.3.1 |
| 底层共享Python | `C:\Users\Jane\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe` |
| Chrome | `C:\Program Files\Google\Chrome\Application\chrome.exe`，由CHROME_EXECUTABLE配置 |
| Codex MCP配置位置 | `C:\Users\Jane\.codex\config.toml`，只归档本组件的空密钥配置示例 |
| WSL安装/系统记录 | [host-setup-status.json](artifacts/evidence/host-setup-status.json)；WSL3.0.3安装退出0、微软签名Valid |
| Ubuntu镜像 | `D:\CodexLocalCrawlers\installers\ubuntu-24.04.5-wsl-amd64.wsl`，SHA256见[记录](artifacts/evidence/ubuntu-image.json) |
| 专用发行版及未来数据 | CodexCrawlers / `D:\CodexLocalCrawlers\WSL\CodexCrawlers` |
| 旧兼容入口 | C盘旧work目录及lcrawl-20261027只为目录联接，实际代码位于E盘 |

迁移复制了49,106个非pyc文件、1,688,429,339字节，排除了未使用的uv启动工具；记录中missing/mismatches均为空。迁移后重建gateway9、browser-use30、ScrapeGraphAI18、Skyvern35，共92个命令入口。原始迁移前记录保留在部署目录的 `migration-history/20261027-before-move`；本树保留关键迁移报告，不复制整套运行缓存和历史网页。

源代码快照不含venv、上游完整源码仓库、浏览器安装、MSI或Ubuntu大镜像。恢复时解压本归档的 `artifacts/code/` 到目标代码目录，按依赖快照查版本，运行Install创建独立环境，再注册MCP。`Install.ps1`固定顶层包但不会自动按freeze锁定全部传递依赖；四份lock是本次已测版本记录，若未来依赖变化应重新核验。更换电脑须显式设置实际BasePython和Chrome路径；WSL/D盘路径也需要相应调整。历史验证脚本/报告是验收依据，恢复时还要检查其中的工作目录假设。

真实 `.env`、密钥、数据库随机密码、Cookie、浏览器资料目录、全局Codex完整配置均不在归档中。运行 `.env.example` 的空模板并不意味着已有可用模型；秘密值通过环境变量传入。模型接入时仍须设置Codex MCP环境透传。底层读取逻辑只覆盖模板中已有的键，恢复时保留模板键名。

## 11. 继续工作的步骤与验收标准

**A. 用户手动重启后完成Firecrawl**

```powershell
Set-Location -LiteralPath 'E:\CAICTBigData\coding\local-crawlers'
powershell -File .\Complete-FirecrawlWSL.ps1
# 之后常规启动/停止；停止不删数据卷。
powershell -File .\Start-Firecrawl.ps1
powershell -File .\Start-Firecrawl.ps1 -Stop
```

归档时尚未运行上述继续步骤。继续脚本校验Ubuntu摘要、导入专用发行版、安装Docker/Compose并启动容器；不重启Windows。不需要再次运行已完成的Configure-WSLHost来覆写历史状态。若同名发行版已存在但无本部署所有权记录，脚本会停止，须先核实归属。

验收应包括专用发行版可启动、Docker/Compose可用、五服务健康、本机API可达、map返回URL、限制几页的crawl成功并保存Markdown，记录实际镜像digest及失败日志。只有通过这些验证才能把Firecrawl状态改为可用。

**B. 用户准备配置模型时接入DeepSeek**

核实供应商实际ID、兼容接口、模型上下文、工具调用、JSON输出及图片支持；不能把“DeepSeek V4.1 Flash”这个需求名称直接当作已核实API模型ID。非敏感参数写配置，密钥只通过进程/系统环境传入；设置MCP透传并重新加载。默认保持MODEL_SUPPORTS_VISION=false，直到真实验证支持图片。

分别执行小规模任务验收：browser-use一次搜索/点击/提取并检查历史；Skyvern一次筛选/详情/提取并检查完成状态；ScrapeGraphAI单页+多页字段提取并核对原文与schema。保留模型调用是否发生、输入/输出、错误和实际费用/时限信息；不要把导入成功等同模型兼容成功。

**C. 之后若用于正式研究流水线**

当前本组件是独立MCP后端，尚未接入父项目版本1任务协议。后续再设计来源白名单、累计预算、研究证据字段、去重、恢复和核验接点；不要假定当前adapter已具备父流水线全部约束。相关规范见父仓库 `docs/GPT_RESEARCH_GUIDE.md`、`docs/COMMANDS.md`、`docs/DATA_DICTIONARY.md`。

## 12. 原项目与继续查找的关键词

| 项目 | 原仓库 | 当前采用方式 |
| --- | --- | --- |
| browser-use | [browser-use/browser-use](https://github.com/browser-use/browser-use) | pip包0.13.14 + 本机Browser/Agent |
| Skyvern | [Skyvern-AI/skyvern](https://github.com/Skyvern-AI/skyvern) | pip包1.0.56 local嵌入式运行 |
| ScrapeGraphAI | [ScrapeGraphAI/Scrapegraph-ai](https://github.com/ScrapeGraphAI/Scrapegraph-ai) | pip包2.3.1 + SmartScraperGraph/MultiGraph |
| Firecrawl | [firecrawl/firecrawl](https://github.com/firecrawl/firecrawl) | 自托管预构建镜像 + 本机map/crawl适配器，尚未运行 |
| WSL | [微软WSL 3.0.3发布](https://github.com/microsoft/WSL/releases/tag/3.0.3) | 已安装，等待Windows手动重启 |
| Ubuntu | [Ubuntu 24.04.5 WSL镜像](https://releases.ubuntu.com/24.04.5/ubuntu-24.04.5-wsl-amd64.wsl) | 已下载并核对SHA256，尚未导入发行版 |

本页按已安装版本、当前代码和本轮记录归档；没有再次验证上游未来版本的产品能力。检索关键词：本地爬虫、爬虫智能体、爬虫Harness、local_crawlers、MCP、browser-use、Skyvern、ScrapeGraphAI、Firecrawl、DeepSeek V4.1 Flash、E盘迁移、CodexCrawlers、WSL、不自动重启、医院采购、能力清单、源代码、验收记录。
"""


def dump(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def secret_values() -> list[str]:
    """Read only to detect accidental copying; never return values in reports."""
    values = []
    path = LIVE / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                value = value.strip().strip("\"'")
                if value and any(word in key.upper() for word in ("KEY", "PASSWORD", "SECRET", "TOKEN")):
                    values.append(value)
    return values


def check_no_secrets(data: bytes, forbidden: list[str]):
    if any(value.encode("utf-8") in data for value in forbidden):
        raise ValueError("Sensitive value detected; no value is included in this error")
    text = data.decode("utf-8-sig")
    if re.search(r"(?im)^[ \t]*(?:MODEL_API_KEY|FIRECRAWL_API_KEY|FIRECRAWL_POSTGRES_PASSWORD)[ \t]*=[ \t]*[^\s#]", text):
        raise ValueError("Nonblank secret assignment detected")
    if re.search(r"https?://[^\s/:@]+:[^\s/@]+@", text):
        raise ValueError("URL with embedded credentials detected")


def build_tree(timestamp: str) -> dict:
    tree = {
        "id": TREE_ID, "created_at": timestamp, "updated_at": timestamp,
        "status": "partial",
        "status_note": "代码和能力归档完成；三个模型后端等待稍后配置DeepSeek；Firecrawl等待手动重启后完成容器安装和验收。",
        "requirement": "把本次部署的代码、每个智能体的能力、使用入口、验证结果和详细待办保存到想法树，方便以后找到和安排任务。",
        "theme": "本地爬虫智能体与Harness：browser-use、Skyvern、ScrapeGraphAI、Firecrawl及Codex MCP",
        "delivery": "[完整说明](DETAILS.md)、[代码索引](CODE-INDEX.md)、[代码与记录压缩包](" + ZIP_NAME + ")、[任务模板](TASK-TEMPLATES.json)、[归档校验](ARCHIVE-VERIFICATION.json)",
        "tool": "现有idea_tree_writer + 本轮源码/依赖/验收快照 + SHA256与ZIP校验",
        "tags": ["本地爬虫", "爬虫智能体", "爬虫Harness", "local_crawlers", "Codex", "MCP", "browser-use", "Skyvern", "ScrapeGraphAI", "Firecrawl", "DeepSeek V4.1 Flash", "E盘迁移", "WSL", "CodexCrawlers", "医院采购", "代码归档", "任务分工"],
        "live_directory": str(LIVE), "nodes": [],
        "result": {"archive_status": "completed", "deployment_status": "partial", "model_configured": False, "ai_end_to_end_tested": False, "firecrawl_running": False, "automatic_windows_restart": False, "mcp_tools": 6, "source_zip": ZIP_NAME},
    }

    def node(id, parent, kind, text, status="completed", **extra):
        tree["nodes"].append({"id": id, "parent": parent, "kind": kind, "at": timestamp, "status": status, "text": text, **extra})

    node("need", None, "需求", "将本次本地爬虫部署的代码、能力、状态、决策和待办完整归档，便于以后检索与安排任务。归档已完成，部署整体仍为partial。")
    node("entry", "need", "查找入口", "先读[完整说明](DETAILS.md)，找源码看[代码索引](CODE-INDEX.md)，直接备份用[压缩包](" + ZIP_NAME + ")，安排任务参考[模板](TASK-TEMPLATES.json)。")
    node("decisions", "need", "用户决定", "网页种类多；采集程序在本机，提供给Codex；代码迁往E:\\CAICTBigData\\coding；DeepSeek稍后配置；WSL现在准备但不得自动重启。")
    node("scope", "decisions", "范围", "选择四后端+一个MCP入口+两个无需后端模型的基础工具。仅记录已安装版本和当前适配器；不把厂商云端能力当作本地已部署能力。")
    node("arch", "need", "架构", "Codex→gateway.py→job_runner.py→独立环境worker.py→本地Chrome或Firecrawl API→runs结果。Harness负责统一调用、预算、后台进程、状态、日志和结构校验。")
    node("harness-functions", "arch", "已实现", "参数检查、URL格式校验、缺失模型/后端报错、默认单任务并发、时限、进程树超时清理、原子JSON保存、日志、结果预览、schema结构校验。")
    node("harness-limits", "arch", "当前边界", "尚无周期调度、统一取消、遗留running自动修复、代理池、通用OCR、共享登录态、验证码服务和父研究协议集成；URL校验不等于研究来源白名单/robots约束。", "partial")
    node("tools", "arch", "MCP接口", "已注册local_crawlers，共6个工具；精确参数、限制和返回字段见[完整说明第8节](DETAILS.md)。")
    node("tool-status", "tools", "crawler_status", "无参数；检查安装版本、模型配置标记、Firecrawl可达性及输出目录，不返回密钥。配置齐全不等于模型调用验证成功。")
    node("tool-fetch", "tools", "fetch_page", "同步HTTP读取HTML；支持CSS区域；保存完整正文、标题和最多100个链接。默认回复12000字符、最多50000；HTML最多5000000字节；不执行JS、不解析PDF。")
    node("tool-render", "tools", "render_page", "无需后端模型，用本地Chrome渲染JS页面；后台任务；保存正文、链接、HTML、整页截图。默认120秒，DOM加载后等1.5秒；不自动点击/滚动/翻页。")
    node("tool-start", "tools", "start_crawl", "engine四选一+task+urls+可选schema；默认20页、30步、900秒；范围分别1..500、1..200、30..1800。Skyvern/Firecrawl只接一个起始URL；三个模型后端当前会明确报未配置。")
    node("tool-poll", "tools", "job_status", "按16位后台job_id读取状态和结果预览，返回完整结果与日志路径；默认12000字符，100..50000夹限；fetch-*同步结果目录不用此接口。")
    node("tool-map", "tools", "firecrawl_map", "本机/v2/map链接发现；默认100，范围1..1000；Firecrawl尚未启动，暂不可用。", "planned")
    node("engines", "need", "四后端能力", "按任务选择：交互→browser-use；单站多步骤流程→Skyvern；已知网址统一字段→ScrapeGraphAI；链接发现和批量原文→Firecrawl。")
    node("bu", "engines", "browser-use 0.13.14", "独立环境已安装，基础浏览器验证通过；模型驱动交互尚待DeepSeek配置后验收。", "partial", repository="https://github.com/browser-use/browser-use")
    node("bu-functions", "bu", "能力", "依据页面状态完成搜索、点击、输入、筛选、翻页、展开、滚动、切换标签页和提取；任务内可下载文件；保存历史，可要求JSON并验证结构。上述自动决策待模型实测。", "partial")
    node("bu-code", "bu", "实现", "[worker.py](artifacts/code/worker.py)的browser_use_task，Agent+Browser+兼容模型；use_cloud=False；每任务新资料目录、下载目录；max_steps传入Agent，检查history成功。")
    node("bu-output", "bu", "产物", "通用result.json、browser-history.json、downloads和任务日志；结果来源URL保留。")
    node("bu-limit", "bu", "边界", "未统一暴露历史重放/文件上传；不继承日常Chrome登录；视觉默认关闭。max_pages不是实际访问页数硬限制，当前靠步数/时限。", "partial")
    node("bu-example", "bu", "任务例", "在医院采购栏目输入设备关键词，逐条进入详情，提取标题、发布日期、采购人、金额、依据、来源链接；明确记录数目标、步数和时限。", "planned")
    node("sky", "engines", "Skyvern 1.0.56 local", "嵌入式运行库+内存SQLite已安装，专用本地Chrome/CDP基础验证通过；模型多步骤任务未验收。", "partial", repository="https://github.com/Skyvern-AI/skyvern")
    node("sky-functions", "sky", "能力", "将检索、筛选、选择年份/类型、导航、信息提取或下载串成自然语言任务；支持传提取schema。原项目有更完整的表单/登录/工作流能力，当前不等于全开放。", "partial")
    node("sky-code", "sky", "实现", "worker.py的skyvern_task，Skyvern.local(use_in_memory_db=True)，每任务随机回环CDP端口，本机Chrome；仅run_task、单起始URL、步数与时限；completed才接受结果。")
    node("sky-output", "sky", "产物", "result.json、skyvern-run.json、artifacts和任务日志。内存数据库不是跨任务状态存储。")
    node("sky-limit", "sky", "边界", "没有完整Web平台、命名工作流管理/调度/直播工具；凭据、验证码、视觉、实际多步业务流程都未验收；云端反自动化能力不计本地。", "partial")
    node("sky-example", "sky", "任务例", "从单个省采购站入口输入关键词、选公告类型和年份、读取详情，提取采购人、预算、日期、附件链接；先用少量记录验收流程。", "planned")
    node("sg", "engines", "ScrapeGraphAI 2.3.1", "核心库和ChromiumLoader真实页面读取已通过；单/多页模型字段提取待验收。", "partial", repository="https://github.com/ScrapeGraphAI/Scrapegraph-ai")
    node("sg-functions", "sg", "能力", "给定一个或多个已知URL，用同一自然语言字段要求提取并汇总；可带schema作最终结构检查，适合排版不统一的详情页。", "partial")
    node("sg-code", "sg", "实现", "worker.py的scrapegraph_task；SmartScraperGraph/SmartScraperMultiGraph；loader_kwargs直接放executable_path；schema加入提示并在worker末尾验证。")
    node("sg-limit", "sg", "边界", "未开放SearchGraph、脚本/音频生成、本地文档/OCR；复杂按钮交互用其他浏览器后端。结构正确不等于事实核验正确。", "partial")
    node("sg-example", "sg", "任务例", "提供一组医院/企业/项目详情页，统一提取机构、项目、产品、日期、原文依据、来源；未知字段留空，后续核对原文。", "planned")
    node("fc", "engines", "Firecrawl", "本地map/crawl适配器与Compose已备；WSL和镜像准备完，容器未运行，等待手动重启后继续。", "partial", repository="https://github.com/firecrawl/firecrawl")
    node("fc-functions", "fc", "已写接口", "站点URL发现/v2/map；单站批量/v2/crawl，设置limit、返回Markdown、轮询完成并取尽结果分页；目前未实际服务验收。", "planned")
    node("fc-code", "fc", "实现", "[Compose](artifacts/code/firecrawl/compose.yaml)五服务：api、playwright、Redis、RabbitMQ、PostgreSQL；API仅127.0.0.1:3002，适配器强制本机服务，无托管兜底。")
    node("fc-limit", "fc", "边界", "task不会转换为主题/年份/栏目过滤；不接受非空schema；不含云Agent/搜索/监控/托管反自动化；部分镜像latest尚未拉取固定digest。", "partial")
    node("fc-example", "fc", "任务例", "服务验收后，从一个政策/产品文档入口抓取最多100页，保存Markdown和来源，再由Codex筛选主题、提取字段。", "planned")
    node("budget", "need", "预算与输出", "默认并发1、时限15分钟；交互默认30步；Firecrawl默认20页。结果写E盘runs，Excel/CSV由Codex后处理。")
    node("budget-pages", "budget", "页数语义", "max_pages约束输入URL数和Firecrawl limit，对browser-use/Skyvern不是访问页数硬上限；严格域名/累计页数/深度/频率管理需要另接约束。")
    node("budget-state", "budget", "后台状态", "queued→running→completed/failed；input/state/result/supervisor/worker日志留存；超时清理worker进程树；无自动遗留状态修复和统一取消入口。")
    node("task-fields", "budget", "安排任务所需", "目标、入口、站点/栏目范围、关键词/时间口径、字段、记录/页数目标、步数、时限、交付格式、原文/附件保留要求；未知字段留空、保留依据与来源。")
    node("code", "need", "代码归档", "[代码索引](CODE-INDEX.md)列出每个文件用途、可浏览副本和原路径；[清单](SOURCE-MANIFEST.json)记录每个副本SHA256、字节数、来源、分类与脱敏变更。")
    for filename, purpose in PURPOSES.items():
        node("file-" + re.sub(r"[^a-z0-9]+", "-", filename.lower()).strip("-"), "code", "源文件", f"[{filename}](artifacts/code/{filename})：{purpose}。")
    node("deps", "code", "依赖记录", "四个环境的freeze快照在artifacts/dependencies；Install固定顶层版本，freeze仅为本次已测记录，不代表未来重新安装完全自动锁定传递依赖。")
    node("config", "code", "MCP配置", "[空密钥配置示例](artifacts/config/codex-mcp.example.toml)只含local_crawlers命令/参数；真实.env和全局配置不归档。重新注册后加载MCP。")
    node("verification", "need", "验证记录", "归档保留原始验收/状态JSON，区分安装、可导入、浏览器读取、模型配置、端到端任务；本次归档仅做离线完整性验证。")
    node("verify-mcp", "verification", "已通过", "MCP握手、6工具发现、HTML提取、JS渲染、后台任务与结果读取、未配置模型时明确报错。[报告](artifacts/evidence/verification.json)")
    node("verify-engines", "verification", "已通过", "三框架非模型基础验证：browser-use本地浏览器导航DOM，Skyvern本地Chrome/CDP读取，ScrapeGraph上游ChromiumLoader读取；各报告均model_called=false。")
    node("verify-migration", "verification", "已通过", "迁移后四套基础验证和四环境依赖检查均通过；父仓库research检查已在前轮通过。[迁移复测](artifacts/evidence/migration-verification.json)")
    node("verify-ai-pending", "verification", "未验收", "三个框架的模型驱动端到端、视觉、登录、验证码与真实业务流程未验收；不能用基础验证推导这些能力可用。", "planned")
    node("migration", "need", "E盘迁移", "部署代码、配置、独立环境迁入E:\\CAICTBigData\\coding\\local-crawlers；旧C盘目录为兼容联接；新Codex配置直接使用E盘。")
    node("migration-proof", "migration", "复制和复测", "复制49106个非pyc文件，共1688429339字节；missing和mismatch为空；重建92个环境命令入口。[迁移报告](artifacts/evidence/migration-report.json)")
    node("migration-history", "migration", "历史保留", "旧验收报告在运行目录migration-history/20261027-before-move，本树保存关键新报告；不覆盖历史失败来声称成功。")
    node("migration-portability", "migration", "恢复边界", "venv底层仍依赖C盘Codex Python；D盘Linux数据未迁到E；新电脑需重新安装环境并调整Python/Chrome/WSL路径，不能直接复制venv当完全便携。", "partial")
    node("host", "need", "WSL系统准备", "已安装微软签名Valid的WSL3.0.3、启用Windows WSL和VirtualMachinePlatform；系统明确要求重启，用户要求不自动重启，实际未自动重启。", "partial")
    node("host-image", "host", "镜像", "Ubuntu24.04.5镜像已校验SHA256并保存在D:\\CodexLocalCrawlers\\installers；[摘要记录](artifacts/evidence/ubuntu-image.json)。尚未导入发行版。")
    node("host-next", "host", "待手动重启后", "执行Complete-FirecrawlWSL.ps1，导入专用CodexCrawlers至D盘WSL目录，安装Docker/Compose并启动Firecrawl；启动脚本不重启Windows。", "awaiting_jane")
    node("model", "need", "DeepSeek接入", "需求名DeepSeek V4.1 Flash；按用户指示稍后配置。MODEL_ID/BASE_URL/API_KEY未配置，视觉默认false。不得猜供应商实际模型ID。", "planned")
    node("model-next", "model", "待办", "核实实际ID、接口、工具调用/JSON/图片兼容；密钥用环境变量，配置MCP透传；三框架分别做小规模端到端并核对依据、schema和失败记录。", "planned")
    node("research-integration", "need", "研究流水线", "本组件当前独立MCP，尚未并入父仓库版本1任务协议；正式研究继续执行来源边界、证据留存、日期口径、核验规则。后续再设计适配器。", "planned")
    node("privacy", "need", "归档范围", "保存本轮源码、配置空模板、四份依赖快照和关键JSON证据；排除真实.env、密码/密钥、Cookie/资料目录、全局配置、运行原文、venv和大安装包；原环境保留在E/D盘。")
    node("restore", "privacy", "恢复方法", "[详细步骤](DETAILS.md)：解压artifacts/code到目标部署目录，重建环境，补非敏感配置与环境密钥，重新注册MCP；Windows/Chrome/WSL路径须按机器调整，历史报告不能替代新验收。")
    node("sources", "need", "原始来源", "以下是本轮选型的四个上游仓库；当前能力以本地代码、安装版本和验收为准。")
    for id, title, url in [
        ("source-bu", "browser-use", "https://github.com/browser-use/browser-use"),
        ("source-sky", "Skyvern", "https://github.com/Skyvern-AI/skyvern"),
        ("source-sg", "ScrapeGraphAI", "https://github.com/ScrapeGraphAI/Scrapegraph-ai"),
        ("source-fc", "Firecrawl", "https://github.com/firecrawl/firecrawl"),
    ]:
        node(id, "sources", "GitHub", f"[{title}]({url})", url=url)
    node("related", "need", "关联工作", "[历史本地采集部署](../20261015-deploy/tree.md)、[医院采购入口成果](../hospital-procurement-urls-20261027/tree.md)、[医卫中标来源规则](../medical-digital-tender-rules-20261027/tree.md)。本树记录爬虫基础设施，不把这些资料采集覆盖率算作本轮能力验收。")
    node("archive-check", "need", "归档验收", "[归档校验报告](ARCHIVE-VERIFICATION.json)：树JSON/Markdown一致、父子节点有效、源码哈希/ZIP成员与文件一致、内部链接存在、真实敏感值未混入；归档交付completed，部署状态partial。")
    return tree


def templates():
    common = {"task": "<目标、来源范围、时间口径、所需字段；未知留空并保留原文依据和URL>", "urls": ["<替换为真实HTTP(S)起始网址>"], "max_pages": 20, "max_steps": 30, "timeout_seconds": 900}
    return {
        "note": "仅为未执行的调用模板；替换所有尖括号占位符，先查状态。后三个模型后端待配置，Firecrawl待启动。不是父仓库版本1任务文件。",
        "examples": [
            {"scenario": "先查可用状态", "tool": "crawler_status", "arguments": {}, "ready_at_snapshot": True},
            {"scenario": "普通HTML正文", "tool": "fetch_page", "arguments": {"url": "<实际HTML网址>", "selector": "", "max_chars": 12000}, "ready_at_snapshot": True},
            {"scenario": "JS渲染正文与截图", "tool": "render_page", "arguments": {"url": "<实际网址>", "timeout_seconds": 120}, "ready_at_snapshot": True},
            *[{"scenario": scenario, "tool": "start_crawl", "arguments": {"engine": engine, **common}, "ready_at_snapshot": False, "pending": "用户稍后配置模型并做端到端验收"} for engine, scenario in (("browser-use", "搜索点击翻页后提取"), ("skyvern", "单站多步骤筛选与提取"), ("scrapegraphai", "已知页面统一字段提取"))],
            {"scenario": "批量站点Markdown原文", "tool": "start_crawl", "arguments": {"engine": "firecrawl", **common, "task": "", "max_pages": 100}, "ready_at_snapshot": False, "pending": "手动重启后完成容器安装和map/crawl验收；task不产生过滤规则"},
            {"scenario": "站点URL发现", "tool": "firecrawl_map", "arguments": {"url": "<实际入口网址>", "limit": 100}, "ready_at_snapshot": False, "pending": "Firecrawl启动与验收"},
            {"scenario": "轮询后台任务", "tool": "job_status", "arguments": {"job_id": "<上一步返回的16位后台ID>", "include_result": True, "max_chars": 12000}, "ready_at_snapshot": True},
        ],
        "optional_schema_example": {"type": "object", "properties": {"records": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": ["string", "null"]}, "publication_date": {"type": ["string", "null"]}, "source_url": {"type": "string"}, "evidence": {"type": ["string", "null"]}}, "required": ["title", "publication_date", "source_url", "evidence"]}}}, "required": ["records"]},
        "schema_note": "仅对三个模型后端使用output_schema；schema是结构校验，不验证事实、链接真实性或覆盖完整度。",
    }


def create_archive():
    if DEST.exists():
        raise FileExistsError(f"Snapshot already exists; use --verify: {DEST}")
    for relative in [*PURPOSES, *DOCS, *EVIDENCE, *LOCKS]:
        if not (LIVE / relative).is_file():
            raise FileNotFoundError(relative)
    timestamp = datetime.now().astimezone().replace(microsecond=0).isoformat()
    DEST.mkdir(parents=True)
    # Only append a discoverability pointer to the live component's README.
    live_readme = LIVE / "README.txt"
    pointer = "想法树详细归档：E:\\CAICTBigData\\coding\\idea-trees\\" + TREE_ID
    original_readme = live_readme.read_text(encoding="utf-8-sig")
    if pointer not in original_readme:
        with live_readme.open("a", encoding="utf-8") as handle:
            handle.write("\n" + pointer + "\\tree.md\n代码快照、能力分工、接口、验收和待办见该树的 DETAILS.md。\n")

    forbidden = secret_values()
    records = []

    def copy(source: Path, relative: str, category: str, purpose: str, transform=False):
        original = source.read_bytes()
        content = original
        transformation = None
        if transform:
            data = json.loads(original.decode("utf-8-sig"))
            data.get("critical_file_hashes_before_path_updates", {}).pop(".env", None)
            data["archive_redaction"] = "仅去除真实.env文件的历史哈希；原运行报告保留不变。"
            content = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            transformation = "removed_real_env_hash"
        check_no_secrets(content, forbidden)
        target = DEST / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        records.append({"path": relative, "category": category, "purpose": purpose, "source_live": str(source), "bytes": len(content), "sha256": sha(content), "source_sha256": sha(original), "transformation": transformation})

    for filename, purpose in PURPOSES.items():
        copy(LIVE / filename, "artifacts/code/" + filename, "integration_source", purpose)
    for filename in DOCS:
        copy(LIVE / filename, "artifacts/docs/" + filename, "previous_delivery", "本轮已交付文档的完整副本")
    for filename in EVIDENCE:
        copy(LIVE / filename, "artifacts/evidence/" + filename, "verification_evidence", "本轮状态/验收/迁移的历史记录", filename == "migration-report.json")
    for filename in LOCKS:
        copy(LIVE / filename, "artifacts/dependencies/" + filename, "dependency_snapshot", "对应独立环境的pip freeze版本记录")
    copy(Path(__file__).resolve(), "artifacts/archive-tool/archive_local_crawler_stack.py", "archive_tool", "本树的归档生成和离线校验脚本")
    copy(REPO / "scripts" / "idea_tree_writer.py", "artifacts/archive-tool/idea_tree_writer.py", "repository_tree_tool", "父仓库已有树渲染/校验工具，保留用于重现")

    config = '''# 本组件配置示例；不含密钥，不覆盖其他MCP项目。\n[mcp_servers.local_crawlers]\ncommand = 'E:\\CAICTBigData\\coding\\local-crawlers\\envs\\gateway\\Scripts\\python.exe'\nargs = ['E:\\CAICTBigData\\coding\\local-crawlers\\gateway.py']\nenabled = true\n# 之后配置模型时，另行设置安全的环境变量透传并重新加载。\n'''
    config_path = DEST / "artifacts/config/codex-mcp.example.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config, encoding="utf-8")
    dump(DEST / "SOURCE-MANIFEST.json", {
        "tree_id": TREE_ID, "created_at": timestamp, "live_directory": str(LIVE),
        "scope": "本轮自编集成源码、部署验证脚本、文档、依赖快照及验收JSON；不是完整上游代码/运行环境镜像。",
        "excluded": ["真实.env及秘密值", "全局Codex完整配置", "envs/", "cache/", "profiles/", "runs/", "logs/", "installers/", "migration-history/", "tools/", "*.pyc"],
        "generated_config_example": "artifacts/config/codex-mcp.example.toml", "files": records,
    })
    (DEST / "DETAILS.md").write_text(DETAILS.replace("__ZIP__", ZIP_NAME), encoding="utf-8")
    dump(DEST / "TASK-TEMPLATES.json", templates())
    tree = build_tree(timestamp)
    tree["result"].update({"archived_source_files": len(PURPOSES), "dependency_snapshots": len(LOCKS), "evidence_reports": len(EVIDENCE), "snapshot_files_from_sources": len(records), "node_count": len(tree["nodes"])})
    dump(DEST / "tree.json", tree)
    render_tree(DEST / "tree.json")

    lines = ["# 本地爬虫代码索引", "", "源目录：`E:\\CAICTBigData\\coding\\local-crawlers`。下面链接均指向本树独立快照。", "", "[完整说明](DETAILS.md) · [想法树](tree.md) · [SHA256清单](SOURCE-MANIFEST.json)", "", "| 文件 | 用途 |", "| --- | --- |"]
    for filename, purpose in PURPOSES.items():
        lines.append(f"| [{filename}](artifacts/code/{filename}) | {purpose} |")
    lines.extend(["", "## 依赖与证据", "", "| 文件 | 分类 |", "| --- | --- |"])
    for record in records:
        if record["category"] != "integration_source":
            lines.append(f"| [{Path(record['path']).name}]({record['path']}) | {record['purpose']} |")
    lines.extend(["", "压缩包保存上述代码与记录及树文档；完整运行环境和第三方框架库未放入包中，版本见锁定快照。真实密钥、密码、Cookie及个人配置未归档。", ""])
    (DEST / "CODE-INDEX.md").write_text("\n".join(lines), encoding="utf-8")

    for path in DEST.rglob("*"):
        if path.is_file():
            check_no_secrets(path.read_bytes(), forbidden)
    # The integrity report records the ZIP's hash, so lives outside the ZIP.
    with zipfile.ZipFile(DEST / ZIP_NAME, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(DEST.rglob("*")):
            if path.is_file() and path.name != ZIP_NAME:
                archive.write(path, path.relative_to(DEST).as_posix())

    repo_pointer = "idea-trees/" + TREE_ID + "/tree.md"
    root_readme = REPO / "README.md"
    if repo_pointer not in root_readme.read_text(encoding="utf-8-sig"):
        with root_readme.open("a", encoding="utf-8") as handle:
            handle.write("\n## 本地爬虫智能体与 Harness（2026-10-27）\n\n- [完整想法树](" + repo_pointer + ")：四后端能力、源码快照、Codex接入、验收记录和后续任务。\n- [详细能力与恢复说明](idea-trees/" + TREE_ID + "/DETAILS.md)：三个模型后端待配置DeepSeek；Firecrawl待手动重启后继续。\n")
    report = verify_archive(allow_missing_report=True)
    dump(DEST / "ARCHIVE-VERIFICATION.json", report)
    verify_archive()
    return report


def verify_archive(allow_missing_report=False):
    tree = validate(read_tree(DEST / "tree.json"))
    assert (DEST / "tree.md").read_text(encoding="utf-8") == render_markdown(tree)
    assert tree["status"] == "partial" and tree["result"]["archive_status"] == "completed"
    ids = {node["id"] for node in tree["nodes"]}
    reachable = set()
    def visit(id):
        assert id not in reachable, "Cycle or duplicate node"
        reachable.add(id)
        for node in tree["nodes"]:
            if node.get("parent") == id:
                visit(node["id"])
    assert tree["nodes"][0]["parent"] is None
    visit("need")
    assert reachable == ids
    manifest = json.loads((DEST / "SOURCE-MANIFEST.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        current = (DEST / entry["path"]).read_bytes()
        assert sha(current) == entry["sha256"] and len(current) == entry["bytes"], entry["path"]
        # Compare unchanged source content; transformed report retains source hash separately.
        assert sha(Path(entry["source_live"]).read_bytes()) == entry["source_sha256"], entry["source_live"]
    assert set(PURPOSES) == {p.relative_to(DEST / "artifacts/code").as_posix() for p in (DEST / "artifacts/code").rglob("*") if p.is_file()}
    forbidden = secret_values()
    text_files = [p for p in DEST.rglob("*") if p.is_file() and p.name not in {ZIP_NAME, "ARCHIVE-VERIFICATION.json"}]
    for path in text_files:
        check_no_secrets(path.read_bytes(), forbidden)
    link_count = 0
    for filename in ("tree.md", "DETAILS.md", "CODE-INDEX.md"):
        content = (DEST / filename).read_text(encoding="utf-8")
        for link in re.findall(r"\]\(([^)]+)\)", content):
            if link.startswith(("http://", "https://", "#")):
                continue
            target = DEST / link.split("#", 1)[0]
            if allow_missing_report and target.name == "ARCHIVE-VERIFICATION.json":
                continue
            assert target.exists(), f"Broken local link: {filename}: {link}"
            link_count += 1
    syntax_count = 0
    for path in (DEST / "artifacts").rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        syntax_count += 1
    evidence = json.loads((DEST / "artifacts/evidence/deployment-status.json").read_text(encoding="utf-8"))
    assert evidence["model_configuration"]["end_to_end_ai_tasks_tested"] is False
    assert evidence["firecrawl"]["running"] is False
    assert evidence["firecrawl"]["windows_automatically_restarted"] is False
    with zipfile.ZipFile(DEST / ZIP_NAME) as archive:
        assert archive.testzip() is None
        members = archive.namelist()
        assert len(members) == len(set(members))
        assert set(members) == {p.relative_to(DEST).as_posix() for p in text_files}
        for name in members:
            parts = Path(name).parts
            assert ".." not in parts and not Path(name).is_absolute()
            assert ".env" not in parts
            assert not {"envs", "profiles", "cache", "runs", "logs", "installers"}.intersection(parts)
            assert archive.read(name) == (DEST / name).read_bytes(), name
            check_no_secrets(archive.read(name), forbidden)
    zip_data = (DEST / ZIP_NAME).read_bytes()
    return {
        "checked_at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "status": "passed", "tree_id": TREE_ID, "tree_nodes": len(ids),
        "tree_structure": "passed", "json_markdown_consistency": "passed",
        "snapshot_source_hashes": "passed", "snapshot_files": len(manifest["files"]),
        "integration_source_files": len(PURPOSES), "dependency_snapshots": len(LOCKS), "evidence_reports": len(EVIDENCE),
        "python_syntax_files": syntax_count, "local_links_checked": link_count,
        "zip_integrity": "passed", "zip_members": len(members), "zip_file": ZIP_NAME,
        "zip_bytes": len(zip_data), "zip_sha256": sha(zip_data),
        "secret_values_excluded": "passed", "runtime_and_personal_files_excluded": "passed",
        "deployment_state_not_overclaimed": "passed", "network_or_model_called_for_archive": False,
        "note": "归档完成不等于模型任务/Firecrawl已验收；此校验没有重跑联网或模型任务。校验报告在ZIP之外，以避免自引用哈希。",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Only check an existing snapshot, without rewriting it")
    args = parser.parse_args()
    result = verify_archive() if args.verify else create_archive()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
