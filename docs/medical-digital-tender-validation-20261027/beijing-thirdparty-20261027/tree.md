# 想法树 20261027-213520

- 状态：completed
- 创建：2026-10-27 21:35:20
- 更新：2026-10-27 21:51:17
- 工具：goverment_spider
- 主题：北京两条官方线经本机第三方库采集医疗招采公告
- 交付：json

## 节点

- **requirement** `need`：用本机第三方库 goverment_spider 采集北京市政府采购网与北京市公共资源交易平台的医疗类招标/中标公告，按库内约定输出5列TSV与详情JSON，失败留痕。
  - **choice** `route`：选定 goverment_spider。命中线索：政府站点脚本(北京市政府采购网)、政府站点脚本(北京市公共资源交易平台)、runner --site 指定站点执行、codes/*.py 站点脚本约定、files/*.txt 5列TSV导出。
    - **decision** `theme`：主题确认为：北京两条官方线经本机第三方库采集医疗招采公告
      - **decision** `delivery`：交付格式确认为：json（站点5列TSV + 详情JSON）
        - **action** `run-1`：第1次执行 · 北京市政府采购网：成功11条、失败0条
        - **action** `run-2`：第2次执行 · 北京公共资源交易平台：成功4条、失败0条
        - **action** `run-3`：第3次执行 · 北京市政府采购网：成功11条、失败0条
        - **action** `run-4`：第4次执行 · 北京公共资源交易平台：成功4条、失败0条
        - **action** `run-5`：第5次执行 · 北京公共资源交易平台：成功4条、失败0条
        - **结果** `result`：两站均为 2026-10-27 当日、各翻 2 页：北京市政府采购网 11 条（医卫数智3/设备6/其他2），北京公共资源交易平台 4 条（设备3/其他1），失败均为 0。字段含项目编号、采购人、中标供应商、金额，属真实公告事实，未做规模推算。
          - **口径提醒** `result-mix`：公资平台“中标成交公告”当日 20 条里确无医卫项目（多为公安、环保、会议服务），4 条不是漏采；政采网仅覆盖 2 页，更早日期需放大页数或改日期窗。
          - **实例** `result-samples`：海淀医院信息化升级改造中标 1169.58 万；市属医院 2026 医用设备带量采购放射组预算 11182 万（采购人北京市医院管理中心）；通州妇幼保健院 1790.79 万；天坛医院超融合扩容 259.65 万；隆福医院中医药示范设备 589.46 万。
          - **已修正错误** `correction`：推翻本轮之前两条“不可采”结论，证据留在规则配置与台账。
            - **纠错1：政采网** `correction-ccgp`：此前只测 443 端口，两轮网络均 TCP 不通，误判为站点/网络准入限制。补测 80 端口：TCP 可连，http:// 首页 200（约90KB）、不跳转 https、robots.txt 为 404。真实结论是“仅 HTTP 入口可用”，规则新增 transport=http_only。
            - **纠错2：公资平台** `correction-ggzy`：此前记为“WAF 按 UA 拦爬虫”。逐 UA 对照后该判断不成立：被拦的只有 UA 含 python-requests 的请求，自报 UA CAICTMedicalResearchBot、curl/8.4.0、不发 UA 均返回 200，robots.txt 为 404。唯一障碍是国密 SM2 TLS（OpenSSL 报 SSL: BAD_ECPOINT），本轮未使用浏览器 UA。
          - **代码沉淀** `code`：按 goverment_spider 库约定新增两个站点脚本，经 runner --site 执行而非直接调用：codes/1600004.北京市政府采购网-医疗中标.py、codes/1600005.北京公共资源交易平台-医疗中标.py；共用 site_fetch.py（先 requests，TLS 失败才换系统 TLS 栈的 curl，证书始终校验，curl=60 直接报错）。repos/ 被 gitignore，正本另存 scripts/thirdparty_goverment_spider/。
            - **本轮修的问题** `code-fix`：① 扩充数字化关键词（超融合/服务器/存储/云平台/DRG 等），否则设备类以外的数智项目会漏；② 取页默认直连：本机代理曾把公资平台 index_2.html 拦成 502，改直连后失败清零；③ 想法树写入：cmd_run 原用固定 id 写 theme/delivery/run，同一棵树连跑多次会产生重复节点，tree.md 把 5 次执行渲染成 125 条重复项，现改为 upsert + 递增 run 节点 id。
          - **验证** `verify`：规则版本升至 2026-10-27.6，两站 rule_status 均为 third_party_script_verified 并写入 third_party 脚本映射；新增 tests/test_beijing_official_scripts.py 11 项离线回归（列表解析、详情字段、关键词正负例、分页地址）；全库 271 项测试 270 通过，唯一失败 test_full_install_fails_preflight_before_installing_missing_repositories 经 stash 复测确认为与本轮无关的既有问题（install 预检读 stderr 为 None）。
          - **证据位置** `evidence`：台账 docs/medical-digital-tender-validation-20261027/beijing-thirdparty-20261027/（report.md + 两站逐条 JSON + 任务树快照）；规则 configs/medical_digital_tender_rules.json；原始首页与栏目样本 outputs/beijing-thirdparty-20261027/。
          - **缺口** `gaps`：
            - **覆盖深度** `gap-pages`：仅当日 2 页，未按日期窗回溯到 2024 起的存量；未验收全量页数下的翻页稳定性。
            - **跨站去重** `gap-dedup`：同一项目在两站重复出现（如“市属医院设备带量采购”），尚未按项目编号做跨站归并。
            - **栏目缺口** `gap-channels`：公资平台的中标候选人公示、合同公示未纳入；政采网区级招标/合同公告仅登记未采。
            - **仍需授权** `gap-authorize`：浙江（根证书不受信任）、河南（证书主机名不匹配）保持不可采，未关闭校验也未加例外；商业 API 无授权不发计费请求。
          - **后续方向** `next`：① 按项目编号跨站去重；② 把合同公示/候选人公示纳入；③ 给 runner 透传 --max-pages；④ 按日期窗回溯并与 ccgp 中央网北京属地数据交叉核对完整性。
