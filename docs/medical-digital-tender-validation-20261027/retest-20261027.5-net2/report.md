# 医疗数字化中标规则逐站验证

规则版本：2026-10-27.5；生成：2026-10-27T21:18:28+08:00。

本报告按实际请求和保存原文重放生成。原失败不覆盖；离线解析修复与联网成功分开。

登记 93 项；3 项有网页尝试，累计 8 页次。
从原文解析 2 条详情，涉及 1 个来源；医疗数字化候选 0 条。均待事实核验。

保留历史失败/未执行记录 6 条；代码和原因见同目录 historical_failures.json。

| 来源 | 当前最高验证阶段 | 页次/详情 | 历史失败代码 | 原因/待补条件 |
|---|---|---:|---|---|
| 中国政府采购网（中央+地方） (`ccgp`) | not_attempted | 0/0 |  | 2024-04-01全部公告推送是制度要求；实际漏推、历史和合同须地方抽样补查；交换接口需官方申请。 |
| 全国公共资源交易平台 (`ggzy_national`) | not_attempted | 0/0 |  | 入口已登记；未验证全历史/全部栏目覆盖。 |
| 中国招标投标公共服务平台 (`cebpub`) | not_attempted | 0/0 |  | 表单200不能计为列表成功；当前签名/接口未复测，不伪造签名或绕过验证。 |
| 国家卫生健康委 (`nhc`) | not_attempted | 0/0 |  | 国家入口；省市须逐机构核验栏目，政策/专项通知不等于中标。 |
| 国家医保局 (`nhsa`) | not_attempted | 0/0 |  | 国家入口；省市须逐机构核验栏目，政策/专项通知不等于中标。 |
| 国家疾控局 (`ndcpa`) | not_attempted | 0/0 |  | 国家入口；省市须逐机构核验栏目，政策/专项通知不等于中标。 |
| 中国疾控中心 (`china_cdc`) | not_attempted | 0/0 |  | 国家入口；省市须逐机构核验栏目，政策/专项通知不等于中标。 |
| 省级电子招投标公共服务平台目录 (`provincial_ebid_directory`) | not_attempted | 0/0 |  | 与交易中心可能分站或同站；省级交换接口不等于公众开放接口。 |
| 各省药械采购中心目录 (`drug_procurement_directory`) | not_attempted | 0/0 |  | 药品/耗材挂网价不是软件中标；仅补设备+软件捆绑包。 |
| 企查查 (`qcc`) | not_attempted | 0/0 |  | 缺授权密钥/配额；官方最近2年最多2000条限制，不调用计费API。 |
| 天眼查 (`tianyancha`) | not_attempted | 0/0 |  | 缺正式招投标/工商接口权限与配额。 |
| 爱企查 (`aiqicha`) | not_attempted | 0/0 |  | 未验证官方批量API契约，接收合法导出；不猜造接口。 |
| 标找找 (`biaozhaozhao`) | not_attempted | 0/0 |  | API/会员导出的字段、历史范围和许可待官方契约及样本验证。 |
| ICT标局 (`ict_biaoju`) | not_attempted | 0/0 |  | 公开摘要可发现线索；完整正文/导出可能需会员或小程序，未提供授权样本。 |
| 剑鱼标讯 (`jianyu`) | not_attempted | 0/0 |  | 官方API及SDK已找到，缺本任务授权密钥和调用预算。 |
| 天天标讯 (`ttbiao`) | not_attempted | 0/0 |  | API/订阅导出的当前能力与历史范围未验证，待正式文档和样本。 |
| 千里马 (`qianlima`) | not_attempted | 0/0 |  | 缺付费导出授权与字段样本。 |
| 乙方宝 (`yifangbao`) | not_attempted | 0/0 |  | 缺付费导出授权与字段样本。 |
| 中国移动采购与招标网 (`cmcc`) | not_attempted | 0/0 |  | 只采公开公告/候选人/结果；上游医院标、运营商分包、联合体成员分别保留，集团名称不替代法律主体。 |
| 中国电信阳光采购网 (`telecom`) | not_attempted | 0/0 |  | 只采公开公告/候选人/结果；上游医院标、运营商分包、联合体成员分别保留，集团名称不替代法律主体。 |
| 中国联通采购与招标网 (`unicom`) | not_attempted | 0/0 |  | 只采公开公告/候选人/结果；上游医院标、运营商分包、联合体成员分别保留，集团名称不替代法律主体。 |
| 讯飞医疗 (`iflyhealth`) | not_attempted | 0/0 |  | 新闻/案例只能算厂商陈述，须追溯采购人公告；主体及新闻栏目待核验。 |
| 腾讯云医疗健康 (`tencent_cloud`) | not_attempted | 0/0 |  | 新闻/案例只能算厂商陈述，须追溯采购人公告；主体及新闻栏目待核验。 |
| 支付宝开放平台 (`alipay`) | not_attempted | 0/0 |  | 新闻/案例只能算厂商陈述，须追溯采购人公告；主体及新闻栏目待核验。 |
| 厂商公众号/视频号 (`wechat_channels`) | not_attempted | 0/0 |  | 无已验证通用官方RSS；搜狗仅发现，历史/视频正文完整性不保证。 |
| 天眼查新闻舆情 (`tyc_news`) | not_attempted | 0/0 |  | 缺舆情字段接口契约与权限；同稿转载不计独立证据。 |
| 高端医械院等院端招采数据中心 (`device_data_center`) | not_attempted | 0/0 |  | 仅找到服务介绍；供数主体、数据包授权和原文链接样本未取得。 |
| 北京公共资源交易平台 (`ggzy_beijing`) | not_attempted | 0/0 |  | 2026-10-27晚实测：站点部署国密/SM2 TLS（Python OpenSSL报BAD_ECPOINT），系统TLS通道可完成握手；但WAF按UA拦截，爬虫UA对robots.txt与首页均返回403（约65KB拦截页），浏览器UA才返回200。属访问拒绝，未伪造UA绕过。需站点授权或官方数据接口。 |
| 北京政府采购网分网 (`ccgp_beijing`) | not_attempted | 0/0 |  | 2026-10-27两次不同网络实测：DNS可解析，但TCP连接无法建立（curl直连与走代理均HTTP 000，耗时10-15秒超时），Python报ProxyError/ConnectTimeout。属站点侧或网络准入限制，非规则问题。 |
| 天津公共资源交易平台 (`ggzy_tianjin`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 天津政府采购网分网 (`ccgp_tianjin`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 河北公共资源交易平台 (`ggzy_hebei`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 河北政府采购网分网 (`ccgp_hebei`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 山西公共资源交易平台 (`ggzy_shanxi`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 山西政府采购网分网 (`ccgp_shanxi`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 内蒙古公共资源交易平台 (`ggzy_neimenggu`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 内蒙古政府采购网分网 (`ccgp_neimenggu`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 辽宁公共资源交易平台 (`ggzy_liaoning`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 辽宁政府采购网分网 (`ccgp_liaoning`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 吉林公共资源交易平台 (`ggzy_jilin`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 吉林政府采购网分网 (`ccgp_jilin`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 黑龙江公共资源交易平台 (`ggzy_heilongjiang`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 黑龙江政府采购网分网 (`ccgp_heilongjiang`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 上海公共资源交易平台 (`ggzy_shanghai`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 上海政府采购网分网 (`ccgp_shanghai`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 江苏公共资源交易平台 (`ggzy_jiangsu`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 江苏政府采购网分网 (`ccgp_jiangsu`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 浙江公共资源交易平台 (`ggzy_zhejiang`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 浙江政府采购网分网 (`ccgp_zhejiang`) | attempted_unresolved | 2/0 | robots_unavailable | robots.txt check failed: Request failed: TLS verification failed in system store: curl: (60) schannel: SEC_E_UNTRUSTED_ROOT (0x80090325) - ֤�������ɲ������εİ䷢�����䷢�ġ� More details here: https://curl.se/docs/sslcerts.htm |
| 安徽公共资源交易平台 (`ggzy_anhui`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 安徽政府采购网分网 (`ccgp_anhui`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 福建公共资源交易平台 (`ggzy_fujian`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 福建政府采购网分网 (`ccgp_fujian`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 江西公共资源交易平台 (`ggzy_jiangxi`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 江西政府采购网分网 (`ccgp_jiangxi`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 山东公共资源交易平台 (`ggzy_shandong`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 山东政府采购网分网 (`ccgp_shandong`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 河南公共资源交易平台 (`ggzy_henan`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 河南政府采购网分网 (`ccgp_henan`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: TLS verification failed: HTTPSConnectionPool(host='www.ccgp-henan.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by SSLError(SSLCertVerificationError(1, "[SSL: CERTIFICATE |
| 湖北公共资源交易平台 (`ggzy_hubei`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 湖北政府采购网分网 (`ccgp_hubei`) | detail_parsed | 5/2 | discovery_no_links | 当前规则未取得公告正文/详情链接；首页可达不等于采集成功 |
| 湖南公共资源交易平台 (`ggzy_hunan`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 湖南政府采购网分网 (`ccgp_hunan`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 广东公共资源交易平台 (`ggzy_guangdong`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 广东政府采购网分网 (`ccgp_guangdong`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 广西公共资源交易平台 (`ggzy_guangxi`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 广西政府采购网分网 (`ccgp_guangxi`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 海南公共资源交易平台 (`ggzy_hainan`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 海南政府采购网分网 (`ccgp_hainan`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 重庆公共资源交易平台 (`ggzy_chongqing`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 重庆政府采购网分网 (`ccgp_chongqing`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 四川公共资源交易平台 (`ggzy_sichuan`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 四川政府采购网分网 (`ccgp_sichuan`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 贵州公共资源交易平台 (`ggzy_guizhou`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 贵州政府采购网分网 (`ccgp_guizhou`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 云南公共资源交易平台 (`ggzy_yunnan`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 云南政府采购网分网 (`ccgp_yunnan`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 西藏公共资源交易平台 (`ggzy_xizang`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 西藏政府采购网分网 (`ccgp_xizang`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 陕西公共资源交易平台 (`ggzy_shaanxi`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 陕西政府采购网分网 (`ccgp_shaanxi`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 甘肃公共资源交易平台 (`ggzy_gansu`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 甘肃政府采购网分网 (`ccgp_gansu`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 青海公共资源交易平台 (`ggzy_qinghai`) | not_attempted | 0/0 |  | 本轮retest抓到的2条详情整页仅146/265字符，正文JS加载，仍记dynamic_shell |
| 青海政府采购网分网 (`ccgp_qinghai`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 宁夏公共资源交易平台 (`ggzy_ningxia`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 宁夏政府采购网分网 (`ccgp_ningxia`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 新疆公共资源交易平台 (`ggzy_xinjiang`) | not_attempted | 0/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 新疆政府采购网分网 (`ccgp_xinjiang`) | not_attempted | 0/0 |  | 中央导航域名可能迁移；未白名单的重定向先记录，核验后再显式补域。 |
| 新疆兵团公共资源交易平台 (`ggzy_bingtuan`) | not_attempted | 0/0 |  | 本轮retest抓到的详情整页仅125字符，em-tab动态容器，需浏览器渲染或官方接口 |
| 新疆兵团政府采购网 (`ccgp_bingtuan`) | not_attempted | 0/0 |  | 入口已登记；未验证全历史/全部栏目覆盖。 |
| 广州公共资源交易中心 (`ggzy_guangzhou`) | not_attempted | 0/0 |  | 上游只验证水利栏目；本轮需独立核验医疗/软件相关业务分类。 |
| 重庆市疾病预防控制中心招标公示 (`cq_cdc`) | not_attempted | 0/0 |  | 只验证一条采购邀请样本；完整栏目/分页尚未验收。 |

完整字段及原文定位见 observations.json、records.json、inputs.json。
省级入口并不等于全部地市已完成适配；商业授权、JSON契约、附件全文/OCR和人工项目归并仍有缺口。
