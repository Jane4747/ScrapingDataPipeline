# 想法树 20261015-caict-health

- 状态：completed
- 创建：2026-10-15 20:06:00
- 更新：2026-10-15 20:10:00
- 工具：crawl4ai
- 主题：中国信通院科研能力栏目中与医疗、健康相关的页面
- 交付：Excel，字段为栏目、标题、日期、链接、命中词、列表页

## 节点

- **requirement** `need`：爬取 https://www.caict.ac.cn/kxyj/ 里关于医疗、健康的网页。
  - **decision** `theme`：主题限定为医疗和健康。医药、卫生、数字健康、健康医疗算在内。标题里单独出现的「健康发展」不算，避免把产业发展类页面算进来。
    - **decision** `delivery`：交付 Excel。Jane 这次没有另指定格式，表格能直接打开核对。
      - **choice** `tool`：栏目是分页列表，普通请求会返回 412。用已安装的 crawl4ai 打开浏览器，沿「下一页」翻完蓝皮书、ICT深度观察、权威数据、专题报告、CAICT观点。
        - **action** `run`：脚本 scripts/caict_kxyj_health.py。五个栏目共翻了 119 个列表页。
          - **result** `output`：命中 23 条。Excel 在 outputs/caict-kxyj-health/caict_kxyj_health.xlsx，同目录有 JSON。日期取自链接里的发布日期；权威数据 PDF 链接没有这个日期字段。
