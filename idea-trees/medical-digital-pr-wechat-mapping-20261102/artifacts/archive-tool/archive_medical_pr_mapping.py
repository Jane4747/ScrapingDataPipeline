#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Archive the medical-digital PR mapping work into this repository's idea-tree format.

Follows the repository convention established by archive_local_crawler_stack_20261027.py:
`tree.json` is the authority, `tree.md` is rendered by scripts/idea_tree_writer.py,
source copies carry a SHA256 manifest, and the archive is verified offline afterwards.

This script does not crawl, call a model, or modify the delivered HTML files.
It upgrades the hand-written tree.md from the previous round into a compliant tree,
keeping a copy of that earlier draft under artifacts/docs/ rather than silently
overwriting history.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TREE_ID = "medical-digital-pr-wechat-mapping-20261102"
DEST = REPO / "idea-trees" / TREE_ID
HANDOVER = Path("E:/CAICTBigData/移动项目沟通/政采_公共资源网_全国与地方_1030")
sys.path.insert(0, str(REPO))
from scripts.idea_tree_writer import read_tree, render_tree, render_markdown, validate  # noqa: E402

# source path (absolute or repo-relative) -> (archive relative path, category, purpose)
SOURCES = [
    (REPO / "outputs/pr-gzh-wxnum/wxnum_probe.py", "artifacts/code/wxnum_probe.py",
     "probe_source", "按认证主体抓取省级运营商公众号的探针脚本（含卡片切块解析、限速与重试）"),
    (REPO / "outputs/pr-gzh-wxnum/probe2.json", "artifacts/evidence/probe2.json",
     "verification_evidence", "广东、四川两省试跑的原始召回结果，用于判定收录源覆盖偏差"),
    (REPO / "docs/medical-digital-pr-url-map.html", "artifacts/delivery/medical-digital-pr-url-map.html",
     "previous_delivery", "网址地图交付物副本（原件仍在 docs/）"),
    (HANDOVER / "medical-digital-pr-wechat-matrix.html", "artifacts/delivery/medical-digital-pr-wechat-matrix.html",
     "previous_delivery", "公众号矩阵交付物副本；原件已移至移交目录，此副本防止再次散落"),
    (REPO / "scripts/idea_tree_writer.py", "artifacts/archive-tool/idea_tree_writer.py",
     "repository_tree_tool", "父仓库已有的树渲染/校验工具，保留以便重现渲染结果"),
    (Path(__file__).resolve(), "artifacts/archive-tool/archive_medical_pr_mapping.py",
     "archive_tool", "本树的归档生成与离线校验脚本自身"),
]

SECRET_PATTERNS = [
    rb'(?i)\b(api[_-]?key|secret|password|token)\s*[:=]\s*["\'][^"\'\s]{8,}',
    rb'\bsk-[A-Za-z0-9]{20,}',
    rb'-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----',
]

