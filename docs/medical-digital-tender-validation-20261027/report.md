# 医疗数字化中标规则逐站验证

规则版本：2026-10-27.4；生成：2026-10-27T17:08:31+08:00。

本报告按实际请求和保存原文重放生成。原失败不覆盖；离线解析修复与联网成功分开。

登记 93 项；79 项有网页尝试，累计 89 页次。
从原文解析 7 条详情，涉及 6 个来源；医疗数字化候选 3 条。均待事实核验。

保留历史失败/未执行记录 87 条；代码和原因见同目录 historical_failures.json。

| 来源 | 当前最高验证阶段 | 页次/详情 | 历史失败代码 | 原因/待补条件 |
|---|---|---:|---|---|
| 中国政府采购网（中央+地方） (`ccgp`) | detail_parsed | 3/2 |  | 2024-04-01全部公告推送是制度要求；实际漏推、历史和合同须地方抽样补查；交换接口需官方申请。 |
| 全国公共资源交易平台 (`ggzy_national`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: Request failed: HTTPSConnectionPool(host='www.ggzy.gov.cn', port=443): Read timed out. (read timeout=10) |
| 中国招标投标公共服务平台 (`cebpub`) | attempted_unresolved | 1/0 | robots_denied | Disallowed by robots.txt |
| 国家卫生健康委 (`nhc`) | attempted_unresolved | 2/0 | error | HTTP 412 |
| 国家医保局 (`nhsa`) | attempted_unresolved | 1/0 | discovery_no_links | 当前规则未取得公告正文/详情链接；首页可达不等于采集成功 |
| 国家疾控局 (`ndcpa`) | attempted_unresolved | 1/0 | discovery_no_links | 当前规则未取得公告正文/详情链接；首页可达不等于采集成功 |
| 中国疾控中心 (`china_cdc`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt returned HTTP 445 |
| 省级电子招投标公共服务平台目录 (`provincial_ebid_directory`) | not_attempted | 0/0 | directory_incomplete | 与交易中心可能分站或同站；省级交换接口不等于公众开放接口。 |
| 各省药械采购中心目录 (`drug_procurement_directory`) | not_attempted | 0/0 | directory_incomplete | 药品/耗材挂网价不是软件中标；仅补设备+软件捆绑包。 |
| 企查查 (`qcc`) | not_attempted | 0/0 | authorization_required | 缺授权密钥/配额；官方最近2年最多2000条限制，不调用计费API。 |
| 天眼查 (`tianyancha`) | not_attempted | 0/0 | authorization_required | 缺正式招投标/工商接口权限与配额。 |
| 爱企查 (`aiqicha`) | not_attempted | 0/0 | contract_unverified | 未验证官方批量API契约，接收合法导出；不猜造接口。 |
| 标找找 (`biaozhaozhao`) | not_attempted | 0/0 | contract_unverified | API/会员导出的字段、历史范围和许可待官方契约及样本验证。 |
| ICT标局 (`ict_biaoju`) | not_attempted | 0/0 | authorization_required | 公开摘要可发现线索；完整正文/导出可能需会员或小程序，未提供授权样本。 |
| 剑鱼标讯 (`jianyu`) | not_attempted | 0/0 | authorization_required | 官方API及SDK已找到，缺本任务授权密钥和调用预算。 |
| 天天标讯 (`ttbiao`) | not_attempted | 0/0 | contract_unverified | API/订阅导出的当前能力与历史范围未验证，待正式文档和样本。 |
| 千里马 (`qianlima`) | not_attempted | 0/0 | contract_unverified | 缺付费导出授权与字段样本。 |
| 乙方宝 (`yifangbao`) | not_attempted | 0/0 | contract_unverified | 缺付费导出授权与字段样本。 |
| 中国移动采购与招标网 (`cmcc`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: TLS verification failed: HTTPSConnectionPool(host='b2b.10086.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by SSLError(SSLError(1, '[SSL: UNSAFE_LEGACY_RENEGOTIATION_DISABLED |
| 中国电信阳光采购网 (`telecom`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: Request failed: HTTPSConnectionPool(host='caigou.chinatelecom.com.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by ConnectTimeoutError(<HTTPSConnection(host='caigou.chinatele |
| 中国联通采购与招标网 (`unicom`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: TLS verification failed: HTTPSConnectionPool(host='www.cupb.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by SSLError(SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FA |
| 讯飞医疗 (`iflyhealth`) | listing_discovered | 3/0 | robots_unavailable, discovery_no_links | robots.txt check failed: Request failed: HTTPSConnectionPool(host='www.xunfeihealthcare.com', port=443): Read timed out. (read timeout=15.0) |
| 腾讯云医疗健康 (`tencent_cloud`) | attempted_unresolved | 1/0 | discovery_no_links | No extractable HTML text |
| 支付宝开放平台 (`alipay`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt returned HTML instead of rules |
| 厂商公众号/视频号 (`wechat_channels`) | not_attempted | 0/0 | official_feed_unavailable | 无已验证通用官方RSS；搜狗仅发现，历史/视频正文完整性不保证。 |
| 天眼查新闻舆情 (`tyc_news`) | not_attempted | 0/0 | authorization_required | 缺舆情字段接口契约与权限；同稿转载不计独立证据。 |
| 高端医械院等院端招采数据中心 (`device_data_center`) | not_attempted | 0/0 | contract_unverified | 仅找到服务介绍；供数主体、数据包授权和原文链接样本未取得。 |
| 北京公共资源交易平台 (`ggzy_beijing`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: TLS verification failed: HTTPSConnectionPool(host='ggzyfw.beijing.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by SSLError(SSLError(1, '[SSL: BAD_ECPOINT] bad ecpoint (_ |
| 北京政府采购网分网 (`ccgp_beijing`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: Request failed: HTTPSConnectionPool(host='www.ccgp-beijing.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by ConnectTimeoutError(<HTTPSConnection(host='www.ccgp-beijing.go |
| 天津公共资源交易平台 (`ggzy_tianjin`) | detail_parsed | 2/1 | discovery_no_links | 当前规则未取得公告正文/详情链接；首页可达不等于采集成功 |
| 天津政府采购网分网 (`ccgp_tianjin`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt returned HTML instead of rules |
| 河北公共资源交易平台 (`ggzy_hebei`) | listing_discovered | 1/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 河北政府采购网分网 (`ccgp_hebei`) | attempted_unresolved | 1/0 | robots_denied | robots.txt returned HTTP 403 |
| 山西公共资源交易平台 (`ggzy_shanxi`) | attempted_unresolved | 1/0 | discovery_no_links | 当前规则未取得公告正文/详情链接；首页可达不等于采集成功 |
| 山西政府采购网分网 (`ccgp_shanxi`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: TLS verification failed: HTTPSConnectionPool(host='www.ccgp-shanxi.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by SSLError(SSLCertVerificationError(1, "[SSL: CERTIFICAT |
| 内蒙古公共资源交易平台 (`ggzy_neimenggu`) | listing_discovered | 1/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 内蒙古政府采购网分网 (`ccgp_neimenggu`) | attempted_unresolved | 1/0 | dynamic_shell | JavaScript shell; enable browser rendering to extract content |
| 辽宁公共资源交易平台 (`ggzy_liaoning`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: Request failed: HTTPSConnectionPool(host='www.lnggzy.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by ConnectTimeoutError(<HTTPSConnection(host='www.lnggzy.gov.cn', port= |
| 辽宁政府采购网分网 (`ccgp_liaoning`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: Request failed: HTTPSConnectionPool(host='www.ccgp-liaoning.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by ConnectTimeoutError(<HTTPSConnection(host='www.ccgp-liaoning. |
| 吉林公共资源交易平台 (`ggzy_jilin`) | listing_discovered | 1/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 吉林政府采购网分网 (`ccgp_jilin`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: TLS verification failed: HTTPSConnectionPool(host='www.ccgp-jilin.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE |
| 黑龙江公共资源交易平台 (`ggzy_heilongjiang`) | detail_parsed | 2/1 | discovery_no_links | 当前规则未取得公告正文/详情链接；首页可达不等于采集成功 |
| 黑龙江政府采购网分网 (`ccgp_heilongjiang`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: TLS verification failed: HTTPSConnectionPool(host='www.ccgp-heilongj.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by SSLError(SSLCertVerificationError(1, "[SSL: CERTIFIC |
| 上海公共资源交易平台 (`ggzy_shanghai`) | attempted_unresolved | 1/0 | robots_denied | robots.txt returned HTTP 403 |
| 上海政府采购网分网 (`ccgp_shanghai`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: TLS verification failed: HTTPSConnectionPool(host='www.ccgp-shanghai.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFIC |
| 江苏公共资源交易平台 (`ggzy_jiangsu`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: Request failed: HTTPConnectionPool(host='jsggzy.jszwfw.gov.cn', port=80): Max retries exceeded with url: /robots.txt (Caused by NewConnectionError("HTTPConnection(host='jsggzy.jszwfw.gov.cn', por |
| 江苏政府采购网分网 (`ccgp_jiangsu`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: Request failed: HTTPSConnectionPool(host='www.ccgp-jiangsu.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by ConnectTimeoutError(<HTTPSConnection(host='www.ccgp-jiangsu.go |
| 浙江公共资源交易平台 (`ggzy_zhejiang`) | detail_parsed | 2/1 | discovery_no_links | 当前规则未取得公告正文/详情链接；首页可达不等于采集成功 |
| 浙江政府采购网分网 (`ccgp_zhejiang`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: TLS verification failed: HTTPSConnectionPool(host='www.ccgp-zhejiang.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFIC |
| 安徽公共资源交易平台 (`ggzy_anhui`) | attempted_unresolved | 1/0 | discovery_no_links | 当前规则未取得公告正文/详情链接；首页可达不等于采集成功 |
| 安徽政府采购网分网 (`ccgp_anhui`) | attempted_unresolved | 1/0 | http_not_found | HTTP 404 |
| 福建公共资源交易平台 (`ggzy_fujian`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt returned HTML instead of rules |
| 福建政府采购网分网 (`ccgp_fujian`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: TLS verification failed: HTTPSConnectionPool(host='www.ccgp-fujian.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by SSLError(SSLCertVerificationError(1, "[SSL: CERTIFICAT |
| 江西公共资源交易平台 (`ggzy_jiangxi`) | detail_parsed | 2/1 | discovery_no_links | 当前规则未取得公告正文/详情链接；首页可达不等于采集成功 |
| 江西政府采购网分网 (`ccgp_jiangxi`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt returned HTTP 405 |
| 山东公共资源交易平台 (`ggzy_shandong`) | attempted_unresolved | 1/0 | robots_denied | Disallowed by robots.txt |
| 山东政府采购网分网 (`ccgp_shandong`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt returned HTML instead of rules |
| 河南公共资源交易平台 (`ggzy_henan`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt returned HTML instead of rules |
| 河南政府采购网分网 (`ccgp_henan`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: TLS verification failed: HTTPSConnectionPool(host='www.ccgp-henan.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by SSLError(SSLCertVerificationError(1, "[SSL: CERTIFICATE |
| 湖北公共资源交易平台 (`ggzy_hubei`) | attempted_unresolved | 1/0 | discovery_no_links | 当前规则未取得公告正文/详情链接；首页可达不等于采集成功 |
| 湖北政府采购网分网 (`ccgp_hubei`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: Request failed: HTTPSConnectionPool(host='www.ccgp-hubei.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by ConnectTimeoutError(<HTTPSConnection(host='www.ccgp-hubei.gov.cn |
| 湖南公共资源交易平台 (`ggzy_hunan`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt returned HTML instead of rules |
| 湖南政府采购网分网 (`ccgp_hunan`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: Request failed: HTTPSConnectionPool(host='www.ccgp-hunan.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by ConnectTimeoutError(<HTTPSConnection(host='www.ccgp-hunan.gov.cn |
| 广东公共资源交易平台 (`ggzy_guangdong`) | attempted_unresolved | 1/0 | dynamic_shell | JavaScript shell; enable browser rendering to extract content |
| 广东政府采购网分网 (`ccgp_guangdong`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: TLS verification failed: HTTPSConnectionPool(host='www.ccgp-guangdong.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFI |
| 广西公共资源交易平台 (`ggzy_guangxi`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: TLS verification failed: HTTPSConnectionPool(host='ggzy.jgswj.gxzf.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by SSLError(SSLCertVerificationError(1, "[SSL: CERTIFICAT |
| 广西政府采购网分网 (`ccgp_guangxi`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: TLS verification failed: HTTPSConnectionPool(host='www.ccgp-guangxi.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by SSLError(SSLCertVerificationError(1, "[SSL: CERTIFICA |
| 海南公共资源交易平台 (`ggzy_hainan`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: TLS verification failed: HTTPSConnectionPool(host='zw.hainan.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERI |
| 海南政府采购网分网 (`ccgp_hainan`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: TLS verification failed: HTTPSConnectionPool(host='ccgp-hainan.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VE |
| 重庆公共资源交易平台 (`ggzy_chongqing`) | attempted_unresolved | 1/0 | robots_denied | robots.txt returned HTTP 403 |
| 重庆政府采购网分网 (`ccgp_chongqing`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: Request failed: HTTPSConnectionPool(host='www.ccgp-chongqing.gov.cn', port=443): Read timed out. (read timeout=10) |
| 四川公共资源交易平台 (`ggzy_sichuan`) | listing_discovered | 1/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 四川政府采购网分网 (`ccgp_sichuan`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt returned HTML instead of rules |
| 贵州公共资源交易平台 (`ggzy_guizhou`) | listing_discovered | 1/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 贵州政府采购网分网 (`ccgp_guizhou`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: TLS verification failed: HTTPSConnectionPool(host='www.ccgp-guizhou.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by SSLError(SSLCertVerificationError(1, "[SSL: CERTIFICA |
| 云南公共资源交易平台 (`ggzy_yunnan`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt returned HTML instead of rules |
| 云南政府采购网分网 (`ccgp_yunnan`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: TLS verification failed: HTTPSConnectionPool(host='www.ccgp-yunnan.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by SSLError(SSLError(1, '[SSL: SSLV3_ALERT_HANDSHAKE_FAIL |
| 西藏公共资源交易平台 (`ggzy_xizang`) | attempted_unresolved | 1/0 | discovery_no_links | 当前规则未取得公告正文/详情链接；首页可达不等于采集成功 |
| 西藏政府采购网分网 (`ccgp_xizang`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: Request failed: HTTPSConnectionPool(host='www.ccgp-xizang.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by ConnectTimeoutError(<HTTPSConnection(host='www.ccgp-xizang.gov. |
| 陕西公共资源交易平台 (`ggzy_shaanxi`) | listing_discovered | 1/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 陕西政府采购网分网 (`ccgp_shaanxi`) | attempted_unresolved | 1/0 | discovery_no_links | 当前规则未取得公告正文/详情链接；首页可达不等于采集成功 |
| 甘肃公共资源交易平台 (`ggzy_gansu`) | attempted_unresolved | 1/0 | error | HTTP 412 |
| 甘肃政府采购网分网 (`ccgp_gansu`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt returned HTTP 418 |
| 青海公共资源交易平台 (`ggzy_qinghai`) | listing_discovered | 2/0 | discovery_no_links | 当前规则未取得公告正文/详情链接；首页可达不等于采集成功 |
| 青海政府采购网分网 (`ccgp_qinghai`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: TLS verification failed: HTTPSConnectionPool(host='www.ccgp-qinghai.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICA |
| 宁夏公共资源交易平台 (`ggzy_ningxia`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt returned HTTP 405 |
| 宁夏政府采购网分网 (`ccgp_ningxia`) | attempted_unresolved | 1/0 | discovery_no_links | 当前规则未取得公告正文/详情链接；首页可达不等于采集成功 |
| 新疆公共资源交易平台 (`ggzy_xinjiang`) | listing_discovered | 1/0 |  | 国家导航入口可能迁移；列表/详情/API/市县分页均待逐站验收。 |
| 新疆政府采购网分网 (`ccgp_xinjiang`) | attempted_unresolved | 1/0 | robots_unavailable | robots.txt check failed: TLS verification failed: HTTPSConnectionPool(host='www.ccgp-xinjiang.gov.cn', port=443): Max retries exceeded with url: /robots.txt (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFIC |
| 新疆兵团公共资源交易平台 (`ggzy_bingtuan`) | listing_discovered | 1/0 |  | 入口已登记；未验证全历史/全部栏目覆盖。 |
| 新疆兵团政府采购网 (`ccgp_bingtuan`) | attempted_unresolved | 1/0 | http_not_found | HTTP 404 |
| 广州公共资源交易中心 (`ggzy_guangzhou`) | attempted_unresolved | 1/0 | domain_scope_denied | URL outside allowed public domains |
| 重庆市疾病预防控制中心招标公示 (`cq_cdc`) | detail_parsed | 1/1 | discovery_no_links | 当前规则未取得公告正文/详情链接；首页可达不等于采集成功 |

完整字段及原文定位见 observations.json、records.json、inputs.json。
省级入口并不等于全部地市已完成适配；商业授权、JSON契约、附件全文/OCR和人工项目归并仍有缺口。
