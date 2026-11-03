# 医疗数字化中标情报采集规则

本轮规则版本 `2026-10-27.5`。规则库覆盖用户给出的 A/B/C 类别，并登记 31 省及兵团的政采、公共资源官方导航入口。入口登记、首页可达、列表发现、详情解析、事实核验分别计数。逐站实际结果见 [验证说明](MEDICAL_DIGITAL_TENDER_VALIDATION.md)，未取得的入口/权限也在失败台账中。

`2026-10-27.5` 相对 `.4` 的变化：山西公资改用专属 profile（`shanxi_ggzy`）；河北、吉林、四川、贵州、陕西、新疆、内蒙古七省改用真实详情样本推导的专属 profile（hebei/jilin/sichuan/guizhou/shaanxi/xinjiang/neimenggu_ggzy），列表→详情在本轮联网复测中打通；青海新闻详情与兵团详情确认为动态渲染缺口。

## 文件和使用

| 文件 | 用途 |
|---|---|
| `configs/medical_digital_tender_rules.json` | 来源矩阵、选择器、接口线索、官方/GitHub/博客出处、地区目录、限制与补齐动作 |
| `pipeline/research/tenders.py` | 规则校验、离线计划、有限采集、离线重解析、转换现有research配置 |
| `pipeline/research/tender_audit.py` | 重放保存原文，汇总逐站状态，保留全部历史失败 |
| `configs/medical_digital_tender_city_candidates.json` | 从省站官方导航发现的233项城市/平台候选，尚未逐项访问验收 |
| `configs/medical_digital_tender_public_sources.json` | 5个重点公开来源，兼容既有research/discover/task配置 |
| `configs/medical_digital_tender_smoke_sources.json` | 本轮2条真实详情样本，供复现，不代表未来固定数据 |
| `tasks/medical_digital_tender_smoke_20261027.json` | 已执行dry-run及正式采集的版本1任务 |
| `tests/test_medical_tender_rules.py` | 编码、金额角色、多包、阶段、访问边界与失败留存回归 |

在代码库根目录运行。使用现有本机Python环境，不安装新依赖、不下载浏览器：

```powershell
$py = (Get-Content .runtime.json -Raw | ConvertFrom-Json).python

# 离线计划，不访问网络；输出文件不能已存在。
& $py -B -m pipeline.research.tenders plan --output outputs/my-tender-plan.json

# 必须显式选择来源；每来源最多3页，优先走真实详情。
& $py -B -m pipeline.research.tenders collect --source ccgp --output outputs/my-ccgp-smoke --allow-network --max-pages 3 --max-depth 1

# 对已核实且在白名单内的详情定向取证。
& $py -B -m pipeline.research.tenders collect --source ccgp --seed-url 'https://www.ccgp.gov.cn/已核实的详情路径.htm' --output outputs/my-known-notice --allow-network --max-pages 1 --max-depth 0

# 从保存的HTML重解析，无网络、无DNS。
& $py -B -m pipeline.research.tenders parse --source ccgp --input-file outputs/某次原文.html --url 'https://www.ccgp.gov.cn/原始详情.htm' --output outputs/my-parsed-notice.json

# 接回既有任务体系；新批次更换task_id与输出根目录。
.\run-local.ps1 task --spec tasks/medical_digital_tender_smoke_20261027.json --dry-run --json
.\run-local.ps1 task --spec tasks/medical_digital_tender_smoke_20261027.json --json
```

`collect`只执行公开HTML模式。选中商业API、会员导出或待建目录时，写入 `attempted=false` 及具体原因，不发计费请求。返回码3代表partial；有失败或页数预算余项不能报告为全量成功。每次新目录，逐页检查点保存；中断保留失败记录，本模块不自动恢复旧目录。既有task/resume机制保持原有行为。

