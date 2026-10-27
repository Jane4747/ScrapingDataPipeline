# 命令与任务协议

## 入口

在仓库目录用 `run-local.ps1`，或使用已配置环境的 `python -B -m pipeline`。启动器优先选择SCRAPING_PYTHON、.venv、.runtime.json、活动conda环境、系统Python；退出后恢复调用者环境。核心命令无需pandas，Excel导出按需加载pandas/xlsxwriter。

| 命令 | 用途 |
|---|---|
| `check --profile research --json` | 检查基础模块导入；默认profile为research |
| `check --profile full --json` | 同时检查旧适配器依赖及仓库目录 |
| `task --spec <JSON> [--output-root <目录>] [--dry-run] --json` | 新任务；dry-run不写文件、不联网 |
| `status --task-id <ID> [--output-root <目录>] --json` | 返回已保存状态及锁存在情况 |
| `resume --task-id <ID> [--output-root <目录>] [--max-pages N] [--max-depth N] [--retry-failed] [--review-file <JSON>] --json` | 恢复或重建受变更影响的阶段 |
| `review --input-dir <证据目录> --output-dir <新目录> [--decisions <JSON>] --json` | 独立生成核验队列或导入项目决定 |
| `discover / research / evidence --help` | 保留的分阶段命令，详见COLLECTING_GUIDE.md |
| `plan / run --help` | 保留旧采集器编排；run支持--process-timeout及--json |

task/status/resume成功时默认输出一个JSON对象；机器调用始终带--json，以保证参数错误也返回JSON。进度写stderr。JSON默认是紧凑阶段摘要，完整状态在返回的status_file中。`stages.<阶段>.files`若提供则是实际交付路径。

## 退出码

| 退出码 | task/resume/run/check含义 |
|---|---|
| 0 | 成功；task dry-run通过校验也是0 |
| 2 | 参数/依赖/执行失败 |
| 3 | 部分完成，需要检查缺口 |
| 4 | 需要输入，如中断的付费搜索不能自动重放 |

status成功读取状态时固定返回0，应同时读取JSON.status。旧research/discover/evidence保留原退出语义：research的partial可能返回0，不能只读退出码判断资料完整性。

## 任务版本1

必填schema_version=1、task_id、title、question。task_id为最多80字符的安全目录名。未知字段拒绝，避免拼写错误被静默忽略。

| 字段 | 默认/约束 |
|---|---|
| research_type | health_deployment；当前统一流水线仅支持此提取类型 |
| source_config | 默认configs/medical_equipment_sources.json；自定义须符合现有来源配置格式 |
| source_ids | 空数组表示配置中的全部来源；否则指定ID子集 |
| topic_profile | 默认configs/topics/health_deployment.json；仅定义检索式 |
| region / scenarios | 字符串/字符串数组，记录范围；须在项目核验中判断，不自动地理过滤 |
| allow_network | 默认false；crawl或Brave阶段须明确true |
| stages | 默认discovery→collection→evidence→review→delivery；existing默认跳过discovery |
| collection | `{mode:"crawl"}`或`{mode:"existing",input_dir:"..."}`；已有目录必须含pages.json |
| discovery | provider=plan、max_queries=6、api_budget=6、results_per_query=5，可选import_results |
| time_range | basis=publication或event；since/until为YYYY-MM-DD或null，含起止日期 |
| review | 可选decisions_path，引用已有证据ID的项目归并记录 |
| delivery | 默认json、markdown、csv；可加excel。JSON/Markdown始终作为可审计核心输出 |

stages必须按既定顺序；evidence依赖collection、review依赖evidence、delivery依赖review。可只运行discovery生成计划；existing模式不能运行discovery。文件路径相对于任务JSON位置解析。

budget默认：max_pages=6、max_depth=1、workers=3、timeout=25、delay=1、retries=1、max_bytes=12582912、browser=false、max_per_page=30、proximity=100。max_pages是每个来源的累计页数上限，含失败页；21个来源各6页最多126页，不是整个任务6页。max_per_page为每网页/整份PDF的线索上限。限制是访问预算，不保证全面覆盖。

## 文件与恢复

默认output-root为仓库outputs。新任务目录必须为空；inputs快照不允许直接修改。各阶段路径见status.json；派生输出位于阶段/attempt-001等目录。抓取恢复沿用collection检查点；派生结果重建用新attempt保留历史。

扩大页数/深度与新核验输入会被记录到task.json.changes，并持久化需要重算的阶段。进程中断后，resume仍会重新生成受影响的下游，不把旧报告当作最新结果。

不自动重放中断的Brave搜索，也不自动重试已产出结果的付费搜索阶段。需要额外搜索时，检查query_status后另建带明确预算的发现任务。

## 本机安装

```powershell
.\scripts\install.ps1 -Profile research -Python '完整的python.exe路径'
# 仅在确需旧采集器且repos已准备好时使用完整安装：
.\scripts\install.ps1 -Profile full -Python '完整的python.exe路径'
# 浏览器下载需显式追加 -InstallBrowser
```

安装使用本脚本所在仓库，不固定D/E盘。full先检查外部仓库，未提供时不会自动克隆。安装成功记录本机.runtime.json（不提交Git）。SCRAPING_REPOS可设置外部采集器目录；SCRAPING_PROCESS_TIMEOUT设置旧采集器默认超时秒数（默认600）。
