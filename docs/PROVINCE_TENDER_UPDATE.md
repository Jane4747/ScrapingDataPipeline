# 分省医疗数字化采购采集（第一、二批）

本文件记录分省/分市采集的口径、入口、预算、风控处理与已知缺口。它补充
`docs/TENDER_UPDATE_DAGU.md`（央采 + 全国平台 + 北京平台三平台版本），两者共用同一套
字段契约与 Dagu 交付方式，但**覆盖范围完全不同，数字不可互相替代**。

## 1. 采集范围（固定，不随归档日变化）

| 项 | 值 |
| --- | --- |
| 日期范围 | 2024-01-01 至 2026-10-29 |
| 日期口径 | 公告发布日期（`publishTime`），非中标日期、非归档日期 |
| 业务分类 | 政府采购 `DEAL_CLASSIFY=02` |
| 公告类型 | 结果公告 `0202`、招标公告 `0201` |
| 关键词 | 医、卫生、疾控、妇幼、血站、急救（逐词检索） |
| 入口 | 全国公共资源交易平台省级/市级检索：`SOURCE_TYPE=1` + `DEAL_PROVINCE`（省级）+ `DEAL_CITY`（市级） |
| 窗口顺序 | 最新月份优先（`newest_first`），保证预算不足时先落最近的数据 |
| 输出字段 | 22 列，与三平台版本一致，见 `pipeline/research/tender_fields.py` |

批次成员写死在 `pipeline/research/province_update.py` 的 `BATCHES`，`--regions` 参数是保留位，
不能改动批次归属——避免"跑着跑着范围变了"。

- 第一批（9 个区域）：上海、北京、深圳、广州、江苏、浙江、湖北、四川、山东
- 第二批（24 个区域）：广东、河南、福建、湖南、安徽、陕西、重庆、辽宁、天津、河北、江西、
  广西、山西、云南、贵州、黑龙江、吉林、内蒙古、新疆、甘肃、宁夏、青海、海南、西藏

深圳、广州是**市级口径**（`DEAL_PROVINCE=440000` + `DEAL_CITY=440300/440100`）；第二批的广东是
**省级口径**，两者在省级窗口上必然重叠，汇总时按网址去重，重叠部分不计入两省独立增量。

## 2. 运行方式

```powershell
# 1) 规划 + 生成 DAG（第一批；首批已生成过，续跑必须带 -Resume）
.\scripts\start-province-update.ps1 -Batch 1 -Start 2024-01-01 -End 2026-10-29 `
  -TaskId province-b1-2024-20261029 -Resume -NoBrowser

# 2) 只校验范围、不落盘
python -B -m pipeline.research.province_update plan --batch 2 ... --dry-run