DETAILS = """# 医卫数字化传播 Mapping：工作思路与取证口径

这是 2026-10-30 三轮对话的归档快照，2026-11-02 补齐代码归档与规范化树结构。
**归档交付 completed；事实覆盖仍 partial**：西藏、青海两省三家运营商无公开证据，另有 6 格待核，
探针脚本的全量抓取已主动中止，未产出可用于统计的全量候选集。

| 入口 | 用途 |
| --- | --- |
| [想法树](tree.md) / [结构化记录](tree.json) | 需求、方案、实现、决策、结果、缺口、下一步 |
| [代码学习总结](CODE_SUMMARY.md) | 探针脚本的设计、已修复缺陷、弃用原因与仓库归档规范学习 |
| [代码索引](CODE-INDEX.md) / [SHA256清单](SOURCE-MANIFEST.json) | 源文件副本、用途、字节数与哈希 |
| [归档校验](ARCHIVE-VERIFICATION.json) | 树一致性、哈希、内部链接、脱敏检查 |
| [交付物副本](artifacts/delivery/) | 两份 HTML 的独立快照 |

## 1. 需求与任务链

1. 用户给出「医卫数字化棋盘」材料（10 家机构 + 媒体矩阵 + 会议清单），要求"不放过任何一个网页路口"标注网址。
2. 追加：补 10 家企业在内地各省的公众号名称。
3. 追加：中国电信、中国联通还有哪些省的公众号。
4. 追加：把华为、讯飞医疗、卫宁、东软、创业慧康、东华医为、阿里健康的公众号入口并入同一页。

产出：`docs/medical-digital-pr-url-map.html`（60+ 可点击入口，按官网/政企/IR/媒体/会议分色）、
`medical-digital-pr-wechat-matrix.html`（31 省 x 3 运营商 + 7 家厂商）。
后者原件已移至 `E:/CAICTBigData/移动项目沟通/政采_公共资源网_全国与地方_1030/`，本树保存副本。

## 2. 证据纪律（本轮最重要的工作思路）

- **不推测、不编造**：查不到名称/网址就留空格，只写"检索词 + 应匹配认证主体"，绝不填猜测值。
  起草网址清单时曾误写一个未核实的学会域名，发现后当场删改。
- **证据强度分级**：强（运营商自有页面/公告、公司官方声明）、中（权威媒体、企业信息平台主体）、
  弱（二手教程，投放前必须复核）。
- **投放红线**：微信搜一搜里"帐号主体"必须与
  `中国移动通信集团XX有限公司` / `中国电信股份有限公司XX分公司` / `中国联合网络通信有限公司XX分公司`
  完全一致；主体为"XX科技有限公司""XX通信专营店"的是代理商，投进去等于给渠道导流。
- 公众号没有稳定 URL，只记名称与微信号；会议当年报名页等深链次年失效，与会议官网分开存档。

## 3. 证据源优先级（实测排序，可复用）

1. **企业信息平台"微信公众号"维度**（天眼查 `/swechat/`、启信宝 ability 页）——按省分公司主体
   一次列出该主体名下全部账号（名称 + 微信号 + 简介）。这是唯一能批量拿省级矩阵的路径，
   也是第二轮把账号数从 42 推到 98 的突破点。天津联通一次拿到 4 个、安徽联通 6 个、福建联通 4 个。
2. **省电信 189.cn 子站的公告/隐私政策页**——直接引用本省公众号全称。
   `gx.189.cn`（广西电信）、`yx.nx.189.cn`（宁夏电信）、`m.sc.189.cn`（四川电信）均命中。
3. **上市公司公告页脚 / 深交所互动易官方答复**——东华软件 `DHC_Software` 出自 2025 社会责任报告页脚；
   讯飞官方答复明示"官方微信公众号为'科大讯飞'、'科大讯飞集团'"，是 7 家里唯一由公司自己声明的口径。
4. **官网"联系我们"页脚与二维码区**——讯飞医疗、华为。
5. 官微文章页脚（创业慧康 `B-soft`）、微信服务市场主体页 `fuwu.weixin.qq.com`、
   省市党媒、政府网站办事指南。

**已排除的路径**：第三方公众号收录站 wxnum.cn 覆盖不全且噪声大（搜"广东移动"混入 OPPO 广东移动通信
与第三方花卡代理号，真正的省级主号反而缺失；收录的多是"法律服务/共青团/一机游"边缘号）；
省公司官网直连被反爬拦下（gd.10086.cn 返回 466、gd.189.cn 返回 412，多数省 *.10010.com 连接失败）。

## 4. 结构性发现（比名单本身更有用）

- **省级矩阵是四层，不是一层**：服务号（`省名+移动10086`，粉丝最多但不承载叙事）→
  官方资讯号（`中国移动X公司`，**这才是发布落点**）→ 垂类号（宽带管家/人力资源/政企/共青团）→
  地市号（不可枚举）。材料里"省分公众号"必须拆成四层才谈得上投放。
- **命名无统一规则**：广东"广东移动10086"、北京"中国移动北京公司"、陕西"陕西移动"、四川"中国移动四川公司"。
- **电信一省两号并行**：`省名+电信`（业务服务号）与 `中国电信+省名+公司`/`省名+电信客服`（传播落点）；
  联通为 `省名+联通` + `中国联通+省名+客服`。**政企号与品牌宣传号才是 To G 入口**
  （天津联通政企客户 `tjltzqkh`、安徽「皖美联通」`gh_01b05195a206`）。集团兜底号 `ChinaUnicom800010010`。
- **10 家里只有三家运营商有真 31 省矩阵**。华为、讯飞、卫宁、东软、创业慧康、东华、阿里健康
  均为集团号 + 行业线号，不按省设号；阿里健康区域触达走支付宝端内。它们做区域传播须借运营商省分号
  联合发声——反向印证材料"运营商护城河是省分组织力"的判断。
- **东软是 7 家里唯一有明确医疗垂类号的**：`NeusoftHIT`，To 医院投放比集团号准确。
- **三处易混**：赛迪 = 赛迪网（媒体）+ 赛迪顾问（研究）；东软集团（医疗 IT）≠ 东软医疗（影像设备）；
  中国软件网 ≠ 中国软件行业协会。合并统计会虚增覆盖数。
- **CHINC 已更名**：原"中华医院信息网络大会"→ 2025 起"数字医学与健康大会"→ 2026 称
  "数字医学大会（CHINC）"，会期由 5 月延至 7 月 3–5 日长沙。按旧名检索会漏当年征稿与议程；
  材料在讯飞段落单列的"数智医学大会"与 CHINC 同源，排期勿重复计入。

## 5. 结果与缺口

- 网址地图 60+ 入口；公众号矩阵已确认 **98 个运营商账号 / 覆盖 29 个省级行政区**，
  另有 **7 家厂商 24 个账号**（集团主号 → 业务线号 → 招聘号三层）。
- **仍空白**：西藏、青海两省三家运营商全无公开证据；重庆电信/联通、上海电信、宁夏联通、北京联通
  共 6 格留空待核。
- 探针脚本全量模式未跑完即主动中止，`candidates.json` 不存在，不得把 `probe2.json` 当作全量结果统计。

## 6. 下一步可选

1. 换运营商年报、招标公示中的联系方式口径，再攻剩余 8 格。
2. 按「To G / To 医院 / To 医生 / To 资本」四条线抽一份可执行投放清单。
3. 需要人工配合：微信搜一搜核验主体，搜索结果页对自动化不友好。
"""

