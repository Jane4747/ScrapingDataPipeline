# 代码学习总结：探针脚本与仓库归档规范

本轮"学习代码"包含两部分：读懂本任务链唯一自编脚本 `wxnum_probe.py`，以及读懂仓库既有的
想法树归档代码（`scripts/idea_tree_writer.py` 与 `archive_local_crawler_stack_20261027.py`），
后者直接决定了本次归档为什么这样组织。

## 1. wxnum_probe.py 解决什么问题

目标：按「省 x 运营商」批量召回公众号名称与微信号，避免逐省人工搜索。数据源是第三方收录站
`wxnum.cn` 的 `/search/?w=` 检索页。

分四层设计：

| 层 | 实现 | 要点 |
| --- | --- | --- |
| 检索词构造 | `PROVINCES`(31) x `OPS`(3 家，每家 4 个模板) | 模板形如 `{p}移动10086`、`{p}移动发布`，`{p}` 填省名；同时给出**应匹配的认证主体关键词** |
| 页面抓取 | `fetch()`：UA 伪装、超时 20s、失败重试 2 次、间隔 2s | 只用标准库 `urllib`，不引入依赖 |
| 卡片解析 | `search()`：按 `<a href="/xxx.html"` 用 `re.split` **切块**，块内分别取 h3 名称、`s-r-corp` 主办方、`l-infos` 简介 | 切块是修复后的写法，见下节 |
| 主体过滤 + 取号 | 只保留主办方包含对应运营商主体的卡片；命中后请求详情页，用 `公众号ID[:：]` 正则取微信号 | 限速：关键词间 1.2s、详情间 1.0s |

`--probe` 只跑广东、四川两省并输出 `probe2.json`；无参数则跑 31 省输出 `candidates.json`。
进度打到 stderr、结果写 JSON，符合本仓库"进度与结果分离"的习惯。

## 2. 一个真实修复过的缺陷：跨卡片错配

初版用一条跨卡片正则贪婪匹配（`ITEM_RE` 一次性抓 href、h3、主办方），结果把
**OPPO 广东移动通信**的条目误判进"广东移动"名下——因为整页多个卡片连在一起，
`.*?` 会跨越卡片边界，把上一张卡的 href 配到下一张卡的主办方。

修法：改为先按卡片起始标签 `re.split(r'(?=<a href="/[a-z0-9\-]+\.html")', html)` 把页面切成独立块，
再在**每个块内部**分别匹配。`CARD_HREF.match(block)` 保证块首即本卡链接，
`CARD_CORP` / `CARD_H3` / `CARD_INFO` 均限定在块内，物理上杜绝跨卡串味。
微信号正则也放宽为允许中间夹 HTML 标签：`公众号ID[:：]\s*(?:<[^>]+>\s*)*([A-Za-z0-9_\-]{4,40})`。

**教训**：抓列表页时，"整页一条正则"几乎必然在卡片边界处产生错配；按卡片边界切块再块内解析，
是比调正则贪婪度更稳的做法。

## 3. 为什么主动中止全量跑（判断，不是故障）

`probe2.json` 显示的是**收录源的结构性偏差**，不是解析 bug：

- 广东移动只召回「广东移动一机游」`gh_f140c3e1d950`、「广东移动法律服务」`gh_6dd1152bba21`；
  真正的省级主号（广东移动10086、中国移动广东公司）**没有收录**。
- 广东电信只召回「广东电信共青团」；四川电信、四川联通 **0 命中**；
  四川移动召回的是掌厅号与攀枝花地市号。
- 该站对"订阅号/发布号"覆盖较好，对"服务号/营业厅号"覆盖差，且混有代理商号。

结论：继续跑 31 省只会批量产出噪声，因此停止全量模式，改走企业信息平台的**主体维度**
（按省分公司主体一次列全账号）。`candidates.json` 从未生成，不可据此做覆盖率统计。
脚本本身保留在 `artifacts/code/`，因为"卡片切块 + 主体白名单过滤"这套解析思路可移植到别的收录源。

## 4. 从仓库代码学到的归档规范（本次据此整改）

`scripts/idea_tree_writer.py` 的约束比想象中严格，上一轮手写的 `tree.md` 并不合规：

- **`tree.json` 是唯一权威源**，`tree.md` 由 `render_tree()` 从 JSON 渲染。工具注释明确写了原因：
  手写会让"事实与大纲在每轮工作后逐渐漂移"。节点状态只存 JSON。
- **必填字段**：`id`、`created_at`、`updated_at`、`status`、`nodes`；可选 `status_note`、`requirement`、
  `theme`、`tool`、`delivery`、`result`。
- **状态枚举固定**：`completed` / `partial` / `open` / `planned` / `awaiting_jane`，越界即 `ValueError`。
- **第一个节点 id 必须是 `need`** 且 `parent` 为 `null`；节点 id 不可重复；父节点必须在子节点**之前**出现。
- 渲染产物是简洁的节点大纲，详细叙述要另放 `DETAILS.md` / `CODE_SUMMARY.md`，由 tree.json 的
  `delivery` 字段和节点文本里的相对链接指过去。

`archive_local_crawler_stack_20261027.py` 给出的完整归档链，本次沿用：

1. 源文件**副本**进 `artifacts/`，原件不动；`SOURCE-MANIFEST.json` 记录每个副本的 `bytes`、
   `sha256`、`source_sha256`、用途与分类。
2. 归档工具自身与 `idea_tree_writer.py` 一并留存，保证结果可重现。
3. `check_no_secrets` 扫描所有归档文件，排除真实密钥/私钥（本轮源文件仅含公开 URL 与 UA，无密钥）。
4. `verify_archive()` 离线校验：树合法、tree.md 与重新渲染结果一致、清单哈希逐一比对、
   内部相对链接目标存在、无敏感模式；报告写 `ARCHIVE-VERIFICATION.json`。
5. 归档交付状态与业务事实状态**分开记**：`result.archive_status=completed`，整体 `status=partial`。
   归档完整不等于事实已核验完，也不等于采集跑完。

本次还额外保留上一轮手写稿为 `artifacts/docs/tree-handwritten-20261102.md`，
遵守 AGENTS.md「不修改历史报告来掩盖失败、新结果进新目录」的口径。

## 5. 环境事实

- 仓库运行时 `D:/Anaconda3/envs/BigData/python.exe`；本脚本仅用标准库，系统 Python 亦可运行。
- 归档脚本不联网、不采集、不调用模型，只做本地复制、渲染与校验；可重复执行（覆盖本树自身产物，
  但不会碰 `artifacts/docs/` 下的历史草稿）。
