# 全国公共资源交易平台（ggzy.gov.cn）医卫数字化采集：探测结果与证据

采集/探测时间 2026-10-28 09:55–10:40；分支 `feat/national-ggzy-medical-digital`；脚本 `codes/1600006.全国公共资源交易平台-医卫数智.py`（正本 `scripts/thirdparty_goverment_spider/`）。

## 一、结论（如实记录：本轮 0 命中，接口不可用）

**全国平台的交易公告检索接口当前从本机网络无法取得数据。** 站点可访问（首页/栏目页 200），但两个列表接口分别被 WAF 拦截和日期校验卡死，未获得任何 `code=200` 响应。脚本已按库内约定完成并如实留痕，待接口恢复或改用浏览器会话后可直接复用。

## 二、站点与接口结构（取自前端 JS，非猜测）

| 项 | 实测结果 |
|---|---|
| 旧入口 deal.ggzy.gov.cn | 全局 NXDOMAIN（DoH 复核），已下线 |
| 新前端 | `https://www.ggzy.gov.cn`（http 80 仅 301 跳 https），列表页 `/deal/dealList.html` 为 Vue 壳 |
| 近一年接口 | `POST /information/pubTradingInfo/getTradList` —— **本机网络稳定 404**（返回站点静态 404 页「网页暂时无法访问」），而同 context 的 `/information/captcha` 返回正常 JSON，说明路径级拦截 |
| 历史接口 | `POST /his/information/pubTradingInfo/getTradList` —— 可达（HTTP 200），但所有实测时间窗返回 `code:400 "结束时间错误！"`；时间窗早于近一年下限（TIMEEND ≤ 当日-366 天）的请求被前置 WAF 以 404 静态页拦截，两条路径合起来**无可用时间窗** |
| 表单参数 | `DEAL_CLASSIFY`（02=政府采购、23=药品采购）、`TIMEBEGIN/TIMEEND`（yyyy-MM-dd，前端限一年内）、`FINDTXT`（单关键词）、`PAGENUMBER` |
| 响应约定 | code 200=正常（data.records/total/pages）；829=需验证码（`/information/captcha`，X-Pass-Token 头 `token#code`）；804=细化条件；800=过频；801/400=错误 |
| 验证码接口 | `/information/captcha` GET 200，返回 base64 图片（脚本不做验证码识别） |

WAF 行为观察：API 路径间歇性返回 404 静态页，与 UA 无关（curl、python-requests、自报 UA 均触发）；请求过密时更频繁，冷却 30–90 秒后恢复；同参数重试结果可复现（同一时间窗多次请求结果一致，非随机拦截）。

## 三、脚本实现（1600006）

- 复用库内约定：`site_fetch` 的自报 UA（`CAICTMedicalResearchBot/1.0`）、证书始终校验、直连优先；新增 POST 能力（requests 失败改系统 curl，`--data-urlencode` 编码）。
- 双接口依次尝试（current → history），逐接口记录「是否获得过 code=200」。
- 检索词默认 `医院/卫生/医保/妇幼/疾控/卫生院`，逐词 × 两栏目（政府采购、药品采购）× `--max_pages` 页；命中后本地按医卫/数字化关键词分类（与 1600005 同口径：医卫数智/医卫设备/医卫其他）。
- 输出：5 列 TSV（files/年月/日期/国家级/）+ 同名 JSON 旁证（记录、失败明细、每页 code/message/total 证据）。
- 防御性解析：records 字段名未实测到 200 样本，按 title/name/dealname、url/link/href、date/time 宽松匹配，原始 JSON 随旁证留存。

## 四、本轮运行结果

- 命令：`--start_date 2026-10-21 --end_date 2026-10-28 --max_pages 1 --keywords "医院,卫生"`
- 结果：命中 0 条，失败 8 项（current 接口 4 次 HTTP 404；history 接口 4 次 code 400「结束时间错误」）。
- 证据：`docs/medical-digital-tender-validation-20261028/national-ggzy-20261028/全国公共资源交易平台-医卫公告.json`（旁证）；`outputs/national-ggzy-20261028/`（WAF 404 页样本、code 400 响应样本、前端 JS 快照、运行日志）。
- 离线回归：`tests/test_national_ggzy_script.py` 新增 11 项（分类口径、API 响应识别、表单构造、接口清单），与北京两脚本 22 项全部通过。已知口径备注：共享 NEGATIVE 词表含「档案」，「健康档案」类标题会被排除（与 1600005 一致，未在本分支改动）。

## 五、缺口与后续方向

1. **接口不可用待人工核验**：需用浏览器打开 `https://www.ggzy.gov.cn/deal/dealList.html` 实际检索一次，确认真实浏览器会话下接口是否可用、是否弹验证码；若可用，再定位脚本被拦的具体指纹差异。
2. **时间窗规则未解**：history 接口的「结束时间错误」触发条件未完全定位（TIMEEND ≥ 当日-365 报错、更早窗口被 WAF 拦），不排除需要验证码 token（X-Pass-Token）才能通过。
3. 代理出口可能被站点区别对待：换出口网络（SITE_FETCH_USE_PROXY=1 或外部环境）复测一次。
4. 若接口长期不可用，备选路径：走 data.ggzy.gov.cn 数据服务（市场主体/信用为主，非公告检索）或地方平台逐一采集。
