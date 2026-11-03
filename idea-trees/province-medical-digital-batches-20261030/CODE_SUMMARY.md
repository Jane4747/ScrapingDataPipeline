# 分省医疗数字化采购采集：本次代码总结

本轮把"全国平台省级/市级检索"接成可分批、可续跑、可交付的分省采集链路，并修掉了第一批首跑暴露的
并发限流问题。新增 3 个文件、修改 1 个既有采集器；Dagu 在一个图里并排展示 9（后续 24）个区域进程的
执行、日志与失败状态，最终统一输出 22 个字段。

归档日期：2026-10-30（北京时间）。采集请求固定为 **2024-01-01 至 2026-10-29，按公告发布日期筛选医疗
数字化采购信息**。第一批 9 个区域累计 **446 条记录**、整体 **partial**，待检索窗口约 3.2k——
这既不是 446 个独立项目，也不是 9 个区域的全量覆盖。

## 五层流程

### 1. 数据源层（入口与参数）

- 接口：`/information/pubTradingInfo/getTradList`（近一年）与 `/his/information/pubTradingInfo/getTradList`（历史），
  参数取自站点前端 JS 契约。
- 分省维度：`DEAL_PROVINCE`（省级）、`DEAL_CITY`（市级）。深圳 `440300`、广州 `440100` 走市级口径，
  其余走省级口径；第二批的广东是省级口径，与深圳/广州在省级窗口上必然重叠，汇总按网址去重。
- 固定口径：`DEAL_CLASSIFY=02`（政采）、`SOURCE_TYPE=1`、公告类型 `0202`（结果）+`0201`（招标）、
  六关键词逐词检索、窗口按"最新月份优先"排列。

### 2. 调度层（Dagu 图 + 逐区域进程）

- `verify` → 每个区域一个 `run-region` 步骤（互不依赖）→ `summary` → `export`。
- 每区域独立输出目录、独立预算（`--max-api-calls 1600`、`--max-details 1400` 是**每区域**额度）、
  独立 `source.lock`，互不覆盖。
- 区域步骤 `continue_on.failure: true`：一个省失败不拖垮整批，汇总如实标 partial。

### 3. 风控治理层（本轮真正的教训）

第一批首跑用 `max_active_steps: 5` 让 9 个进程同时打同一接口，结果每个区域约 79–101 次请求后
返回 `HTTP 200 + code 800`，18 分钟累计约 700 次请求即被拦。判定：**不是预算问题，是并发速率问题**
（1600/区域的预算远未用尽），且此前串行 3.5 秒/请求长时间稳定。

revision 2 的三处改动都只降低压力，不绕过任何挑战：

1. **跨进程共享节流**：`--pace-file` 记录全机最后一次请求的 `time.monotonic()`，配 `O_EXCL` 锁文件串行化
   写入，N 个 worker 合计仍是每 `--delay`（3.5 秒）一次请求。实测聚合速率 0.30 请求/秒，与设计一致。
2. **一次冷却重试**：`--challenge-cooldown 900 --challenge-retries 1`，被拦后等 15 分钟重试一次，仍被拦
   就 `StopCollection` 并在 `stop_reason` 写明，不换 IP、不换 UA、不重放验证码。
3. **并发降到 3**：同起同落的 9 个浏览器实例本身就是可疑流量特征。

代价是变慢：3.2k 个待检索窗口按 1 请求/3.5 秒约需数小时。

### 4. 字段层（22 列复用）

复用 `tender_fields` 的 22 列契约（时间、项目名称、产品、招标单位、客户标签、中标单位、运营商类型、
中标金额（万元）、场景、评审专家、网址、公告类型、省份、项目编号、中标金额原文、信息缺口、标签依据、
两项资格要求、来源平台、资格要求出处、原文文件），与三平台版本完全一致。省份按区域补写；
`来源平台` 标注为"全国公共资源交易平台·<区域>（省级聚合入口）"，避免读者误以为是省门户数据。

### 5. 存储输出层

- `regions/<id>/`：`state.json`（可恢复状态）、`progress.json`（实时计数）、`region-progress.json`
  （收尾记录：`stop_reason`、`challenge_waits`、`exit_code`）、`records.json`、`公告明细.csv`、
  `lists/`（原始响应）、`raw/`（原文 HTML）、`attempts/`（每次尝试的代码哈希与节流参数）。
- `summary.json`：逐区域状态、记录数、缺口、去重数、`city_unconfirmed`。
- 工作簿两页：数据页（22 列、动态行数）+ 采集范围页（逐区域覆盖状态与说明）。

## 本次修改的文件

| 文件 | 变更 |
| --- | --- |
| `pipeline/research/province_update.py` | 新增：批次成员、不可变契约、DAG 生成、区域调度、汇总、导出 |
| `pipeline/research/national_ggzy.py` | 修改：省/市维度参数、省份文本校验、`city_unconfirmed`、最新优先窗口、共享节流、冷却重试 |
| `scripts/export_province_workbook.mjs` | 新增：分省工作簿（数据页 + 采集范围页） |
| `scripts/start-province-update.ps1` | 新增：校验 → 起 Dagu → 入队 → 写 launch.json |
| `tests/test_province_update.py` | 新增：批次清单、表单参数、省市校验、跨区域去重、预算、锁、共享节流、DAG 结构 |
| `docs/PROVINCE_TENDER_UPDATE.md` | 新增：口径、风控处理与缺口说明 |

## 验证

- 离线回归 31 项通过（`tests.test_province_update` + `tests.test_tender_update`）。
- DAG 两次 `validate` 退出码 0；第一批、第二批分别生成 9 / 24 个区域步骤。
- 单省小预算端到端试跑：省级记录字段正确落表，工作簿版式经截图核对无错位。
- 代码修订记录 revision 2 保留原请求哈希，`verify` 可复算；范围、日期、预算、字段均未变。

## 未完成（不要读成已完成）

- 第一批仍在续跑，`pending_search_windows` 未清零前一律 partial。
- 第二批 24 个区域已生成契约与 DAG（`pt-province-b2-2024-20261029`），但**未入队**——同一接口再叠 24 个
  进程会立刻重演限流，必须等第一批收尾。
- 省级聚合入口收录 ≠ 各省门户全量；公告数 ≠ 项目数。
