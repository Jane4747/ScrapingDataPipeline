# 报告图表提数与 PowerPoint 重绘代码说明

拿到一张分组条形图后，先找图号、同号数据表和图例。类别决定每一行表示什么，图例决定同一行里各系列的顺序，样本量决定百分比的分母。整理后的同一份配置同时供 Excel 和 PowerPoint 使用。

## 从原图还原数据

| 原始材料 | 取数办法 | 核对要点 |
| --- | --- | --- |
| PDF 图旁有可选中文字的配套表 | 在指定页定位同号表，按原顺序提取类别和每组的数量、百分比。跨页时包含续表所在页。 | 对照整页预览，确认没有混入相邻图表。核查首尾类别、每组表头、样本量及零值。 |
| PDF 只有栅格图，或单独收到一张截图 | 放大原图，沿类别轴依次读取标签，按图例把每个标注值录入对应系列，再逐行回看原图。 | 图例颜色只标识系列。重叠或模糊的数字留待查证；从原表补齐后再生成图表。 |
| 图上只有比例 | 保存原图标注的比例。只有来源另给出样本量或数量时，才填写相应字段。 | 留存出处、图号及页码；把正文中的均值等补充指标与图内的系列值区分开。 |

[页面提取脚本](../../scripts/pdf_chart_to_pptx/extract_evidence.py)使用 `pypdf` 读取文字，用 Poppler 渲染整页。[配套表提取脚本](../../scripts/pdf_chart_to_pptx/extract_table_rows.py)处理带文本层的数值行，输出草稿。随后用原图核对类别、系列和比例，再写入 [JSON 配置](../../configs/pdf_charts/example.json)。只有图片的情形通过读图录入，自动解析针对的是文字表。

## 数据单位、舍入和重叠类别

- **医院家数和技术人员人数分别计算。** 例如学历分布的分母是该组技术人员总数，某项业务覆盖率的分母是该组受访医院数。
- **先合并数量，再计算比例。** 要从“硕士”“博士”得到“硕士及以上”，应在同一组内将两类的人数相加，再除以该组人员总数。按两位小数分别显示的比例相加，末位可能有舍入差异。
- **百分比在配置中保存为小数。** 例如原文的 12.50% 对应 `values` 中的 `0.125`。饼图式的互斥分档可能因为舍入合计到 99.99% 或 100.01%。同一家机构可承担多项业务，此类覆盖比例本身就可以合计超过 100%。

下面用示例人数演示合并口径。Excel 和 PPT 展示原图时使用核实过的原文比例；这个计算用于新增的汇总指标。

```python
from decimal import Decimal, ROUND_HALF_UP

masters, doctors, group_total = 16, 4, 160
percent = (Decimal(masters + doctors) * 100 / group_total).quantize(
    Decimal("0.01"), rounding=ROUND_HALF_UP
)
print(f"{percent}%")  # 12.50%
```

[数值校验](../../scripts/pdf_chart_to_pptx/validate_data.py)检查类别与系列的长度、比例范围，以及有数量和分母时的舍入结果。把样本量或单位写错、有一组数据错行时，先回查原图及配套表。

## 从配置生成可编辑图表

[Excel 生成器](../../scripts/pdf_chart_to_pptx/build_excel.mjs)按分类和系列写入数值型百分比，便于核对和复制。[PPT 生成器](../../scripts/pdf_chart_to_pptx/build_ppt.mjs)将同一组数组传给原生图表。调用的核心结构如下，省略了位置、字号及配色。

```javascript
slide.charts.add("bar", {
  categories: figure.categories,
  series: figure.series.map(group => ({
    name: group.name,
    values: group.values,
    valuesFormatCode: "0.00%",
  })),
  barOptions: { direction: "bar", grouping: "clustered" },
  dataLabels: { showValue: true, numberFormatCode: "0.00%" },
});
```

条形图按来源的分类顺序排列。[轴顺序处理](../../scripts/pdf_chart_to_pptx/axis_order.py)确保第一项出现在图的上方。导出时为图表写入内嵌工作簿，PowerPoint 的“编辑数据”可以打开相应数值。标签引用图表数据，改数值后可随图更新。

## 复现与验收

按[运行说明](../../scripts/pdf_chart_to_pptx/README.md)使用示例配置做 DryRun，再生成结果。验收时按三处核对。

1. **原图与配置**。核对来源页、系列顺序、类别数、原文标签值、单位和样本量，跨页表须覆盖续表。
2. **配置与 Excel**。按类别与系列逐格核对数值和百分比格式，区分缺失、零和真实分母。
3. **配置与 PPTX**。确认幻灯片通过关系引用原生图表，图表引用可打开的内嵌 XLSX；核对系列名、类别、数值，查看预览中的标签是否截断。需要验证目标 Office 版本的编辑行为时，可在成品副本上修改一个数值，保存重开后复查图条和标签。

本次复核覆盖四张历史配套表，包括单系列、多系列、跨页续表和可重叠业务选项。提取出的 70 个百分比和 70 个数量与已核验的 Excel 逐项一致。另用一页合成 PDF 与两组、三类的示例配置跑完页面取证、Excel 和 PPT 生成流程，并按原生图表引用的单元格核对了内嵌工作簿的 6 个数值和类别顺序。

[返回想法树](tree.md)
