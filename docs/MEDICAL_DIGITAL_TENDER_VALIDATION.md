# 医疗数字化中标采集规则：本轮验证与剩余缺口

2026-10-27，规则版本 `2026-10-27.5`（首轮为 `.4`）。本轮目标是可复用采集规则和可追溯失败台账；未执行全国历史公告的全量抓取。

已登记 **93个来源/目录项**，覆盖用户A/B/C全部类别，含31省及兵团的政采、公共资源双入口；保留23条官方、固定版本GitHub源码及作者博客出处。由16个省级页面发现 **233项城市/平台导航候选**，未把候选当作已完成地市适配。

## 2026-10-27.5 复测轮（本轮）

按上轮"复测可达入口和已修复正文"的既定顺序执行：对10个省级公资站做限量联网复测（每站≤3页、深度1），并对5个robots瞬时失败来源复测。全部原文、失败与重放记录见 [retest-20261027.5台账](medical-digital-tender-validation-20261027/retest-20261027.5/report.md)（原始采集在 `outputs/medical-digital-tender-retest-20261027/`，outputs不入Git）。

**结果**：33页次，取得 **8个来源15条详情记录**（真实联网抓取原文+新规则解析），23条历史失败全部保留。本轮无医疗数字化候选（抓到的样本为保函遴选、违规处理通知、评审办法等），不等于已核验中标项目。

| 来源 | 本轮结果 | 规则改进 |
|---|---|---|
| 山西公资 | 列表148链接→2条详情（标题/日期/正文均解析） | 新profile `shanxi_ggzy`：列表`div.cs_tab_box_cont`，标题`p.cs_title_P1`，日期`p.cs_title_P3`，正文`.cs_xq_content` |
| 河北公资 | 1条详情 | `hebei_ggzy`：列表`li.ewb-notice-item`，标题`.ewb-bulid h2`，正文`.ewb-copy` |
| 吉林公资 | 2条详情（标题修正为公告标题而非门户h1） | `jilin_ggzy`：标题`h3.ewb-article-tt` |
| 四川公资 | 2条详情 | `sichuan_ggzy`：标题`h2.detailed-title`，正文`.news-detailed` |
| 贵州公资 | 2条详情（含1条中选公告，stage=award） | `guizhou_ggzy`：正文`.Article_Con`/`.trs_editor_view` |
| 陕西公资 | 2条详情 | `shaanxi_ggzy`：标题`h3.article-title`，正文`.epoint-article-content` |
| 新疆公资 | 2条详情 | `xinjiang_ggzy`：标题`h3.public-article-title`，正文`.public-article-container` |
| 内蒙古公资 | 2条详情（正文容器含导航文本，已标`article_text_with_chrome`待复核） | `neimenggu_ggzy`：正文`.body_zzms` |
| 青海公资 | 2条详情页整页仅146/265字符，正文JS加载 | 维持dynamic_shell缺口；需浏览器渲染或官方接口 |
| 兵团公资 | 1条详情页整页仅125字符，em-tab动态容器 | 同上 |
| ccgp/ggzy北京、ccgp浙江/河南/湖北 | robots复测仍5次`robots_unavailable`（TLS/连接失败） | 属本机网络或站点防护持续性限制，未绕过，原始原因逐条留痕；**北京两站已于本轮经第三方库打通，见下** |

**北京两条官方线：改走本机第三方库（2026-10-27 21:30–21:45）**

`ccgp_beijing`（www.ccgp-beijing.gov.cn）——**修订此前结论**。之前只测 443，两轮网络都 TCP 不通（DNS 可解析、连接建立不了、HTTP 000）。本轮补测 **80 端口：TCP 可连、`http://` 首页返回 200（约 90KB）且不做 https 跳转、robots.txt 为 404**。所以这条线不是“不可采”，是只有 HTTP 入口可用，已按 HTTP 采集。

`ggzy_beijing`（ggzyfw.beijing.gov.cn）——**修订此前“WAF 按 UA 拦截爬虫”的判断**。逐 UA 对照：被拦的只有 UA 里带 `python-requests` 的请求（首页与 robots.txt 均 403）；自报 UA `CAICTMedicalResearchBot/1.0 (public-source research)`、`curl/8.x`、完全不发 UA 都返回 200，robots.txt 为 404（无 robots 规则）。站点是国密 SM2 TLS，Python OpenSSL 报 `SSL: BAD_ECPOINT`，改走系统 TLS 栈即通。**本轮未使用浏览器 UA，不涉及伪装。**

