# 北京两条官方线经本机第三方库采集：结果与证据

采集时间 2026-10-27 21:35–21:45；规则版本 `2026-10-27.6`；任务树 `20261027-213520`（`tool=goverment_spider`）。

## 一、两条线的真实状态（修订此前结论）

| 入口 | 此前结论 | 本轮实测 | 结论 |
|---|---|---|---|
| www.ccgp-beijing.gov.cn | TCP 层不通，判为站点侧或网络准入限制 | 443 确实建立不了连接；**80 端口 TCP 可连、`http://` 首页 200（约 90KB）、不跳转 https、robots.txt 404** | 只测了 443 才得出“不可采”，实为**仅 HTTP 入口可用** |
| ggzyfw.beijing.gov.cn | WAF 按 UA 拦截爬虫（爬虫 UA 403） | 被拦的只有 UA 含 `python-requests` 的请求；自报 UA `CAICTMedicalResearchBot/1.0 (public-source research)`、`curl/8.4.0`、不发 UA 均 200；robots.txt 404 | “WAF 拦爬虫”不成立；国密 SM2 TLS 需系统 TLS 栈，与 UA 无关 |

UA 逐项对照（首页 / robots.txt 状态码）：

| UA | 首页 | robots.txt |
|---|---|---|
| `curl/8.4.0` | 200 | 404 |
| `python-requests/2.31.0` | 403 | 403 |
| `CAICTMedicalResearchBot/1.0 (public-source research)` | 200 | 404 |
| `Mozilla/5.0 … Chrome/131.0` | 200 | 404 |
| 不发 UA 头 | 200 | 404 |

## 二、接入方式

按库内约定新增两个站点脚本，由 `pipeline/runner.py` 的 `run_task` 执行（`--site` 指定脚本）：

```powershell
& $py -B -m pipeline run --tree-id 20261027-213520 --theme "…" --delivery json `
    --site 北京市政府采购网 --start-date 2026-10-27
& $py -B -m pipeline run --tree-id 20261027-213520 --theme "…" --delivery json `
    --site 北京公共资源交易平台 --start-date 2026-10-27
```

共用 `site_fetch.py`：先 requests，TLS/连接失败才换系统 TLS 栈的 curl；`curl=60` 按失败抛出、不返回内容；默认直连（本机注入的代理曾把 `jyxxzbjggg/index_2.html` 拦成 `CONNECT tunnel failed 502`，改为直连后失败清零），需要代理时设 `SITE_FETCH_USE_PROXY=1`。

## 三、本轮结果

| 站点 | 通道 | 记录 | 类型分布 | 失败 |
|---|---|---|---|---|
| 北京市政府采购网 | 市级中标、区级中标、市级招标公告（各 2 页） | 11 | 医卫数智 3、医卫设备 6、医卫其他 2 | 0 |
| 北京公共资源交易平台 | 采购公告、中标成交公告（各 2 页） | 4 | 医卫设备 3、医卫其他 1 | 0 |

样例（取自同名 `.json` 旁证，金额为原文提及，未做汇总）：

| 站点 | 标题 | 采购人 | 中标/预算 | 金额 |
|---|---|---|---|---|
| 政采网 | 海淀医院信息化升级改造项目中标公告 | — | 北京鑫博腾飞科技有限公司 | 1169.582022 万元 |
| 政采网 | 市属医院2026年医用设备带量采购放射组第二批次（国产部分）第1–4包 | — | — | 11182 万元（预算） |
| 政采网 | 2026年北京天坛医院超融合节点扩容 | — | — | 259.65 万元 |
| 公资平台 | 市属医院2026年医用设备带量采购放射组第二批次第1–4包公开招标公告 | 北京市医院管理中心(本级) | — | 11182 万元 |
| 公资平台 | 北京市通州区妇幼保健院公立医院改革和高质量发展项目 | 北京市通州区妇幼保健院 | — | 1790.79 万元 |
| 公资平台 | 隆福医院中央财政支持中医药事业传承发展示范试点设备 | 北京市隆福医院 | — | 589.46 万元 |

## 四、口径与缺口（如实记录）

1. 公资平台“中标成交公告”当日两页 20 条（多为公安、环保、会议服务、政务外网改造）无医卫项目，**4 条不是漏采**。
2. 政采网只覆盖当日 2 页；更早公告需放大页数或改日期窗（脚本支持 `--max_pages`，runner 暂不透传）。
3. 政采网“市级中标公告”多为一事一包的中标结果，采购人字段在来源页并不总出现，缺项留空不推断。
4. 公资平台采购公告是招标阶段，没有中标供应商；中标成交公告才带供应商与金额。
5. 未做跨站同项目去重（如“市属医院医用设备带量采购”两站同时出现），下一步按项目编号归并。

## 五、文件清单

- `北京市政府采购网-医疗公告.json`、`北京市公共资源交易平台-医疗公告.json`：逐条记录与失败明细
- `tree.json` / `tree.md`：任务树快照（需求、选型、5 次执行记录、结果、纠错、代码沉淀、验证、缺口、后续方向）
- 脚本正本：`scripts/thirdparty_goverment_spider/`（`repos/` 被 gitignore，运行时再拷入）
- 规则与文档：`configs/medical_digital_tender_rules.json`、`docs/MEDICAL_DIGITAL_TENDER_RULES.md`、`docs/MEDICAL_DIGITAL_TENDER_VALIDATION.md`
- 离线回归：`tests/test_beijing_official_scripts.py`（11 项，不联网）、`tests/test_idea_tree_ids.py`（5 项，树节点 id 唯一）

## 六、测试

- `tests/test_beijing_official_scripts.py`：11 项通过（列表解析、分页地址、标题去项目编号、医卫数智/设备分类、误判排除、详情字段抽取）
- `tests/test_idea_tree_ids.py`：5 项通过（同 id 追加自动加序号、upsert 改写不重复、渲染不重复展开）
- 全库：276 项，275 通过；唯一失败 `test_full_install_fails_preflight_before_installing_missing_repositories` 为既有问题（install 预检读 stderr 为 None），与本轮无关

## 七、想法树（20261027-213520）

- 本轮成果已上传到该树，25 个节点，父子关系逐条校验可解析，状态 `completed`。
- 上传时修掉一处写入缺陷：`cmd_run` 原用固定 id 写 `theme`/`delivery`/`run`，同一棵树连跑多次会产生同 id 节点，`tree.md` 把 5 次执行渲染成 125 条重复项。现改为 `upsert` 改写主题/交付、`run-N` 递增 id，历史重复节点已按序重编号并折叠。
- 顶层事实字段同步：`rules_version=2026-10-27.6`、`result`（两站记录数/页数/测试通过数）、`artifacts`（9 项可追溯路径）、`provenance`（说明节点来自真实执行记录，纠错节点保留被推翻的旧判断）。
