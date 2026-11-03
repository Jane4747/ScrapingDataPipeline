# 本地爬虫代码索引

源目录：`E:\CAICTBigData\coding\local-crawlers`。下面链接均指向本树独立快照。

[完整说明](DETAILS.md) · [想法树](tree.md) · [SHA256清单](SOURCE-MANIFEST.json)

| 文件 | 用途 |
| --- | --- |
| [gateway.py](artifacts/code/gateway.py) | 六个 MCP 工具、输入检查、并发入口和后台任务提交 |
| [common.py](artifacts/code/common.py) | 相对目录定位、环境变量、模型配置检查、TLS、URL校验与原子写入 |
| [worker.py](artifacts/code/worker.py) | browser-use / Skyvern / ScrapeGraphAI / Firecrawl 及渲染适配器 |
| [job_runner.py](artifacts/code/job_runner.py) | 后台监督、任务时限、日志和超时进程树清理 |
| [Install.ps1](artifacts/code/Install.ps1) | 创建四个独立 Python 环境并安装固定顶层版本 |
| [Register-Codex.ps1](artifacts/code/Register-Codex.ps1) | 注册 local_crawlers MCP，不包含全局配置或密钥 |
| [Start-Firecrawl.ps1](artifacts/code/Start-Firecrawl.ps1) | Docker 或专用 WSL 环境中的服务启动/停止 |
| [Complete-FirecrawlWSL.ps1](artifacts/code/Complete-FirecrawlWSL.ps1) | 手动重启后的专用 Ubuntu 导入、Docker 安装与容器启动 |
| [Configure-WSLHost.ps1](artifacts/code/Configure-WSLHost.ps1) | 管理员系统准备，启用功能且不自动重启 |
| [download_wsl.py](artifacts/code/download_wsl.py) | WSL 安装包下载与摘要校验辅助 |
| [download_ubuntu.py](artifacts/code/download_ubuntu.py) | Ubuntu WSL 镜像下载与摘要校验辅助 |
| [migrate_runtime.py](artifacts/code/migrate_runtime.py) | E盘迁移后重新生成虚拟环境命令入口 |
| [migration_validation.py](artifacts/code/migration_validation.py) | 迁移后依赖和功能验证辅助 |
| [report_status.py](artifacts/code/report_status.py) | 生成部署状态报告，不返回密钥值 |
| [verify_stack.py](artifacts/code/verify_stack.py) | MCP握手、工具发现、HTML/JS渲染和缺失模型验证 |
| [verify_browser_use.py](artifacts/code/verify_browser_use.py) | browser-use 导入、本地浏览器启动和DOM读取验证 |
| [verify_skyvern.py](artifacts/code/verify_skyvern.py) | Skyvern嵌入式运行库、本地Chrome/CDP与页面读取验证 |
| [verify_scrapegraph.py](artifacts/code/verify_scrapegraph.py) | ScrapeGraphAI导入与上游ChromiumLoader验证 |
| [.env.example](artifacts/code/.env.example) | 空配置模板；真实 .env 明确不归档 |
| [.gitignore](artifacts/code/.gitignore) | 部署目录运行数据、环境、缓存和密钥文件忽略规则 |
| [requirements-gateway.txt](artifacts/code/requirements-gateway.txt) | MCP网关固定顶层依赖 |
| [firecrawl/compose.yaml](artifacts/code/firecrawl/compose.yaml) | 五服务自托管容器配置，API仅绑定回环地址 |
| [firecrawl/install-docker-wsl.sh](artifacts/code/firecrawl/install-docker-wsl.sh) | 在专用Ubuntu内安装并启动Docker与Compose |

## 依赖与证据

| 文件 | 分类 |
| --- | --- |
| [README.txt](artifacts/docs/README.txt) | 本轮已交付文档的完整副本 |
| [WORK-SUMMARY-20261027.txt](artifacts/docs/WORK-SUMMARY-20261027.txt) | 本轮已交付文档的完整副本 |
| [TASK-CAPABILITIES-20261027.txt](artifacts/docs/TASK-CAPABILITIES-20261027.txt) | 本轮已交付文档的完整副本 |
| [deployment-status.json](artifacts/evidence/deployment-status.json) | 本轮状态/验收/迁移的历史记录 |
| [host-setup-status.json](artifacts/evidence/host-setup-status.json) | 本轮状态/验收/迁移的历史记录 |
| [verification.json](artifacts/evidence/verification.json) | 本轮状态/验收/迁移的历史记录 |
| [browser-use-verification.json](artifacts/evidence/browser-use-verification.json) | 本轮状态/验收/迁移的历史记录 |
| [skyvern-verification.json](artifacts/evidence/skyvern-verification.json) | 本轮状态/验收/迁移的历史记录 |
| [scrapegraphai-verification.json](artifacts/evidence/scrapegraphai-verification.json) | 本轮状态/验收/迁移的历史记录 |
| [dependency-checks.json](artifacts/evidence/dependency-checks.json) | 本轮状态/验收/迁移的历史记录 |
| [migration-dependency-checks.json](artifacts/evidence/migration-dependency-checks.json) | 本轮状态/验收/迁移的历史记录 |
| [migration-verification.json](artifacts/evidence/migration-verification.json) | 本轮状态/验收/迁移的历史记录 |
| [migration-runtime.json](artifacts/evidence/migration-runtime.json) | 本轮状态/验收/迁移的历史记录 |
| [migration-report.json](artifacts/evidence/migration-report.json) | 本轮状态/验收/迁移的历史记录 |
| [ubuntu-image.json](artifacts/evidence/ubuntu-image.json) | 本轮状态/验收/迁移的历史记录 |
| [gateway.lock.txt](artifacts/dependencies/gateway.lock.txt) | 对应独立环境的pip freeze版本记录 |
| [browser-use.lock.txt](artifacts/dependencies/browser-use.lock.txt) | 对应独立环境的pip freeze版本记录 |
| [skyvern.lock.txt](artifacts/dependencies/skyvern.lock.txt) | 对应独立环境的pip freeze版本记录 |
| [scrapegraphai.lock.txt](artifacts/dependencies/scrapegraphai.lock.txt) | 对应独立环境的pip freeze版本记录 |
| [archive_local_crawler_stack.py](artifacts/archive-tool/archive_local_crawler_stack.py) | 本树的归档生成和离线校验脚本 |
| [idea_tree_writer.py](artifacts/archive-tool/idea_tree_writer.py) | 父仓库已有树渲染/校验工具，保留用于重现 |

压缩包保存上述代码与记录及树文档；完整运行环境和第三方框架库未放入包中，版本见锁定快照。真实密钥、密码、Cookie及个人配置未归档。