CODE_SUMMARY = """# 代码学习总结：探针脚本与仓库归档规范

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

修法：改为先按卡片起始标签 `re.split(r'(?=<a href="/[a-z0-9\\-]+\\.html")', html)` 把页面切成独立块，
再在**每个块内部**分别匹配。`CARD_HREF.match(block)` 保证块首即本卡链接，
`CARD_CORP` / `CARD_H3` / `CARD_INFO` 均限定在块内，物理上杜绝跨卡串味。
微信号正则也放宽为允许中间夹 HTML 标签：`公众号ID[:：]\\s*(?:<[^>]+>\\s*)*([A-Za-z0-9_\\-]{4,40})`。

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
"""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check_no_secrets(data: bytes, where: str) -> None:
    for pattern in SECRET_PATTERNS:
        if re.search(pattern, data):
            raise ValueError(f"Possible secret in {where}: pattern {pattern!r}")


def build_tree(timestamp: str, node_count_target: int) -> dict:
    nodes = []

    def node(nid, parent, kind, text, status="completed", **extra):
        entry = {"id": nid, "parent": parent, "kind": kind, "status": status,
                 "at": timestamp, "text": text}
        entry.update(extra)
        nodes.append(entry)

    node("need", None, "需求",
         "对「医卫数字化棋盘」材料做可核实的传播 mapping：逐条标注涉及网址，补齐三家运营商内地各省公众号，"
         "并纳入华为、讯飞医疗、卫宁、东软、创业慧康、东华医为、阿里健康的公众号入口。")
    node("discipline", "need", "证据纪律",
         "不推测、不编造：查不到只写检索词与应匹配认证主体；证据分强/中/弱；"
         "投放前帐号主体必须与省分公司全称完全一致，代理商主体一律不用。详见[工作思路](DETAILS.md)。")
    node("url-map", "need", "网址清单",
         "[medical-digital-pr-url-map.html](artifacts/delivery/medical-digital-pr-url-map.html)："
         "60+ 可点击入口，按官网/政企/IR/媒体/会议分色；补入 A股 IR 三件套、港股披露易、搜狗微信、会议当年报名页等隐性路口。")
    node("url-findings", "url-map", "核实结论",
         "CHINC 已更名（2026 称数字医学大会，7/3-5 长沙，按旧名检索会漏）；"
         "三家运营商医疗品牌（翼康/智慧医疗军团/OneHealth）均无独立官网；"
         "赛迪网≠赛迪顾问、东软集团≠东软医疗、中国软件网≠中国软件行业协会。")
    node("matrix", "need", "省级公众号矩阵",
         "[medical-digital-pr-wechat-matrix.html](artifacts/delivery/medical-digital-pr-wechat-matrix.html)："
         "31 省 x 移动/电信/联通，已确认 98 个账号、覆盖 29 个省级行政区；未确认格留检索词。")
    node("matrix-layers", "matrix", "四层结构",
         "服务号（粉丝多但不承载叙事）→ 官方资讯号（真正投放落点）→ 垂类号（宽带管家/人力资源/政企/共青团）"
         "→ 地市号（不可枚举）；命名无统一规则。")
    node("matrix-breakthrough", "matrix", "取证突破",
         "第二轮改用企业信息平台「微信公众号」维度，按省分公司主体一次列全账号，账号数 42→98；"
         "省电信 189.cn 子站公告/隐私政策页可直接命中本省公众号全称。")
    node("vendors", "need", "7家厂商入口",
         "华为/讯飞医疗/卫宁/东软/创业慧康/东华医为/阿里健康共 24 个账号，"
         "按集团主号→业务线号→招聘号三层；均不按省设号，区域传播须借运营商省分号。"
         "东软 NeusoftHIT 是唯一明确医疗垂类号；阿里健康区域触达走支付宝端内。")
    node("code", "need", "代码归档",
         "[代码学习总结](CODE_SUMMARY.md) · [代码索引](CODE-INDEX.md) · [SHA256清单](SOURCE-MANIFEST.json)。"
         "唯一自编脚本为 wxnum_probe.py，全量抓取已主动中止，未产出 candidates.json。", "partial")
    node("code-probe", "code", "探针脚本",
         "[wxnum_probe.py](artifacts/code/wxnum_probe.py)：检索词模板 → 按卡片切块解析 → 认证主体白名单过滤"
         " → 详情页取微信号；1.2s/1.0s 限速、超时 20s、重试 2 次。", "completed")
    node("code-bug", "code-probe", "已修复缺陷",
         "初版用跨卡片贪婪正则，把 OPPO 广东移动通信误判进广东移动名下；改为按卡片起始标签 re.split 切块、"
         "块内分别匹配，物理隔离卡片边界。微信号正则放宽为允许中间夹 HTML 标签。", "completed")
    node("code-abandon", "code", "中止原因",
         "[probe2.json](artifacts/evidence/probe2.json) 显示广东只召回一机游/法律服务/共青团等边缘号，"
         "主号缺失，四川电信与联通 0 命中——是收录源结构性偏差而非解析故障，继续跑只产噪声，故停止全量模式。", "partial")
    node("code-repo-tool", "code", "仓库规范学习",
         "tree.json 为权威源、tree.md 由 scripts/idea_tree_writer.py 渲染（首节点必须为 need、状态枚举固定）；"
         "完整归档含源码副本、SHA256 清单、脱敏扫描与离线校验；归档状态与事实覆盖状态分开记录。", "completed")
    node("delivery", "need", "交付物位置",
         "网址地图原件在 docs/；矩阵页原件已移至 E:/CAICTBigData/移动项目沟通/政采_公共资源网_全国与地方_1030/，"
         "本树 artifacts/delivery/ 保存两份独立副本防止散落。")
    node("gaps", "need", "仍待核",
         "西藏、青海两省三家运营商无公开证据；重庆电信/联通、上海电信、宁夏联通、北京联通共 6 格留空，"
         "保留检索词与应匹配主体，未填推测值。", "partial")
    node("next", "gaps", "下一步",
         "① 换运营商年报/招标公示联系方式口径再攻剩余 8 格；② 按 To G / To 医院 / To 医生 / To 资本 抽投放清单；"
         "③ 微信搜一搜核验主体需人工配合（搜索结果页对自动化不友好）。", "awaiting_jane")
    node("archive-check", "need", "归档验收",
         "[归档校验](ARCHIVE-VERIFICATION.json)：树 JSON/Markdown 一致、父子节点有效、源码哈希比对、"
         "内部链接存在、无敏感模式；上一轮手写稿另存 artifacts/docs/ 未覆盖。归档交付 completed，事实覆盖 partial。")

    return {
        "id": TREE_ID,
        "created_at": timestamp,
        "updated_at": timestamp,
        "status": "partial",
        "status_note": "归档交付已完成；事实覆盖仍为 partial：8 格省级公众号待核，探针全量抓取已主动中止。",
        "requirement": "标注材料涉及的全部网页入口，补齐三家运营商内地各省公众号，并纳入 7 家厂商公众号入口。",
        "theme": "医卫数字化传播 mapping：网址清单 + 省级公众号矩阵 + 厂商入口",
        "tool": "公开检索核实 + wxnum.cn 探针脚本 + 企业信息平台主体维度 + 仓库 idea_tree_writer 渲染",
        "delivery": "[工作思路](DETAILS.md)、[代码学习总结](CODE_SUMMARY.md)、[代码索引](CODE-INDEX.md)、[SHA256清单](SOURCE-MANIFEST.json)、[归档校验](ARCHIVE-VERIFICATION.json)",
        "result": {
            "archive_status": "completed",
            "coverage_status": "partial",
            "url_entries": 60,
            "operator_accounts_confirmed": 98,
            "provinces_covered": 29,
            "vendor_accounts_confirmed": 24,
            "vendor_firms": 7,
            "unverified_cells": 8,
            "wxnum_full_run": False,
            "wxnum_candidates_file_exists": False,
            "facts_verified": False,
            "github_pushed": False,
            "node_count": len(nodes),
        },
        "nodes": nodes,
    }