# 3) 单区域重跑（调试用，需先设任务目录）
$env:PROVINCE_UPDATE_TASK_DIR = "$PWD\outputs\province-updates\<task>"
python -B -m pipeline.research.province_update run-region --region 320000
```

DAG 结构：`verify` → 每个区域一个 `run-region` 步骤（互不依赖，可并行）→ `summary` → `export`。
区域步骤 `continue_on.failure`，一个省失败不拖垮整批，最后汇总会如实标 `partial`。

预算按**区域**计：`--max-api-calls 1600`、`--max-details 1400` 是每个区域的额度，不是整批共享。

## 3. 风控处理（revision 2 的由来）

第一批首次运行（run `...-ba21b4`，2026-10-30 11:08–11:26）在 `max_active_steps: 5` 下让 9 个进程
同时打同一接口，每个区域约 79–101 次请求后被平台以 `HTTP 200 + code 800` 拦下，约 18 分钟内
累计约 700 次请求。预算（1600/区域）远未用完，所以那次的 partial **不是预算问题，是速率问题**。

revision 2 改了三处，均属"降低压力"，不涉及任何绕过：

1. **跨进程共享节流**（`national_ggzy.py --pace-file/--pace-interval`）：以文件锁 + 时间戳文件记录
   全机最后一次请求时间，N 个 worker 合计仍为每 `--delay`（3.5s）一次请求。此前串行 3.5 秒的
   采集长时间稳定，因此这个速率是已验证安全的速率。
2. **一次冷却重试**（`--challenge-cooldown 900 --challenge-retries 1`）：被拦后等 15 分钟重试一次，
   仍被拦就 `StopCollection` 并写明原因，不换 IP、不换 UA、不重放验证码。
3. **并发降到 3**（`MAX_ACTIVE_REGIONS`）：同时开 3 个区域进程，配合共享节流，避免 9 个浏览器
   实例同起同落。

代价是变慢：合计约 3400 个检索窗口，按 1 请求/3.5 秒约需数小时量级，属预期。

### 2026-10-30 16:25 决策：不提速

实测 16:22 时点，3 并发、0.4 请求/秒已连续稳定运行 2 小时，风控 0 次、证书错误 0 次。按每窗口
3.2 次请求（检索 + 详情 + 原文）折算，单区域跑完 408 个窗口约 2.5–2.7 小时：

- 第一批剩余 6 个排队区域 + 3 个收尾区域，预计 22:00 前后完成；
- 第二批 24 个区域，3 并发约 21 小时，次日傍晚完成。

用户选择**保持现状、稳定优先**，不提高并发（5 并发 + 2.5 秒间隔属未验证区间，首发 9 并发曾被
`code 800` 拦下）。因此 `MAX_ACTIVE_REGIONS=3` 与 `--delay 3.5` 不再调整；需要更快只能靠缩小口径，
那属于新建任务，不能用续跑表达。

### revision 3：传输层重试与导出占用

第二轮（run `...-1a65f7`）在 13:58 同时出现两种基础设施故障，导致整批判 failed（范围与预算均未变）：

1. 三个在跑区域同时报 `Page.evaluate: TypeError: Failed to fetch`；紧接着另外六个区域一启动就报
   `ERR_CERT_AUTHORITY_INVALID`。入口页 `page.goto` 与检索 `page.evaluate` **都没有重试**，一次瞬时
   TLS/DNS 抖动就结束整个区域。
2. 收尾 `export` 步骤把 `workbook-building.xlsx` 重命名覆盖交付表时失败——因为交付表正在编辑器里打开
   （Windows 文件占用），于是一个被占用的文件让整批判 failed。

修法：

- 入口页与检索请求都加**有界传输重试**（`--net-retries 2`、`--net-backoff 60`，即 60/120 秒退避），
  只对 `Failed to fetch` / `net::ERR_*` / 超时这类"请求没到服务端"的故障重试；**证书校验保持开启**，
  不降级为忽略证书。重试次数记进 `state.json` 的 `net_retries` 与 `failures`。
- 导出重命名失败时**回退为带时间戳的文件名**（`…_202610301406.xlsx`）并打印 `target_locked` 警告，
  不再让整批失败。也就是说：跑完后如果你正开着旧表，新表会落成另一个名字，而不是报错退出。

### revision 5：主机重启让节流文件"卡住"整批（2026-10-30 19:00 定位）

18:09 采集整批静默停止，报障现象是"进程全没了、`progress.json` 停在 18:09、之后再启动也不动"。
根因不是风控，也不是预算：

- 共享节流文件 `.source-pace` 里存的是 `time.monotonic()`。**主机重启后这个计数器从 0 重新开始**
  （实测重启后 `monotonic≈1517`），而文件里还是重启前的 `117880`。于是
  `gap = now - last` 为负，`interval - gap` 变成约 **32 小时**，三个 worker 全部睡在临界区里、
  并且**一直持有锁文件**不释放。
- 后续区域的 reclaim 逻辑等满 120 秒后 `unlink()` 这把被持有的锁，Windows 上直接
  `WinError 32`（另一个程序正在使用此文件），异常没人接 → 该区域 `exit_code 3` 结束
  （广州 19:02 的 `stop_reason` 就是这条）。

修法（只改节流辅助函数，不动检索范围/日期/预算/间隔）：

1. 时间戳落在"未来"（重启前的值）时按**未知**处理，不再当作需要等待的间隔；
2. `gap` 用 `0 <= gap < interval` 判断，避免 0 值或负值被误算成长等待；
3. 抢锁超时后的 `unlink` 失败只记录、不抛出——锁被别人合法持有不是该区域的错。

对应新增两条离线测试：`test_shared_pace_ignores_timestamp_from_before_a_reboot`、
`test_shared_pace_survives_a_stale_lock`。

**人工恢复的固定顺序**（`scripts/resume-province-batch.ps1` 已按此实现并会自己检查）：

1. 先确认区域锁里的 pid 已经不存在——进程还活着就**不要**删锁，先停它；
2. 清掉 `regions/*/source.lock`、`.source-pace`、`.source-pace.lck`；
3. 用 `dagu start` 起同一个 DAG（`dagu enqueue` 在遗留僵尸 run 的队列里会报
   `dag-run is not queued`，此时改用 `start` 直跑，产物与续跑语义完全一致）。

另外记一条环境事实：这个采集是**当前会话的子进程**，关掉 WorkBuddy 窗口会把 dagu 与所有浏览器
一并带走。要跨会话跑，用普通控制台窗口执行
`powershell -ExecutionPolicy Bypass -File scripts\resume-province-batch.ps1 -Batch 1`。

### revision 6：交付说明被堆栈打断、`publish` 静默跳过（2026-10-31 07:30）

两批跑完后核对交付件才发现的两个**投放层**问题，都不影响已采到的数据：

- `stop_reason` 里的 Playwright 报错是多行堆栈（`Page.evaluate: TypeError: Failed to fetch` + 三行
  `at ...`），被原样写进「逐区域覆盖」的 markdown 表格单元格，**表格直接断行**。第 2 批 24 个区域
  里有 22 个是这种原因，等于整张覆盖表都读不了。现在用 `table_cell()` 把它压成一行：折叠空白、
  去掉 `at ...` 帧、转义 `|`、超长截断。`summary.json` 仍保留原始全文，机器读不受影响。
- `publish` 子命令不带 `--target` 时，argparse 给的默认值是**空字符串**而不是 `None`，
  于是 `if target is None` 的 `publish.json` 回退分支永远进不去，命令打印
  `{"status": "skipped", "reason": "no publish target configured"}` 后以 0 退出——**看起来成功，
  实际没投放**。改成 `args.target or None`。

对应新增两条测试：`test_publish_keeps_a_traceback_stop_reason_on_one_line`、
`test_publish_without_target_falls_back_to_the_configured_folder`。两批都已用修正后的代码重投放，
表格恢复正常（第 1 批 16 个文件、第 2 批 31 个文件，`records` 分别为 3411 / 777）。

## 4. 产物结构

```
outputs/province-updates/<task_id>/
├── request.json               # 不可变契约（含各文件 code_sha256）
├── code-revisions/current.json# 代码修订记录（revision 2 = 节流与冷却）
├── snapshot-<pid>.json        # 各次运行的操作快照
├── regions/<id>/
│   ├── state.json             # 可恢复状态：pending/completed_windows/notices/records
│   ├── progress.json          # 实时计数（api_calls_total、pending_search_windows…）
│   ├── region-progress.json   # 区域级收尾记录（stop_reason、challenge_waits、exit_code）
│   ├── records.json           # 该区域 22 字段记录
│   ├── 公告明细.csv            # 同内容的可读副本
│   ├── lists/                 # 每次检索的原始响应（含缓存索引，可复算）
│   ├── raw/                   # 公告原文 HTML
│   └── attempts/<时间戳>/      # 每次尝试的代码版本、节流参数、回执
├── summary.json               # 各省状态、记录数、缺口、去重数
└── delivery/
    ├── 分省医疗数字化采购_第N批_YYYY年至今.xlsx
    └── coverage.png           # 版式自查截图（TENDER_RENDER_QA=1 时生成）
```

工作簿两个页签：**数据**（22 列，动态行数）与**采集范围**（逐区域列出状态/记录数/缺口与说明）。

## 5. 交付落地（爬取完成后自动投放）

用户指定的交付目录：`E:\CAICTBigData\移动项目沟通\政采_公共资源网_全国与地方_1030`

批次配置在任务目录的 `publish.json`（不进请求契约，因此不影响续跑与 `verify`）：

```json
{"target": "E:\\CAICTBigData\\移动项目沟通\\政采_公共资源网_全国与地方_1030"}
```

`export` 步骤成功后会调用 `publish(task_dir)`，把成品复制为：

```
政采_公共资源网_全国与地方_1030\
  00_全国层_央采与全国平台\        ← 上一轮三平台汇总，按来源切，仅作参照
  01_地方_分省第1批\
    分省医疗数字化采购_第1批_2024年至今.xlsx
    公告明细.csv / records.json / summary.json / request.json
    交付说明_第1批.md
    分区域\<区域>_公告明细.csv
  02_地方_分省第2批\              ← 结构相同
```

几点行为约定：

- **幂等**：重复执行覆盖同名文件，不会产生重复目录或重复行。
- **数字只搬运不重算**：`交付说明` 里的记录数、缺口、去重数全部来自 `summary.json`，即 `summarize`
  步骤已经算好的值，复制环节不引入新的口径。
- **目标文件被占用不致命**：工作簿/CSV 被 Excel 打开导致写入失败时，落成带 `_更新<时分秒>` 的邻居
  文件；投放出错只报 `publish_failed`，不会把已完成的采集判为失败（revision 4）。
- **预览会被清理**：采集期间放在根目录的 `进行中预览_*.xlsx` 与 `_采集进行中说明.md`，在正式投放时
  自动删除，避免与最终表混淆。

第二批由 `scripts/supervise_province_batches.py` 接力：第一批 Dagu 运行结束后自动入队
`pt-province-b2-2024-20261029`，两批都结束后再统一投放。该脚本幂等，状态写在
`outputs/province-updates/_supervisor.json`。

手动重投（例如改了目标目录）：

```bash
set PROVINCE_UPDATE_TASK_DIR=<任务目录>
python -B -m pipeline.research.province_update publish
```

## 6. 已知缺口（必须随结果一起读）

- **入口覆盖 ≠ 全省全量**：省级/市级检索只反映全国平台收录的部分，各省门户（如省公共资源交易
  中心、省政府采购网）收录更全者不在本链路内。任何"某省 N 条"都应读作"该入口收录 N 条"。
- **公告数 ≠ 项目数**：同一项目会有招标、结果、变更等多条公告，且多标包会拆多行。
- **`city_unconfirmed`**：市级口径下，省级命中但正文/字段未出现市名的记录数，单独计数，不当作
  已确认的市数据使用。
- **`partial` 的含义**：`pending_search_windows > 0` 即有未检索窗口；`status=partial` 表示覆盖不完整，
  不能当"跑完了"。
- 首批首次运行的 446 条记录是在被风控打断前落下的，续跑会在此基础上继续追加，不会丢弃。
- **2024 年数据为什么一开始看不到**：窗口顺序是"最新月份优先"，2024 排在最后。首跑只覆盖到 2025-07
  起就被限流，所以 11:26 的交付表里没有 2024。续跑后 2024 已开始落表（北京 11、上海 28、深圳 33），
  但这些只进 `state.json` / `公告明细.csv`，要等 `summary`/`export` 步骤跑完才会写进正式工作簿。
  需要中途查看时用 `python -B -m scripts.live_province_snapshot <task_dir> <out_dir> <文件名>`，
  它复用同一套字段映射（`公告日期`→`时间`）与去重规则，只写单独目录，不动正式交付文件。

- **本轮到 2026-10-31 07:28 为止的真实进度**：两批合计 **4188 条**（第 1 批 3411、第 2 批 777），
  **33 个区域没有一个完成声明的检索范围**，剩余未检索窗口 **1669（第 1 批）+ 8624（第 2 批）= 10293**。
  第 2 批 24 个区域、平均每区只发出 60 次左右请求就被打断，夜里同一 IP 的配额已经被第 1 批吃掉，
  这是"分批推进"而不是"再跑一次就能补齐"的量级差别。

## 7. 相关文件

| 文件 | 作用 |
| --- | --- |
| `pipeline/research/province_update.py` | 批次定义、契约、DAG 生成、区域调度、汇总、导出 |
| `pipeline/research/national_ggzy.py` | 全国平台采集器（本次增加省/市维度、共享节流、冷却重试） |
| `scripts/export_province_workbook.mjs` | 工作簿生成（数据页 + 采集范围页） |
| `scripts/live_province_snapshot.py` | 采集中途按正式口径生成"进行中快照"，不动正式交付件 |
| `scripts/supervise_province_batches.py` | 无人值守接力：第一批结束入队第二批，两批结束统一投放 |
| `scripts/start-province-update.ps1` | 校验 → 起 Dagu → 入队 → 写 launch.json |
| `scripts/resume-province-batch.ps1` | 会话外续跑：查锁里 pid → 清陈旧锁/节流文件 → `dagu start` 直跑 |
| `tests/test_province_update.py` | 批次清单、表单参数、省市校验、去重、预算、锁、节流、DAG 结构 |
