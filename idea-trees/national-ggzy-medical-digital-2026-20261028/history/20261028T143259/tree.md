# 想法树 national-ggzy-medical-digital-2026-20261028

- 状态：partial
- 创建：2026-10-28T14:08:04+08:00
- 更新：2026-10-28T14:08:04+08:00
- 工具：本地Chrome/Playwright + site_fetch + national_ggzy + artifact-tool
- 主题：2026全国公共资源交易平台医疗数字化公开采购
- 交付：E:\CAICTBigData\coding\outputs\01a17c0d-96d1-79a3-9665-f4fc255ee0c7\全国公共资源交易平台_医疗数字化_2026.xlsx

## 节点

- **requirement** `need`：采集全国公共资源交易平台2026-01-01至2026-10-28发布的医疗数字化公告，提供项目、产品、采购人、客户标签、供应商、运营商、万元金额、场景及原文链接。
  - **result** `access`：普通本地Chrome会话下，POST /information/pubTradingInfo/getTradList已实取code 200及公告。原先脚本的404/历史接口错误仍保存在旧任务，不改写为成功。
    - **decision** `body`：详情a路径是外壳；按实际iframe指向获取同一全国平台/html/b/正文。复用site_fetch处理text/plain MIME的HTML，开启Windows系统证书信任，始终校验证书。
  - **decision** `scope`：先政府采购（02，0202/0201，省平台1+财政部3），再工程建设（01，0104/0101，省平台1+央企2+商务部6）。检索词：医,卫生,疾控,妇幼,血站,急救。其他公告栏目和仅正文出现的医疗词不保证覆盖。
    - **correction** `source-map`：前端证实SOURCE_TYPE=3才是财政部，4是自然资源部。保留collection旧范围及失败；独立collection-v2改为1,3，import-manifest.json列来源与文件哈希。
    - **implementation** `paging`：按月逐词请求，结果达1000则递归二分日期；逐页保存原始JSON。单日达1000会停止并留下待细分缺口。每次显式请求至少间隔3.2秒。
  - **implementation** `code`：主适配器pipeline/research/national_ggzy.py（PARSER_VERSION=6），复用zycg/bid_common解析组件；保留旧1600006脚本和用户暂存/未暂存改动，不自动提交。
    - **rules** `fields`：仅从原文提取实体与标的；标签为名称/标题规则，非人工核验声明。采购公告、候选人公示、更正、终止不填最终中标单位和金额。
      - **rules** `amount`：只转换明确中标/成交金额，元除10000，亿元乘10000；预算、评审报价、单价及百分比不当作中标总额。多标包未有明确总额则主表留空，分项表逐行留金额，不与主表重复加总。
      - **verification** `tables`：修复外层布局表与嵌套表串行、畸形产品单元格带入联系方式、将品目号/供应商当产品等问题。对不可靠字段留空；保留原始HTML和完整文本。
      - **evidence** `samples`：真实样本：龙岗中心医院信息化基础设施22055416元=2205.5416万元；江苏省人民医院资产系统592800元=59.28万元；南宁市第四人民医院机房（二期）648000元=64.8万元。记录均有本地原文及全国平台URL。
    - **verification** `tests`：test_national_ggzy_collector.py 22项 + test_national_ggzy_script.py 11项，合计33项离线通过。不能以此代替联网成功证据。
  - **delivery** `excel`：交付outputs/01a17c0d-96d1-79a3-9665-f4fc255ee0c7/全国公共资源交易平台_医疗数字化_2026.xlsx，含中标成交、中标分项、采购线索、覆盖与缺口。当前验证快照：215条结果公告、70条分项、83条线索；均为公告计数，不等于去重项目数。
    - **implementation** `excel-code`：support/build.mjs用bundled artifact-tool生成工作簿；当前运行库HYPERLINK函数未实现，仅用stdlib ZIP补原生超链接。金额为数值、日期有类型、冻结标题和项目列，全部URL逐项校验。
  - **action** `live`：本机有限批次进程support/run_collection.mjs运行；进度outputs/national-ggzy-medical-digital-2026-20261028/job.json，Excel约每180秒有新记录时刷新。运行依赖本机开机及网络；非定时提醒服务。
    - **boundary** `budget`：每阶段每批500条检索请求，最多12轮，详情每阶段累计6000次。预算到检查点可继续；验证码、访问限制或重复证书错误会停留并如实报告。不要用删除锁、关闭证书校验或伪造结果恢复。
  - **provenance** `archive`：原collection、原0命中调研outputs/national-ggzy-20261028、旧想法树national-ggzy-medical-digital-20261028均保留。当前资料collection-v2含导入清单、lists/articles/texts、失败与恢复记录；前次暂停的job和runner日志另存attempt-1。
  - **next** `next`：继续推进未完成窗口和工程建设队列，按原文补不可靠字段，核查重复发布与不同标包；只有所选窗口全部处理并核对失败后才能报告该范围完成，不能据此声称全国全部覆盖。
