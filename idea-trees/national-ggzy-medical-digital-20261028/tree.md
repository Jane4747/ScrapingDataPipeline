# 想法树 national-ggzy-medical-digital-20261028

- 状态：partial（脚本完成并验证留痕能力，接口未取得数据）
- 创建：2026-10-28 10:05
- 更新：2026-10-28 10:45
- 工具：goverment_spider（新增站点脚本 1600006）
- 主题：全国公共资源交易平台医卫数字化公告采集
- 交付：json（5列TSV + 旁证JSON）

## 节点

- **requirement** `need`：新建代码分支，采集全国公共资源交易平台（ggzy.gov.cn）医卫数字化相关招标/中标公告，沿用 goverment_spider 库内约定输出。
  - **choice** `route`：选定新增站点脚本接入。命中线索：全国平台为聚合门户（各地方平台公告归集）、旧入口 deal.ggzy.gov.cn 已停、新前端 www.ggzy.gov.cn 列表页为 Vue 壳 + POST 接口、库内 codes/*.py 站点脚本与 --site 子串匹配约定可直接扩展。
    - **decision** `branch`：新建分支 feat/national-ggzy-medical-digital（自 feat/bj-xa-medical-bid HEAD），用户既有未提交改动原样保留。
      - **decision** `entry`：接口契约取自前端内联 JS（非猜测）：POST /information/pubTradingInfo/getTradList（近一年）与 POST /his/information/pubTradingInfo/getTradList（历史），参数 DEAL_CLASSIFY(02政采/23药品)、TIMEBEGIN/TIMEEND、FINDTXT、PAGENUMBER；响应 code 200/829(验证码)/804/800/801。
        - **action** `probe-1`：deal.ggzy.gov.cn 域名 NXDOMAIN（DoH 复核），确认旧入口下线。
        - **action** `probe-2`：近一年接口本机网络稳定 404（返回站点静态 404 页）；同 context 的 /information/captcha 返回正常 JSON，判定为路径级拦截而非站点故障。
        - **action** `probe-3`：历史接口可达（HTTP 200），但实测所有时间窗返回 code 400「结束时间错误！」；TIMEEND ≤ 当日-366 天的窗口被前置 WAF 以 404 静态页拦截。两路径合计无可用时间窗。
        - **action** `probe-4`：WAF 行为：与 UA 无关、请求过密更频繁、冷却 30–90s 恢复、同参数结果可复现（非随机）。
        - **action** `code`：新增 scripts/thirdparty_goverment_spider/1600006.全国公共资源交易平台-医卫数智.py 并部署到 repos/goverment_spider/codes/；POST 能力脚本内实现（requests 失败改系统 curl，证书始终校验）；默认检索词 医院/卫生/医保/妇幼/疾控/卫生院，逐词×两栏目×翻页，命中后按 1600005 同口径分类（医卫数智/设备/其他）；5列TSV + 旁证JSON（含每页 code/message/total 页面证据）。
        - **action** `run-1`：真实冒烟（2026-10-21~10-28，词=医院,卫生，各1页）：命中 0 条、失败 8 项（current 4×HTTP 404；history 4×code 400）。结果如实留痕，未伪造成功。
          - **验证** `verify`：新增 tests/test_national_ggzy_script.py 11 项离线回归（分类口径、API 响应识别含 WAF HTML/829/400、表单构造、接口清单）；与北京两脚本共 22 项全部通过。口径备注：共享 NEGATIVE 词表含「档案」，「健康档案」类标题被排除（与 1600005 一致，本分支不改）。
          - **证据位置** `evidence`：docs/medical-digital-tender-validation-20261028/national-ggzy-20261028/（report.md + 旁证JSON）；outputs/national-ggzy-20261028/（WAF 404 页样本、code 400 响应、前端 JS 快照、运行日志）。
          - **缺口** `gaps`：接口未能取得任何 code=200 响应；records 字段名未实测（脚本为防御性解析，原始 JSON 随旁证留存）；验证码流程未验证（829 路径留待人工/浏览器）。
          - **后续方向** `next`：① 浏览器打开 dealList.html 实检一次，确认真实会话下接口可用性与验证码触发点；② 定位 history 接口「结束时间错误」的确切校验规则（不排除需 X-Pass-Token）；③ 换出口网络复测；④ 若接口长期不可用，改走地方平台逐一采集或 data.ggzy.gov.cn 数据服务评估。