def copy_sources(timestamp: str) -> list:
    records = []
    for source, relative, category, purpose in SOURCES:
        if not source.is_file():
            raise FileNotFoundError(f"Archive source missing: {source}")
        original = source.read_bytes()
        check_no_secrets(original, str(source))
        target = DEST / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(original)
        records.append({
            "path": relative,
            "category": category,
            "purpose": purpose,
            "source_live": str(source),
            "bytes": len(original),
            "sha256": sha(original),
            "source_sha256": sha(original),
            "transformation": None,
        })
    return records


def write_docs(records: list) -> None:
    (DEST / "DETAILS.md").write_text(DETAILS, encoding="utf-8")
    (DEST / "CODE_SUMMARY.md").write_text(CODE_SUMMARY, encoding="utf-8")

    lines = [
        "# 代码与交付物索引", "",
        "源目录：`E:/CAICTBigData/coding`。下列链接均指向本树独立快照，原件未改动。", "",
        "[工作思路](DETAILS.md) · [代码学习总结](CODE_SUMMARY.md) · [想法树](tree.md) · [SHA256清单](SOURCE-MANIFEST.json)", "",
        "| 文件 | 分类 | 用途 |", "| --- | --- | --- |",
    ]
    for rec in records:
        lines.append(f"| [{Path(rec['path']).name}]({rec['path']}) | {rec['category']} | {rec['purpose']} |")
    lines += [
        "", "## 范围说明", "",
        "归档内容为本任务链自编脚本、试跑证据、两份 HTML 交付物副本，以及仓库树渲染工具与本归档脚本。",
        "不含真实密钥、Cookie、运行环境或第三方框架库。探针脚本全量模式未跑完，",
        "`artifacts/evidence/probe2.json` 只是两省试跑结果，不能当作省级覆盖率统计依据。", "",
    ]
    (DEST / "CODE-INDEX.md").write_text("\n".join(lines), encoding="utf-8")