传输层：来源可声明 `"transport": "system_tls"`，经 curl 使用操作系统TLS栈访问国密/SM2 或证书链不全的站点。证书仍由系统信任库严格校验，校验失败即记TLS错误且不返回内容；不提供任何关闭验证的开关。`auto` 仅在OpenSSL报BAD_ECPOINT等不兼容错误时改用系统TLS。默认 `requests`。

离线审计可复现本轮逐站报告；输出换成一个新目录：

```powershell
& $py -B -m pipeline.research.tender_audit --input-dir outputs/medical-digital-rules-20261027 --collection outputs/medical-digital-tender-smoke-20261027/collection/attempt-001 --output-dir outputs/my-tender-audit
```

## A类：官方底座

中国政府采购网使用中央/地方的中标和成交栏目；详情兼容 `.vF_detail_content` 与 `.vT_detail_content`。检索接口 `bxsearch` 的日期、页码和公告类型在配置中作为可复核线索，未自动遍历。中标8、成交9、竞争性磋商7，不能把磋商枚举误作中标。财办库〔2024〕30号的要求从2024-04-01开始，仍需对地方栏目抽样核对完整性。[财政部原始文件](https://www.mof.gov.cn/gkml/caizhengwengao/wg2024/wg202403/202407/P020240710665612076807.pdf)

地方与中央之间的交换接口要正式申请，不能当公众下载接口。当前程序使用公开网页。[接口通知](https://www.ccgp.gov.cn/zcfg/mof/202403/t20240306_21605100.htm)

全国公共资源与各省平台同时检查政府采购、工程建设的结果、合同、更正。医院建设总包中包含信息化，不代表合同金额全部属于软件。全国旧 `dealList.jsp` 以及广东、广西、云南JSON入口保留为 `api_hints`；这些请求尚未完成当前契约验证，程序不会执行它们。上游水利分类不能直接继承为医疗检索分类。

省级公服平台、地市平台、卫健/医保/疾控、药械中心应逐站登记主体、栏目、日期窗、包号和附件。`province_directories`保留31省缺口；同一省级网站可以承载多个市级栏目，不能只按域名计地市数量。市级候选来自已保存的省站官方导航，未核验项不自动进入访问白名单。

### 北京两条官方线：改走本机第三方库

北京两条官方入口不经过 `pipeline.research.tenders`，而是接入代码库自带的第三方库 `repos/goverment_spider`（由 `pipeline/runner.py` 的 `run_task` 管理：`--site` 执行指定站点脚本，`--all-sites` 才全量）。该库约定：`codes/*.py` 每站一个脚本，输出 5 列 TSV（部门名称/类型/标题/日期/链接）到 `files/<年月>/<日期>/<区域>/`，再由 `start_project.py` 汇总 Excel。

本轮新增两个站点脚本：

| 脚本 | 入口 | 实测结论 |
|---|---|---|
| `codes/1600004.北京市政府采购网-医疗中标.py` | `http://www.ccgp-beijing.gov.cn`：市级中标、区级中标、市级招标公告，`index_N.htm` 翻页 | 443 端口在两条网络下都建立不了 TCP 连接；**80 端口正常返回 200 且不跳转 https**，故按 HTTP 入口采集 |
| `codes/1600005.北京公共资源交易平台-医疗中标.py` | `https://ggzyfw.beijing.gov.cn`：采购公告 `jyxxcggg`、中标成交公告 `jyxxzbjggg`，`index_N.html` 翻页 | 国密 SM2 TLS，requests 报 `SSL: BAD_ECPOINT`；取页走系统 TLS 通道，证书仍然校验 |

共用的 `site_fetch.py` 只做三件事：先 requests，TLS 或连接失败才换系统 TLS 栈的 curl；`curl=60`（证书不可信）按失败抛出、不返回内容；默认直连（本机注入的代理会让部分政务站返回 502，需要代理时设 `SITE_FETCH_USE_PROXY=1`）。UA 统一自报 `CAICTMedicalResearchBot`，不伪装浏览器。

筛选口径与主流水线一致：标题先命中医疗卫生机构词，再用数字化/设备词打 `医卫数智`、`医卫设备`、`医卫其他` 标签；`基层/健康/养老` 属弱信号，标题同时出现 `公安/保安/物业/街道` 等词即排除。本库自带的 `key_words.txt` 是产业政策口径，脚本不引用它，避免把“设备更新/以旧换新”当招采结果。

5 列 TSV 只保留部门/类型/标题/日期/链接，因此每个脚本同时写一份同名 `.json` 旁证（项目编号、采购人、中标供应商、金额、失败明细）；金额只记录带单位的原文提及，缺项留空。

## B类：商业及运营商

企查查官方招投标接口文档指出最近2年、最多2000条；不能声称能无条件回溯更长历史。剑鱼有官方API/SDK，仍需实际授权与预算。天眼查的工商、招投标和舆情是不同能力，需逐项核对权限。[企查查文档](https://openapi.qcc.com/dataApi/958)、[剑鱼服务](https://www.jianyu360.cn/front/dataMarket/dataInterface)

爱企查、标找找、ICT标局、天天标讯、千里马、乙方宝的接口/导出契约未取得，不编造API地址，不把会员页面当授权批采。当前仅沉淀合法导出接入规范，尚无商业数据导入器或已验证付费调用。

移动使用 `b2b.10086.cn`，电信使用 `caigou.chinatelecom.com.cn`，联通登记新 `cupb.cn` 门户；旧详情URL可能只返回门户或迁移页，必须核对公告标题、编号、发布日期。只采公开公告；登录、验证码、拒绝和限流均停止。运营商中标、集成分包和医院上游项目分别保留证据，不按相近集团名称自动归并。

## C类：厂商和数据包

讯飞医疗保留历史域，补当前 `xunfeihealthcare.com` 企业动态入口。腾讯云与支付宝入口只提供补链发现，产品/解决方案页不能当采购结果。公众号/视频号没有本轮验证过的通用官方RSS；搜狗仅作为发现途径。厂商陈述标为source_claim，需回到采购人或官方结果公告。

新闻舆情与院端招采数据包需保存供数方、授权范围、导出时间、原始字段、文件哈希、原公告URL。没有原文链的记录不能自动视为已核验；同稿转载也不是多条独立证据。

## 字段与质量控制

- 公告阶段依据标题分为招标、意向、候选人、结果、合同、更正、终止；正文里的“中标”措辞不会把采购邀请升级成结果。
- 发布日、项目事件日、抓取时间分开。缺日期留空，不使用URL或抓取日期代替。
- 金额只保存带单位、角色和上下文的提及。总金额保持null，多包、多供应商、联合体角色需要核验；预算、代理费、单价不自动变成中标额。
- 数字化候选要求医疗与数字主题同时命中，属于高召回线索标签，不等于最终纳入。餐饮、工程、电梯、药械挂网需要按包件复核。
- 原文按URL哈希保存并记录SHA-256。附件只登记绝对URL，本模块不下载外域附件、不展开压缩包、不执行OCR。既有research可单独做白名单PDF采集。
- `labeled_fields`保留原表格值，多次出现的供应商不覆盖；复杂表格仍是待核验文本，不自动计算公司/项目数。

## 失败必须保留

每次执行生成 `rules.snapshot.json / pages.json / records.json / failures.json / pending.json / summary.json`。失败包含来源、请求/最终网址、阶段、HTTP状态、原因、下一步、时间及已有原文路径。预检缺权限与实际访问失败分开；robots读取失败中的TLS/超时仍保留完整原始原因。当前Fetcher不会保存被拒绝响应的正文，因此该类记录的raw_path可为空。

规则改进另建版本和attempt；不修改首轮失败/原文来制造成功。接口过期、网站迁移、通用选择器未命中、动态空壳和本机网络问题都可以重试验证，但不能据一次失败断言站点永久不可采。
