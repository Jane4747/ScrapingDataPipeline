# 从报告图表提取百分比并生成可编辑 PPT

这个工具用同一份经核对的 JSON 数据生成 Excel 工作表和 PowerPoint 原生条形图。每个图号对应一张工作表和一页幻灯片，保留类别顺序、分组名称、比例、分母和来源页码。PPT 的“编辑数据”打开随图嵌入的工作簿。

## 从原件得到数据

1. 用纸面图号定位完整图、图例与同号配套表。记录印刷页码和从 1 开始的 PDF 页码，同号配套表可能延续到下一页。
2. 用下面的命令输出指定页的 PNG、可选中文字和来源文件的 SHA256。表格有文字层时，可用[配套表提取脚本](EXTRACTION.md)提取行数据。遇到纯图片时，按标签逐行录入各组数据，对照完整页面核对。缺少清晰标签时回查数据表或更高清的原件。
3. 对照每个图例检查每行的类别、数量、比例和分母。将复核后的结果放入配置中的 `figures`。原图若未提供某组的数量，省略该组 `counts`，或用 `null` 表示个别未知数量。百分比必须有明确数值才可绘制。各项百分比保留原文精度。
4. 比例、数量和样本量均已知时，程序逐项核对 `数量 ÷ 本组 N` 四舍五入到百分数小数点后两位的值。遇到多选题，设 `multiResponse: true`，各项按同一组样本量计算，Excel 跳过合计行。

只提取页面供阅读时，可在安装了 Python 3.11+、pypdf 和 Poppler 的环境中执行下例。输出目录须为新目录，若 `pdftoppm` 未加入 PATH，可加 `--poppler <pdftoppm 路径>`。

```powershell
python scripts/pdf_chart_to_pptx/extract_evidence.py --pdf ./source.pdf --pages 7 8 --output ./outputs/evidence-review
```

## 运行示例

在仓库根目录使用 Windows PowerShell 7。Excel 和 PPT 的生成入口使用 Codex 桌面版附带的本地 runtime 与对应的表格、演示文稿工具资源。Excel 用到 Node.js 和 `@oai/artifact-tool`。PPT 还用到 Python、lxml 以及演示文稿资源中的图表工作簿生成与文件校验工具。按需运行 `evidence` 时需 Python、pypdf 和 Poppler。

[示例配置](../../configs/pdf_charts/example.json)有两个工作组和三项业务，采用合成数据。其中 0% 表示已知数量为零。仅试做 Excel 或 PPT 时直接执行如下命令，源 PDF 仅在页面提取阶段用到。

```powershell
$entry = './scripts/pdf_chart_to_pptx/run.ps1'
$config = './configs/pdf_charts/example.json'
& $entry -Config $config -Stage ppt -DryRun
& $entry -Config $config -Stage ppt
& $entry -Config $config -Stage excel
```

实际处理报告时，复制配置，填写该报告的数据及页码。`source.path` 相对于配置文件。也可用 `-SourcePdf` 指向本地原件（相对路径从当前工作目录起算），一次生成证据页、Excel 和 PPT。

```powershell
& $entry -Config ./configs/pdf_charts/my-report.json -SourcePdf ./source.pdf -Stage all -DryRun
& $entry -Config ./configs/pdf_charts/my-report.json -SourcePdf ./source.pdf -Stage all
```

运行时位置可用 `-RuntimeRoot`、`-PresentationSkillDir`、`-SpreadsheetSkillDir` 指定。每次生成使用新的运行目录，默认位于 `outputs/pdf_charts/<RunId>/`，可用 `-OutputRoot` 和 `-RunId` 修改。打印结果中的 `runDirectory` 为实际路径。

| 结果 | 相对于运行目录的位置 |
| --- | --- |
| 各页文本、页面 PNG 和来源哈希 | `evidence/` |
| 可复制的类别、数值型比例、样本量和可选计数 | `excel/data.xlsx` |
| 可编辑的 PPT 图表 | `ppt/final/charts.pptx` |
| PPT 各页预览和结构校验记录 | `ppt/draft/` |

## 配置与程序对应关系

| 配置字段 | 输入约定 |
| --- | --- |
| `schema`、`title` | 版本固定为 `pdf-percent-charts.v1`，title 是共同主题 |
| `source` | 填写 path、title、organization |
| `figures[].id`、`name`、`subtitle` | 唯一图号、Excel 工作表名、图的分组或主题说明 |
| `sourcePages`、`pdfPages` | 图表所在印刷页说明、PDF 页码数组（从 1 开始） |
| `categories`、`series[].name` | 按原图顺序录入完整类别及图例 |
| `series[].values` | 0 至 1 之间的比例小数。8.44% 写作 0.0844 |
| `series[].n`、`series[].counts` | 本组样本量和逐类数量。未知时可省略 |
| `countUnit`、`multiResponse` | 统计单位（如“家”“人”），类别可重叠时显式设为 true |
| `note` | 来源说明、分母或舍入差异，可在工作表和幻灯片备注查阅 |

`validate_data.py` 核对组内分母及数组长度。`build_excel.mjs` 将比例写作数值型单元格，采用百分比格式。`build_ppt.mjs` 用同一组类别和数值创建横向分组条形图，以自动数据标签显示百分数，再为图表生成嵌入工作簿。`axis_order.py` 调整原生分类轴的方向，使第一条类别显示在最上方。

检查生成文件时可对照预览、Excel 与来源页。PPT 草稿目录的 validation.json 记录原生图表关系、嵌入工作簿和版面校验结果。在 PowerPoint 中右键图表并选择“编辑数据”，可修改相应系列的数据。