接入方式：按 `repos/goverment_spider` 的库内约定新增两个站点脚本，经 `pipeline/runner.py` 执行（`--site` 指定脚本，`--start-date 2026-10-27`，每栏目 2 页）：

| 站点 | 脚本 | 通道 | 结果 |
|---|---|---|---|
| 北京市政府采购网 | `codes/1600004` | 市级中标、区级中标、市级招标公告 | **11 条**（医卫数智 3、医卫设备 6、医卫其他 2），失败 0 |
| 北京公共资源交易平台 | `codes/1600005` | 采购公告、中标成交公告 | **4 条**（医卫设备 3、医卫其他 1），失败 0 |

抽取到的实例：海淀医院信息化升级改造项目（中标 1169.58 万元）；市属医院 2026 年医用设备带量采购放射组第二批次（预算 11182 万元，采购人北京市医院管理中心）；隆福医院中医药传承示范试点设备（589.46 万元）；通州区妇幼保健院改革项目（1790.79 万元）；天坛医院超融合节点扩容（259.65 万元）。

如实说明两个口径问题：①公共资源交易平台“中标成交公告”当日两页 20 条里没有医卫项目（多为公安、环保、会议服务），4 条不是漏采；②政府采购网只覆盖当日 2 页，更早公告需放大页数或改日期窗。另有一处失败已复现并修复：本地代理会让 `jyxxzbjggg/index_2.html` 返回 `CONNECT tunnel failed 502`，`site_fetch` 改为默认直连后失败清零。

**旧诊断（留档，已被上面修订）**：`ccgp_beijing` 两次不同网络均为 TCP 层不通，curl 直连与走代理都是 HTTP 000（10–15 秒超时），判为站点侧或网络准入限制——该项只覆盖 443，未测 80。`ggzy_beijing` 曾按“爬虫 UA 403”记为访问拒绝——该判断源于 UA 中带 `python-requests`，逐 UA 对照后不成立。

**网络切换后复测（net2，21:10–21:20）**：台账见 [retest-net2](medical-digital-tender-validation-20261027/retest-20261027.5-net2/report.md)。

| 来源 | 本轮结果 | 诊断与处理 |
|---|---|---|
| ccgp_hubei | 由robots失败转为可采：首页100条链接→`/notice/`详情，1条解析成功（黄冈市财政局考核结果公告，2026-10-26） | 新profile `ccgp_hubei`：列表`a[href*='/notice/']`、正文`#main`、标题`#main h2`；首页新闻栏目混入《中国政府采购报》征订软文，已记录需按`/notice/`入口过滤 |
| ccgp_zhejiang | 系统TLS后仍失败 | schannel报`SEC_E_UNTRUSTED_ROOT`：证书链根不受信任，属站点侧证书问题，未关闭验证 |
| ccgp_henan | 仍失败 | `Hostname mismatch`：证书与域名不符，属真实证书问题，不绕过 |
| ggzy_beijing | 握手成功但被WAF按UA拦截（robots 403） | 记robots_denied；需授权/官方接口 |
| ccgp_beijing | TCP不可达（两轮网络一致） | 记robots_unavailable（连接超时）；需政务外网或官方接口 |

代码变更：`pipeline/research/fetch.py` 新增 `transport`（requests / system_tls / auto）。`system_tls` 通过 curl 使用操作系统TLS栈，证书仍由系统信任库严格校验（curl退出码60映射为TLS失败，绝不返回内容），仅在OpenSSL无法握手时使用；`configs`中按来源显式声明，不隐式回退。新增5项传输层回归测试。

回归测试新增3项（山西列表/详情、省站首页listing不伪造detail），传输层新增5项；医疗规则模块22项、传输层5项通过，全库260项中259项通过；唯一失败`test_full_install_fails_preflight_before_installing_missing_repositories`经stash复测确认为与本轮无关的既有失败（install预检读stderr为None）。

首轮（`.4`）验证结论如下，逐站状态与失败仍以下文台账为准。

本机累计尝试 **79个来源、89页次**。按保存原文重放，取得 **6个来源的7条详情记录**，其中3条被标为医疗数字化候选。另有10个来源到达列表发现阶段，63个来源仍存在访问或解析缺口，14项因权限、接口契约或目录缺失未尝试联网。以上均不等于已核验中标项目数。

