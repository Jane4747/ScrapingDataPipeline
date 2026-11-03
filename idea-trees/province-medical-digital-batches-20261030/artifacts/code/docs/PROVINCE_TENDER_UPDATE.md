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

## 5. 已知缺口（必须随结果一起读）

- **入口覆盖 ≠ 全省全量**：省级/市级检索只反映全国平台收录的部分，各省门户（如省公共资源交易
  中心、省政府采购网）收录更全者不在本链路内。任何"某省 N 条"都应读作"该入口收录 N 条"。
- **公告数 ≠ 项目数**：同一项目会有招标、结果、变更等多条公告，且多标包会拆多行。
- **`city_unconfirmed`**：市级口径下，省级命中但正文/字段未出现市名的记录数，单独计数，不当作
  已确认的市数据使用。
- **`partial` 的含义**：`pending_search_windows > 0` 即有未检索窗口；`status=partial` 表示覆盖不完整，
  不能当"跑完了"。
- 首批首次运行的 446 条记录是在被风控打断前落下的，续跑会在此基础上继续追加，不会丢弃。

## 6. 相关文件

| 文件 | 作用 |
| --- | --- |
| `pipeline/research/province_update.py` | 批次定义、契约、DAG 生成、区域调度、汇总、导出 |
| `pipeline/research/national_ggzy.py` | 全国平台采集器（本次增加省/市维度、共享节流、冷却重试） |
| `scripts/export_province_workbook.mjs` | 工作簿生成（数据页 + 采集范围页） |
| `scripts/start-province-update.ps1` | 校验 → 起 Dagu → 入队 → 写 launch.json |
| `tests/test_province_update.py` | 批次清单、表单参数、省市校验、去重、预算、锁、节流、DAG 结构 |