REPORT_NAME = "ARCHIVE-VERIFICATION.json"


def verify_archive(allow_missing_report: bool = False) -> dict:
    checks = {}

    tree = read_tree(DEST / "tree.json")
    validate(tree)
    checks["tree_valid"] = True
    checks["first_node_need"] = tree["nodes"][0]["id"] == "need"

    rendered = render_markdown(tree)
    actual = (DEST / "tree.md").read_text(encoding="utf-8")
    checks["tree_md_matches_render"] = rendered == actual
    if not checks["tree_md_matches_render"]:
        raise AssertionError("tree.md drifted from tree.json")

    manifest = json.loads((DEST / "SOURCE-MANIFEST.json").read_text(encoding="utf-8"))
    hash_ok = True
    for rec in manifest["files"]:
        target = DEST / rec["path"]
        if not target.is_file() or sha(target.read_bytes()) != rec["sha256"]:
            hash_ok = False
            break
    checks["manifest_hashes_match"] = hash_ok
    checks["manifest_file_count"] = len(manifest["files"])

    link_re = re.compile(r"\]\(([^)]+)\)")
    missing = []
    for md in DEST.glob("*.md"):
        for link in link_re.findall(md.read_text(encoding="utf-8")):
            link = link.split("#")[0]
            if not link or link.startswith(("http://", "https://")):
                continue
            if allow_missing_report and link == REPORT_NAME:
                continue  # the integrity report is written only after this check runs
            if not (DEST / link).exists():
                missing.append(f"{md.name}: {link}")
    checks["internal_links_exist"] = not missing
    checks["missing_links"] = missing

    secret_hits = []
    for path in DEST.rglob("*"):
        if path.is_file() and path.suffix != ".zip":
            data = path.read_bytes()
            if any(re.search(p, data) for p in SECRET_PATTERNS):
                secret_hits.append(str(path.relative_to(DEST)))
    checks["no_secret_patterns"] = not secret_hits
    checks["secret_hits"] = secret_hits

    checks["node_count"] = len(tree["nodes"])
    # explicit roll-up: booleans must all be True, missing_links/secret_hits must be empty
    bool_keys = ["tree_valid", "first_node_need", "tree_md_matches_render",
                 "manifest_hashes_match", "internal_links_exist", "no_secret_patterns"]
    ok = all(checks[k] for k in bool_keys) and not missing and not secret_hits
    checks["status"] = "completed" if ok else "failed"
    report = {"tree_id": TREE_ID, "verified_at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
              "checks": checks, "archive_status": "completed" if ok else "failed",
              "coverage_status": "partial",
              "note": "离线完整性校验，不重新联网采集；归档完整不等于事实已核验完。"}
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verify", action="store_true", help="Only re-run offline verification")
    args = parser.parse_args(argv)

    if args.verify:
        print(json.dumps(verify_archive(), ensure_ascii=False, indent=2))
        return 0

    timestamp = datetime.now().astimezone().replace(microsecond=0).isoformat()
    DEST.mkdir(parents=True, exist_ok=True)

    # Preserve the previous hand-written draft instead of silently overwriting it.
    handwritten = DEST / "tree.md"
    if handwritten.is_file():
        old = handwritten.read_text(encoding="utf-8")
        if not old.startswith("# 想法树 "):
            backup = DEST / "artifacts/docs/tree-handwritten-20261102.md"
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_text(old, encoding="utf-8")

    records = copy_sources(timestamp)
    dump(DEST / "SOURCE-MANIFEST.json", {
        "tree_id": TREE_ID,
        "created_at": timestamp,
        "scope": "本任务链自编探针脚本、试跑证据、两份 HTML 交付物副本、仓库树渲染工具与归档脚本自身；"
                 "不是完整运行环境或第三方库镜像。",
        "excluded": ["真实密钥/Cookie", "运行环境与依赖库", "未生成的 candidates.json（全量抓取已中止）"],
        "files": records,
    })

    tree = build_tree(timestamp, len(records))
    dump(DEST / "tree.json", tree)
    rendered = render_tree(DEST / "tree.json")
    write_docs(records)

    report = verify_archive(allow_missing_report=True)
    dump(DEST / REPORT_NAME, report)
    report = verify_archive()  # full re-check now that the report exists
    dump(DEST / REPORT_NAME, report)
    if report["archive_status"] != "completed":
        print(json.dumps({"status": "failed", "report": report}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"status": "completed", "tree": rendered,
                      "source_files": len(records), "verification": report["checks"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