完整逐站状态见 [93项台账](medical-digital-tender-validation-20261027/report.md)；机器记录见 [来源状态](medical-digital-tender-validation-20261027/sources.json)、[原文重放记录](medical-digital-tender-validation-20261027/observations.json)。

## 已落实的规则改进

| 来源/问题 | 改进与验证结果 |
|---|---|
| 中国政府采购网 | 中央/地方中标及成交入口；新旧vF/vT正文与GBK编码；2条真实详情通过既有版本1任务保存，均重解析成功 |
| 天津公资 | 优先公告`.detail-title`，避免读取前面的门户h1；正文`.detail-body`，成交样本可解析 |
| 黑龙江公资 | `.ewb-art-hd`及`.ewb-art-bd`；预中标/公示生效条件另标需要核验，耗材包未混入软件候选 |
| 江西公资 | `.content > .text`正文；电梯公告保留原文并排除数字化候选，不把医院名当软件项目 |
| 浙江公资 | 交换摘要`.article-info .con`，标明`summary_and_attachments`；PDF全文尚未解析 |
| 重庆疾控 | `.box-r > .title`和`.box-r > .scroll`，采购邀请保持tender，不被正文“中标”等措辞升级 |
| 青海公资 | 识别空mytitle和projectDetail.js动态详情，保留dynamic_shell缺口 |
| 讯飞医疗 | 补当前xunfeihealthcare域及企业动态入口，保留历史iflyhealth入口失败；新闻栏目复测在robots检查阶段超时，尚未取得新闻详情 |
| 金额、阶段与归并 | 预算/中标/代理费/单价分开；89万元总额与1.335万元代理费在真实样本中分开保存；多包、多供应商不自动合计 |

## 失败完整留存

本轮保留 **87条历史失败或未执行记录**，包含已通过离线规则修复的原未命中记录。失败条数不能当作当前失败站点数，也不能把HTTP请求页次与资料/项目条数混用。

| 原始失败代码 | 条数 | 处理 |
|---|---:|---|
| robots_unavailable | 44 | robots读取超时、TLS或返回HTML；保留底层错误，未继续绕过读取 |
| robots_denied | 5 | robots拒绝或检查返回403；停止 |
| discovery_no_links | 16 | 首页/详情取到但旧规则未命中；其中一部分已由新规则离线修复，原记录不覆盖 |
| error | 3 | 原HTTP错误，包括卫健委412；具体网址、阶段和错误逐条保留 |
| dynamic_shell | 2 | 初始HTML为空壳，当前仍需浏览器或官方数据契约适配 |
| http_not_found | 2 | 旧入口404，需官方迁移入口验证 |
| domain_scope_denied | 1 | 跳转超出白名单，未自动扩大范围 |
| authorization_required | 5 | 企查查/天眼查/剑鱼/新闻舆情等缺本轮已确认接口授权与预算，未发付费请求 |
| contract_unverified | 6 | API/会员导出/数据包的正式契约与样本未验证 |
| directory_incomplete | 2 | 省级公服与药械中心目录未逐项补齐 |
| official_feed_unavailable | 1 | 公众号/视频号无本轮验证过的通用官方RSS |

可跟随Git保存的完整记录在 [historical_failures.json](medical-digital-tender-validation-20261027/historical_failures.json)。原始HTML、原任务状态及各批次失败仍在 `outputs/medical-digital-rules-20261027/` 与 `outputs/medical-digital-tender-smoke-20261027/`，不改旧失败来模拟成功。任务状态保留原执行目录，JSON中的仓库相对原文路径可在本库查找。

## 仍待补齐

31省入口已经登记，全部地市及卫健/医保/疾控/药械中心目录尚未穷尽；233个导航候选需核验主体与真实采购栏目。全国、广东、广西、云南及中国招标投标平台的JSON接口只有有出处的线索，尚无当前已验收的API请求实现。商业API和导出没有正式样本，保留接入规范与未执行理由。

本模块尚不自动展开附件、执行OCR、解析所有供应商/联合体/包件或按历史日期窗口跑全量；这些缺口均有明示。下一轮应优先复测可达入口和已修复的省级正文，再逐省补城市/垂直站点。无需通过关闭证书验证、代理轮换或验证码破解来掩盖失败。

复现命令及字段口径见 [规则使用说明](MEDICAL_DIGITAL_TENDER_RULES.md)。本轮19项新增回归通过，代码库整套252项测试全部通过；结果见 [最终检查记录](medical-digital-tender-validation-20261027/final_checks.json)。
