# 想法树 pdf-chart-to-editable-ppt-20261111

- 状态：completed
- 创建：2026-11-11T15:34:49+08:00
- 更新：2026-11-11T15:34:49+08:00
- 工具：pypdf、Poppler、Artifact Tool、PowerShell
- 主题：报告图表提数与 PowerPoint 原生图表重绘
- 交付：[代码总结](CODE_SUMMARY.md)、[运行说明](../../scripts/pdf_chart_to_pptx/README.md)、[示例配置](../../configs/pdf_charts/example.json)

## 节点

- **需求** `need`：把图片或 PDF 图表中的关键数据整理成可核对的结构，生成可在 PowerPoint 中编辑数据的图表。
  - **取数** `evidence`：保存图号、来源页、原图及配套表。文字表可提取候选数据行；截图或扫描件须读取并核对已标出的数值。[配套表解析](../../scripts/pdf_chart_to_pptx/extract_table_rows.py)
    - **统计口径** `data`：每组记录类别、原比例、分母及已知数量。区分机构数和人员数，处理多项业务重叠以及显示精度带来的舍入差异。[口径及换算示例](CODE_SUMMARY.md#数据单位舍入和重叠类别)
      - **Excel** `excel`：将分类和图例排列为可复制的数值表，保留百分比格式和数据出处。[Excel 生成代码](../../scripts/pdf_chart_to_pptx/build_excel.mjs)
      - **PPT** `ppt`：用原生分组条形图绑定系列值，导出可编辑的内嵌工作簿，调整分类轴顺序并按数值显示标签。[PPT 生成代码](../../scripts/pdf_chart_to_pptx/build_ppt.mjs)
  - **核验** `verify`：依次检查原图与配置、配置与 Excel、图表及其内嵌工作簿中的类别和数值，并查看幻灯片渲染。[复现与验收](CODE_SUMMARY.md#复现与验收)
