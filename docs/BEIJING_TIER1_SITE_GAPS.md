# 北京一级医院招采网站采集缺口

核对日期：2026-10-27。依据本轮及此前保存的访问响应、原文、检索日志和核验台账；本次代码整理没有重新测试各站网络。下面的状态是特定时间、网址和客户端的实际观察，不表示网站现在持续处于同一状态。

范围仍为原251家北京一级医院、2024-01-01至2026-10-27医卫数智化招采。上轮251家1629条逐院查询，本轮26家及平台入口149条去重查询；累计16条主表、30条候选或排除。正式与候选合计涉及15家，余236家没有保留记录，原因未知，不能统一列成爬取失败。

## 为什么扩词后仍不能完整取得

扩展词表改善发现范围，但不能解决登录条件、正文遮挡、扫描图、缺日期、使用医院不明或原文未披露金额。公开搜索也不等于遍历各站所有历史分页和附件。目前没有全量真值基准，不能给出可信的整体召回率。

本地程序对域名、robots、页数、深度与响应体积设置边界；搜索由会话工具执行，通用代码主要用于已知URL归档和证据整理。它尚不是针对全部26个网站定制、覆盖历史分页的完整爬虫。

## 逐站说明

| 网站或渠道 | 已观察到的障碍或缺口 | 影响的信息 | 后续可补方向 |
|---|---|---|---|
| [中央政府采购网](https://www.zycg.gov.cn/) | 本轮首页读取超时；已使用域名限定公开搜索补查，没有遍历站内公告库。 | 站内历史分页覆盖；公告详情与电子卖场附件 | 在后续新任务中低频重试官方详情网址；按医院及上级采购单位、项目编号补查。 |
| [北京市政府采购网](https://www.ccgp-beijing.gov.cn/) | 本轮官网首页超时；部分公告已通过北京市公共资源平台及公开索引取得。 | 原站分页与完整历史公告覆盖 | 以采购人和项目编号同时核查北京公共资源平台及原网，后续单独做日期分段分页。 |
| [军队采购网](https://www.plap.mil.cn/) | 首页超时，公开公告索引可检索；原251家名单未核得可新增对应公告，未把匿名某医院对应到名单。 | 站内全量覆盖；匿名采购单位与251家医院的映射 | 仅查公开可访问公告并用采购单位明确名称或可验证别名匹配；保留无法对应状态。 |
| [中国政府采购网](https://www.ccgp.gov.cn/) | 首页及多份公告可读；本轮是医院名称与产品词的公开检索，没有完成站内全库分页。研究所采购也不自动属于其医院。 | 全量覆盖证明；采购人和最终使用医院关系 | 保留研究所、医院、统一采购单位三种主体，并通过需求文件证明具体使用医院。 |
| [北京市公共资源交易服务平台](https://ggzyfw.beijing.gov.cn/jyxxzbjggg/20261010/5740604.html) | 本地Python抓取在robots检查时发生TLS BAD_ECPOINT并记录robots_unavailable；网页读取工具另已成功取得公告正文。怀柔区域医保项目正文未提供目标牙防所清单。 | 本地抓取正文归档；区域项目与目标医院关系；需求附件 | 核查本地TLS运行环境并保持证书校验；通过已允许的官方正文和公开附件补充，不将区域总价分摊给目标医院。 |
| [北京市政府采购电子交易平台](http://zbcg-bjzc.zhongcy.com/bjczj-portal-site/index.html#/home) | 怀柔医保智能审核系统公告说明获取电子版招标文件需CA数字证书或电子营业执照登录；公告列示售价为0元。尚未取得含覆盖医院的完整需求文件。 | 服务医院名单；第五章技术需求 | 优先找官方结果公告公开附件或代理机构公开版本；需要账号的文件由有权限人员合法获取后导入。 |
| [通用技术集团中心采购平台](https://cg.gt.cn/) | 本地采集首页与北京中兴医院采购目录时，robots.txt返回HTTP403，程序按访问规则停止，记为robots_denied。 | 集团采购列表与公告全文；北京中兴及东里医院来源追溯 | 不绕过访问限制；继续查公开代理公告、医院官网及授权取得的原文，后续重试须保留状态。 |
| [京能集团电子招标平台](https://www.powerbeijing-ec.com/) | 本轮入口返回405 Method Not Allowed，未取得平台站内公告库。 | 官方原文和完整历史采购覆盖 | 从集团官网核验当前公开入口及公告直接链接，使用合法公开接口；保留第三方转载标识。 |
| [京能集团官方网站](https://www.powerbeijing.com/newa_s32655.html) | 用于确认京能e购渠道的官方介绍页直接打开超时，公开索引曾提供该介绍线索。 | 采购平台迁移说明全文核验 | 后续对该公开介绍页或其新版入口低频复核。 |
| [中国政法大学采购管理系统](https://cgw.cupl.edu.cn/) | HTTP入口转到HTTPS后返回412 Precondition Failed。 | 校医院采购管理系统站内详情 | 通过学校采购办及正式代理机构公开公告交叉定位项目号；在允许环境中核验正常访问路径。 |
| [中国政法大学招投标及采购管理办公室](https://ztbjcgglbgs.cupl.edu.cn/) | 主页读取返回403 Forbidden；域名限定公开索引查询已执行。 | 校医院公告前序比选详情和确定日期 | 依项目编号查代理机构正式公告及合法公开转载；无法读取的日期留空。 |
| [华北电力大学资产管理处](https://zcc.ncepu.edu.cn/zbgg/7c6786f1e97e47b0b94e2ddc6de77ff0.htm) | 两条公告HTTP200且提取出导航和PDF链接，但通用HTML正文抽取返回empty；后续已阅读相关PDF确认HIS接口需求。 | HTML正文自动归档；公告日期抽取；附件技术参数 | 增加该站正文选择器与附件回退；对原始HTML和PDF分别保存。折扣及单价不换算成未知成交总额。 |
| [采招网](https://www.bidcenter.com.cn/newscontent-426500874-1.html) | 已知详情请求跳转到HumanMachineVerification.shtml；跳转子域不在该来源白名单，程序记录blocked。其他目录页可公开读取。 | 部分公告全文；正式结果来源追溯 | 不自动放开任意跳转域或绕过人机核验；使用原始发布平台与公开转载核对。 |
| [水滴标讯](https://biaoxun.shuidi.cn/detail/51307c79a3c8ffe15d546c8e994d1df1.html) | 北京中兴医院自助机页面可见标题、日期和候选公示阶段，公告正文显示会员登录后可见；公开来源按钮未取得原站网址。 | 技术范围；候选供应商完整字段；正式成交结果及金额 | 查通用集团或代理机构公开正式结果；授权取得正文后导入，并保持候选与中标分开。 |
| [贝登招标企业目录](https://www.vedeng.com/qiye/283174/zhong.html) | 既有核验记录称直接HTTP访问429；保存的目录搜索只给相对时间、同名成交标题与供应商线索，缺明确日期和完整项目号。 | 确定发布日期；同名项目关联；正式供应商核验 | 低频重试或追溯央采正式成交公告；不以7天前或标题一致判断同一项目。 |
| [医疗招标网](https://www.yiliaozhaobiao.com/news-c1bdab39b6c1af1dd1c19c48f071de52/) | 部分转载供应商字段遮挡；机场车牌识别项目只见目录缓存，当前列表与缓存不一致，数条详情打开工具失败。 | 中标单位；明确日期；公告全文和原始来源 | 用完整项目名/编号追原官网；保留原始缓存及当前页面时间，遮挡信息不猜填。 |
| [千里马及乙方宝聚合页](https://www.qianlima.com/gjxx/275308_8_4) | 政法校医院比选只有目录缓存且当前页已无同条目；第二福利院用友服务详情打开失败；部分项目转载提示会员查看隐藏字段。 | 前序采购详情与确定日期；供应商/金额；上级单位与医院关系 | 追溯代理机构原文，以项目编号与正文确认日期；会员信息由授权途径取得。 |
| [国家体育总局运动医学研究所](https://www.sport.gov.cn/yys/n27506619/c28353424/content.html) | 官方目录和多份详情抓取成功；体育数据服务一条正文为扫描图片，文本层只有标题/日期；多条研究所项目未明确体育医院使用范围。 | 图片公告的采购内容；具体医院用途关系 | 对已获公开图片做OCR并核对原图；通过需求文件确认使用机构，不以报名地点在医院推定医院用途。 |
| [中招国际招标有限公司](https://www.cntcitc.com.cn/more/article.html?gContentId=f187415dac2346d4a0c520ee559aaf64) | 牙科设备公告和候选公示可读，但详细参数未公开于已获正文；电子标书获取说明要求注册登录并购买下载。第一候选人44.9万元未核为正式成交。 | 软件/接口/数据输出技术参数；正式结果和成交金额 | 查后续正式结果和公开技术附件；有权限者获取标书后导入。 |
| [必联网](https://www.ebnew.com/businessShow/707682204.html) | 东里医院电子皮肤镜等项目公开转载可读，部分字段提示登录查看；具体技术要求指向尚未取得的第五章。 | 技术参数；数智化范围判定 | 优先查采购方公开需求附件，保留技术边界待核状态。 |
| [创识科技新闻页面](https://www.echase.cn/news.html) | 可检得仲博医院自助缴费项目中标自述，但只有供应商月度新闻，缺采购方公告和完整日期。 | 正式公告日期；采购人；成交金额 | 以供应商新闻为发现线索，按医院和项目名核查采购方或代理公告。 |
| [北京市中介服务网上交易平台](https://zjfw.beijing.gov.cn/page/zjfw/zjjg/lygg) | 履约公告目录可检得第二福利院档案数字加工项目；尚无完整采购/中选详情，目录未显示供应商和金额，亦未明确附属医院使用。 | 采购或中选日期；供应商和金额；医院归属 | 后续追溯该项目单独详情和需求文件，日期按语义分别保存。 |
| [北京农学院校医院官网](https://xyy.bua.edu.cn/info/1158/1694.htm) | 官网应用新闻确认药品追溯码扫码发药和高拍仪使用，但未取得采购或成交公告。 | 采购人公告；供应商；成交金额 | 继续在学校资产采购部门按项目、设备及上级采购单位检索。 |
| [电力能源招标网及京能聚合页](https://www.dnezb.com/detail/43074679) | 公开独立采购正文支持京煤两分院病案系统改造，但聚合页页脚明确是第三方；单一来源采购公示没有正式中标单位和成交额。 | 官方原文追溯；后续正式成交单位和金额 | 保持转载标识，按P-DY26002639追查后续正式结果。 |
| [电子验收单公开镜像](https://zhengxin-pub.cdn.bcebos.com/) | 机场货物项目DD24051411021920公开镜像能检得，但没有核实到明确公告或验收日期。 | 2024年至今日期判定 | 核查原始验收单完整页及央采验收单核查入口；未知日期保持空值与待核。 |
| [麦投保公开招标转载](https://www.maituobao.com/bidding/a25b4a129aa78150) | 五里店最终中标转载披露完整工程合同价671.623428万元；施工包括综合布线、机房、监控，但数字部分未单独报价。 | 独立数字化采购金额；官方最终结果网址 | 保留整项合同价的明确标记；如果以后取得工程量清单或分项合同，再按原文增加分项。 |

## 各站判断边界与本地证据

下面路径以仓库根目录为基准；原始证据保存在本机outputs，未上传公开仓库。字段标为curated的引文来自既有核验台账，不等同独立HTTP响应日志。完整逐字引文及路径保存在本机outputs/beijing-hospital-channel-review-20261027/site_gap_audit.json。

### 1. 中央政府采购网

超时不能确定由服务端故障、网络链路或客户端请求环境造成，不能直接称为反爬。

- `outputs/beijing-hospital-channel-supplement-20261027/evidence_root/portal_open.json`（raw_saved_response）

### 2. 北京市政府采购网

不代表网站持续不可用，也不代表医院没有采购。

- `outputs/beijing-hospital-channel-supplement-20261027/evidence_root/portal_open.json`（raw_saved_response）

### 3. 军队采购网

没有证据可把超时归因于军采统一禁止抓取；匿名主体也不能凭地名猜测。

- `outputs/beijing-hospital-channel-supplement-20261027/evidence_root/portal_open.json`（raw_saved_response）
- `outputs/beijing-hospital-channel-supplement-20261027/platform_channels.json`（curated_channel_log）

### 4. 中国政府采购网

没有证据表明该网站整体不可爬；未命中不是不存在。

- `outputs/beijing-hospital-channel-supplement-20261027/channels_central.json`（curated_channel_log）
- `outputs/beijing-hospital-channel-supplement-20261027/candidate_notices.json`（curated_record）

### 5. 北京市公共资源交易服务平台

这是特定客户端请求失败，不能说网站全面不可访问或robots明确禁止。

- `outputs/beijing-hospital-channel-supplement-20261027/archive/beijing-tier1-new-notices-20261027/collection/attempt-001/failures.json`（raw_saved_response）
- `outputs/beijing-hospital-channel-supplement-20261027/candidate_notices.json`（curated_record）

### 6. 北京市政府采购电子交易平台

不能把第三方会员页面的付费要求说成官方标书收费；未验证匿名浏览能否得到其他公开附件副本。

- `outputs/beijing-hospital-channel-supplement-20261027/evidence_beijing/open_02.json`（raw_saved_response）
- `outputs/beijing-hospital-channel-supplement-20261027/evidence_beijing/open_02.json`（raw_saved_response）

### 7. 通用技术集团中心采购平台

没有读取到robots正文的Disallow规则；不能把robots.txt的403描述成公告页面本身403或所有人不可访问。

- `outputs/beijing-hospital-channel-supplement-20261027/archive/beijing-tier1-official-20261027/collection/attempt-001/failures.json`（raw_saved_response）

### 8. 京能集团电子招标平台

405只能说明该请求方法不被该端点接受；是否入口迁移、网关策略或方法限制尚未查明。

- `outputs/beijing-hospital-channel-supplement-20261027/evidence_enterprise/open001.json`（raw_saved_response）

### 9. 京能集团官方网站

不能从单页超时推断集团官网全部不可访问。

- `outputs/beijing-hospital-channel-supplement-20261027/evidence_enterprise/open001.json`（raw_saved_response）

### 10. 中国政法大学采购管理系统

尚未核实是前置条件、网关校验或其他策略，不应直接等同验证码或封IP。

- `outputs/beijing-hospital-channel-supplement-20261027/evidence_central/search_008.json`（raw_saved_response）

### 11. 中国政法大学招投标及采购管理办公室

没有证据判定为账号要求、IP封禁或某一反爬产品。

- `outputs/beijing-hospital-channel-supplement-20261027/evidence_central/search_009.json`（raw_saved_response）

### 12. 华北电力大学资产管理处

HTTP200正文抽取失败不是网络拒绝；现有证据不足以确定是模板选择器还是HTML结构导致。

- `outputs/beijing-hospital-channel-supplement-20261027/archive/beijing-tier1-new-notices-20261027/collection/attempt-001/failures.json`（raw_saved_response）
- `outputs/beijing-hospital-channel-supplement-20261027/summary_c.json`（curated_summary）

### 13. 采招网

本次停止的直接程序原因是域名边界，跳转目的为人机核验；不是所有该站页面都不可读。

- `outputs/beijing-hospital-channel-supplement-20261027/archive/beijing-tier1-new-notices-20261027/collection/attempt-001/failures.json`（raw_saved_response）
- `outputs/beijing-hospital-channel-supplement-20261027/archive/beijing-tier1-new-notices-20261027/collection/attempt-001/failures.json`（raw_saved_response）

### 14. 水滴标讯

页面关联企业并不能证明该企业已经中标；没有正式结果不能把候选改成成交。

- `outputs/beijing-hospital-channel-supplement-20261027/evidence_b/open_001.json`（raw_saved_response）
- `outputs/beijing-hospital-channel-supplement-20261027/candidate_notices.json`（curated_record）

### 15. 贝登招标企业目录

429在本次审计中只有既有核验备注，未发现独立HTTP响应日志，因此不把它提升为新实测结论。

- `outputs/beijing-hospital-channel-supplement-20261027/candidate_notices.json`（curated_record）
- `outputs/beijing-hospital-channel-supplement-20261027/previous/evidence_c/search26.json`（raw_saved_response）

### 16. 医疗招标网

工具无法打开不等于源站HTTP封禁；目录相邻日期不能自动归给项目。

- `outputs/beijing-hospital-channel-supplement-20261027/candidate_notices.json`（curated_record）
- `outputs/beijing-hospital-channel-supplement-20261027/candidate_notices.json`（curated_record）
- `outputs/beijing-hospital-channel-supplement-20261027/evidence_c/followup019.json`（raw_saved_response）

### 17. 千里马及乙方宝聚合页

缓存显示的邻近日期可能错配；不可把当前空缺说成项目撤销。

- `outputs/beijing-hospital-channel-supplement-20261027/candidate_notices.json`（curated_record）
- `outputs/beijing-hospital-channel-supplement-20261027/evidence_beijing/open_03.json`（raw_saved_response）

### 18. 国家体育总局运动医学研究所

这些记录少主要是图片解析与归属核验，不是整个站爬取失败。

- `outputs/beijing-hospital-channel-supplement-20261027/candidate_notices.json`（curated_record）
- `outputs/beijing-hospital-channel-supplement-20261027/candidate_notices.json`（curated_record）

### 19. 中招国际招标有限公司

不能仅凭数字设备名称判定数智化采购，也不能以候选报价替代中标金额。

- `outputs/beijing-hospital-channel-supplement-20261027/evidence_b/open_001.json`（raw_saved_response）
- `outputs/beijing-hospital-channel-supplement-20261027/candidate_notices.json`（curated_record）

### 20. 必联网

电子或系统字样不能单独证明属于信息化建设项目。

- `outputs/beijing-hospital-channel-supplement-20261027/evidence_a/open_01.json`（raw_saved_response）
- `outputs/beijing-hospital-channel-supplement-20261027/candidate_notices.json`（curated_record）

### 21. 创识科技新闻页面

这属于证据性质不足，不能称作页面无法抓取；也不能将企业自述升级为正式公告。

- `outputs/beijing-hospital-channel-supplement-20261027/candidate_notices.json`（curated_record）

### 22. 北京市中介服务网上交易平台

目录入库日不等于招标日；福利院采购不必然用于医院。

- `outputs/beijing-hospital-channel-supplement-20261027/candidate_notices.json`（curated_record）

### 23. 北京农学院校医院官网

应用新闻不是采购公告，缺采购字段不是抓取工具自动可修补的字段。

- `outputs/beijing-hospital-channel-supplement-20261027/candidate_notices.json`（curated_record）

### 24. 电力能源招标网及京能聚合页

不能因为域名或页面标题含京能便当作官网；拟定供应商不等于最终中标。

- `outputs/beijing-hospital-channel-supplement-20261027/evidence_enterprise/open001.json`（raw_saved_response）
- `outputs/beijing-hospital-channel-supplement-20261027/records.validated.json`（curated_record）

### 25. 电子验收单公开镜像

订单编号中的240514不能单独证明日期；搜索器相对发布时间也不是验收日期。

- `outputs/beijing-hospital-channel-supplement-20261027/candidate_notices.json`（curated_record）

### 26. 麦投保公开招标转载

这是披露颗粒度不足，不能通过猜比例拆分金额；转载交叉核验不能替代未找到的官方结果页。

- `outputs/beijing-hospital-channel-supplement-20261027/records.validated.json`（curated_record）

## 对旧记录的一处更正

官方公告注明电子招标文件售价0元，但需CA/电子营业执照登录获取。第三方会员隐藏/付费不能归因于官方标书收费。

旧候选文件candidate_notices.json第22项（索引21，hospital_id 241）含“公开附件跳转付费页面”的表述，容易把第三方展示条件误写为官方收费。已在本说明及本机corrections.json更正，历史原件保留。主表16条不受影响，该项目仍因未证明目标医院纳入服务范围而待核。

## 优先补齐顺序

1. 追溯项目编号和正式结果原文，补官方来源、公告日期与最终成交阶段。
2. 获取公开需求附件或由有权限人员取得的文件，确认使用医院、产品参数和分项价格。
3. 为已证实可读站点增加正文选择器、附件回退、日期分段与分页检查点；扫描件采用OCR并核对原图。
4. 记录每次重试结果和剩余范围；未查明原因写未知，不将未检到、范围排除、非采购新闻统称抓取失败。
