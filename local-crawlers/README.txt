本地爬虫工具集（Windows / Codex）

用途
四个后端由一个 local_crawlers MCP 入口提供给 Codex。各后端使用独立 Python 环境；浏览器任务按需启动，默认同时只运行一个任务。已安装、可导入、模型已配置、任务实测通过是不同状态，查看 deployment-status.json 和 crawler_status 的实时结果。

组件
browser-use 0.13.14：自然语言浏览器操作、提取、执行历史。
Skyvern 1.0.56 [local]：嵌入式任务执行，内存 SQLite；不安装完整 Web 管理平台，也不启用云端调度。
ScrapeGraphAI 2.3.1：单页或多页的自然语言字段提取。
Firecrawl：官方自托管容器组合，访问地址仅绑定 127.0.0.1:3002。采用专门的 WSL 2 Ubuntu 环境和 Docker Engine，Linux 数据保存在 D:\CodexLocalCrawlers；也支持已有 Docker Desktop。

模型
用户指定 DeepSeek V4.1 Flash，稍后配置。实际模型 ID 和接口能力尚未核实，.env 中 MODEL_ID、MODEL_BASE_URL、MODEL_API_KEY 故意留空。.env 只保存接口地址、模型标识等非敏感参数；密钥通过进程或系统环境变量传入，不写入文件、日志或对话。实际接入时还需设置 MCP 的环境变量透传。配置后需验证结构化输出、工具调用和视觉能力，再做三个模型后端的端到端验收。MODEL_SUPPORTS_VISION 默认 false，待实际模型确认支持图片后再启用。
本地部署指采集程序在本机；之后连接模型 API 时，发送给模型的页面内容仍会离开本机。

工具
crawler_status：检查组件安装、Firecrawl 和模型状态，不返回密钥。
fetch_page：无需模型的 HTML 正文与链接提取。
render_page：无需模型的 JavaScript 页面渲染；保存正文、HTML、截图。
start_crawl：选择 browser-use、skyvern、scrapegraphai 或 firecrawl，提交有时限的任务。
job_status：查询执行状态和结果；完整结果保存在 runs/。
firecrawl_map：通过本地 Firecrawl 发现站点 URL。

推荐分工
简单网页优先 fetch_page；JS 页面先 render_page；规则不统一的字段提取用 ScrapeGraphAI；交互操作用 browser-use；需要多步业务流程时使用 Skyvern；整站批量采集用 Firecrawl。
工具会明确报告未配置/不可用状态，不会在本地后端失败时偷偷改用厂商云爬虫。

重新安装
在本目录运行 powershell -File .\Install.ps1。三个后端默认复用系统 Chrome；Skyvern 使用独立浏览器资料目录和仅本机可访问的随机调试端口。需要独立的 Playwright Chromium 时加 -InstallSkyvernBrowser。
安装日志在 logs/。每个环境的依赖快照在对应 *.lock.txt。

启动 Firecrawl
本次已安装微软 WSL 3.0.3、启用 WSL 和 VirtualMachinePlatform。Windows 明确要求重启，遵照用户要求没有自动重启。实际状态记录在 host-setup-status.json。
手动重启后运行 powershell -File .\Complete-FirecrawlWSL.ps1：导入已校验的 Ubuntu 镜像到专门的 CodexCrawlers 发行版，在该发行版内安装 Docker Engine 和 Compose，再启动 Firecrawl。此过程也不会重启 Windows。
之后常规启动运行 powershell -File .\Start-Firecrawl.ps1。
停止服务运行 powershell -File .\Start-Firecrawl.ps1 -Stop；此操作不删除数据卷。
firecrawl/compose.yaml 根据官方配置使用预构建镜像，目前尚须实际 pull/start 验证；首次成功拉取后应记录镜像 digest。
自托管只使用 /v2/crawl、/v2/map 等基础接口。官方云服务的 Agent、搜索和反自动化能力不视为本地已有功能。

接入 Codex
运行 powershell -File .\Register-Codex.ps1，然后重新加载 MCP 或打开新聊天。
不改动既有 MCP 项目；新增 local_crawlers。全局接入位置是 C:\Users\Jane\.codex\config.toml。
如需撤销接入，运行 codex mcp remove local_crawlers。这不会卸载工具或删除结果。
部署代码、独立环境与配置已迁到 E:\CAICTBigData\coding\local-crawlers。旧 C 盘路径保留为兼容目录联接；Codex 的新配置直接使用 E 盘路径。

来源
https://github.com/browser-use/browser-use
https://github.com/Skyvern-AI/skyvern
https://github.com/ScrapeGraphAI/Scrapegraph-ai
https://github.com/firecrawl/firecrawl
https://learn.chatgpt.com/docs/extend/mcp?surface=cli

任务分工与当前接入能力详见 TASK-CAPABILITIES-20261027.txt。

想法树详细归档：E:\CAICTBigData\coding\idea-trees\local-crawler-agents-20261027\tree.md
代码快照、能力分工、接口、验收和待办见该树的 DETAILS.md。
