# 医院官网与采购栏目核查

这套脚本把 2026-10-27 逐院查找招标采购网址的做法固化：先离线计划，再授权联网探测，最后受控回写工作簿。目录约定沿用本仓库：`scripts/` 放脚本、`configs/` 放配置、`outputs/` 放每次产物、`tests/` 放离线测试。

## 为什么分层

逐院检索的实际瓶颈不是抓取，而是**判定**：一个 host 到底是不是这所医院自己的官网、栏目是不是真的发布过采购公告、平台入口能不能当成医院渠道写进去。2026-10-27 第一轮把 `ggzyfw.beijing.gov.cn` 一类的平台域名误截成 `beijing.gov.cn`，污染了 8 行。所以现在分三层：

| 层 | 命令 | 是否联网 | 作用 |
|---|---|---|---|
| 计划 | `hospital_site_probe.py --plan` | 否 | 产出每家医院的候选域名、检索式、不可探测的平台域名标记 |
| 探测 | `hospital_site_probe.py --probe --allow-network` | 是 | 抓首页、按关键词与路径打分找采购栏目候选 |
| 回写 | `hospital_workbook_writer.py` | 否 | 默认干跑，`--apply` 才写，先备份，保留未命中行的人工结论 |

## 1. 生成计划（不联网）

名单 `outputs/<任务>/roster.json` 每行可带 `candidate_hosts`：

```json
[
  {"hospital_id": 1, "hospital_name": "北京大学第三医院", "candidate_hosts": ["puh3.net.cn"], "level": "三级", "owner": "市属"},
  {"hospital_id": 2, "hospital_name": "示例平台占位院", "candidate_hosts": ["ccgp-beijing.gov.cn"], "level": "二级"}
]
```

```powershell
$py = (Get-Content .runtime.json -Raw | ConvertFrom-Json).python
& $py scripts/hospital_site_probe.py --roster outputs/demo/roster.json --plan --output-dir outputs/demo/plan
```

产出 `probe_plan.json` 与 `scope.json`。平台域名与集团域名分别标记：`platform_host` 的 `probe` 为 false，永远不会被当成医院本级官网；`group_host` 会被探测，但需要人工判断该站点是否真的承载这所医院。`scope.json` 里 `network_requests` 恒为 0，`planned_query_count` 是待执行的检索式数量。

## 2. 执行探测（需显式授权，且额外用于外网段）

```powershell
& $py scripts/hospital_site_probe.py --roster outputs/demo/roster.json --probe --allow-network --output-dir outputs/demo/probe
```

没有 `--allow-network` 会直接失败，不会静默联网。每次请求受 `configs/hospital_site_probe.json` 约束：超时、响应大小、单页链接数、robots 策略。首页重定向到平台或集团域名时记为 `not_hospital_homepage`，不当作命中。

`probe_records.json` 每行含 `homepage_url`、`top_candidate`、`channel_status`（`found` / `not_found` / `unknown`）与 `evidence` 列表。

## 3. 回写工作簿（默认不写）

```powershell
# 先看计划改哪些单元格
& $py scripts/hospital_workbook_writer.py --workbook 清单.xlsx --sheet 05-全量明细 --records outputs/demo/probe/probe_records.json

# 确认后再写：自动备份 .bak，只改命中行，并重建清单页
& $py scripts/hospital_workbook_writer.py --workbook 清单.xlsx --sheet 05-全量明细 --records outputs/demo/probe/probe_records.json --apply --update-channel
```

列位置可改：`--head-row --name-col --level-col --owner-col --homepage-col --status-col --channel-col`。只有加 `--update-channel` 时才会用本级栏目覆盖 S 列，避免把平台入口写成医院栏目。`--list-sheet` 重建记录表，收录所有未 `found` 的行（幂等删除重建）。

## 配置

`configs/hospital_site_probe.json`：

- `column_keywords`：strong（招标/采购/中标/成交/比选/遴选/询价/竞价）权重 3，medium（院务公开/信息公开/通知公告/公示/公告）权重 1，exclude（招聘/挂号等）直接剔除；
- `column_path_hints`：URL 路径含 `zb` `cg` `caigou` `tender` `xxgk` 等再加分；
- `platform_domains` / `group_domains`：平台与集团域名名单，是上一轮误写事故的护栏；
- `request`：`timeout_seconds`、`max_bytes`、`max_links_per_page`、`respect_robots`、`follow_top_candidates`。

## 已知边界

- 栏目页存在**不等于**发布过招标公告；命中后仍需人工核对发布日期与主体。
- 未命中**不等于**没有采购：可能只有微信公众号、上级单位或区政府页面统一发布。
- 探测只取单页链接；栏目分页、动态列表、`mHtml` 附件不在范围内。
- 离线测试覆盖计划、解析、回写与树渲染；测试通过不能代表真实网站可达。
- 回写前请确认编辑器实例不是旧快照：`get_pool_status` 核对 file_id 与时间戳。
