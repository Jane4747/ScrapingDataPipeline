import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';

// Usage: node build_ppt.mjs <config.json> <new_run_directory>
// Produces native PowerPoint charts with embedded workbooks. Never starts Office.
const [configArg, runArg] = process.argv.slice(2);
if (!configArg || !runArg) throw new Error('Usage: node build_ppt.mjs <config.json> <run_dir>');
for (const name of ['PRESENTATION_SKILL_DIR', 'RUNTIME_PYTHON', 'RUNTIME_NODE_MODULES']) {
  if (!process.env[name]) throw new Error(`${name} must be set to the installed bundled runtime/skill path.`);
}
const skillDir = path.resolve(process.env.PRESENTATION_SKILL_DIR);
const runtimePython = path.resolve(process.env.RUNTIME_PYTHON);
const runtimeRequire = createRequire(path.join(path.resolve(process.env.RUNTIME_NODE_MODULES), '_workflow_loader.cjs'));
const { Presentation, PresentationFile, FileBlob } = await import(pathToFileURL(runtimeRequire.resolve('@oai/artifact-tool')).href);
const { applyPresentationChartFont, finalizePresentation } = await import(pathToFileURL(path.join(skillDir, 'container_tools/artifact_tool_utils.mjs')).href);
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const configPath = path.resolve(configArg);
const config = JSON.parse((await fs.readFile(configPath, 'utf8')).replace(/^\uFEFF/, ''));
const workspaceDir = path.resolve(runArg);
const draftDir = path.join(workspaceDir, 'ppt', 'draft');
const finalDir = path.join(workspaceDir, 'ppt', 'final');
const finalPath = path.join(finalDir, 'charts.pptx');
try { await fs.access(finalPath); throw new Error(`Output already exists; use a new run directory: ${finalPath}`); }
catch (error) { if (error.code !== 'ENOENT') throw error; }
if (!Array.isArray(config.figures) || !config.figures.length) throw new Error('config.figures must be non-empty.');
const font = config.fontFamily || 'Microsoft YaHei';
const palette = config.colors || ['#2E75B6', '#D62728', '#4DAF4A', '#8064A2', '#E69138'];
if (!Array.isArray(palette) || !palette.length || palette.some(c => !/^#[0-9a-fA-F]{6}$/.test(c))) throw new Error('colors must be a non-empty list of #RRGGBB colors.');
const source = config.source || {};
const sourceLabel = [source.organization, source.title ? `《${source.title}》` : ''].filter(Boolean).join(' ');
const presentation = Presentation.create({ slideSize: { width: 1600, height: 900 } });
const summaries = [];

function normalized(value) { return Number(value.toPrecision(15)); }
function units(text) { return Array.from(String(text)).reduce((n, c) => n + (/[\u0000-\u00ff]/.test(c) ? 1 : 2), 0); }
function wrap(text, budget) {
  const lines = []; let line = '', width = 0;
  for (const ch of String(text)) {
    const advance = /[\u0000-\u00ff]/.test(ch) ? 1 : 2;
    if (ch === '\n' || width + advance > budget) { lines.push(line); line = ''; width = 0; }
    if (ch !== '\n') { line += ch; width += advance; }
  }
  if (line) lines.push(line);
  return lines;
}
function percentDigits(values) {
  return Math.max(2, ...values.map(value => {
    const [mantissa, exp = '0'] = normalized(value).toString().toLowerCase().split('e');
    return Math.max(0, (mantissa.split('.')[1]?.length || 0) - Number(exp) - 2);
  }));
}
function text(slide, name, content, left, top, width, height, size, color, bold = false) {
  const shape = slide.shapes.add({ geometry: 'textbox', name, position: { left, top, width, height }, fill: 'none', line: { fill: 'none', width: 0 } });
  shape.text = content;
  shape.text.style = { fontSize: size, typeface: font, color, bold, insets: 0, wrap: 'none', autoFit: 'none' };
  return shape;
}
function valueAxis(values) {
  const largest = Math.max(...values);
  if (largest === 0) return { max: 0.1, majorUnit: 0.02 };
  // Leave label room beyond the largest bar; a 100% datum may use a 120% axis.
  const target = largest * 1.13;
  const base = 10 ** Math.floor(Math.log10(target / 5));
  const step = [1, 2, 2.5, 5, 10].map(v => v * base).find(v => v >= target / 5);
  return { max: Number((Math.ceil(target / step) * step).toPrecision(12)), majorUnit: step };
}

// Preflight all figures before writing any presentation files. A source with
// more information than this horizontal-chart layout can show must be split
// deliberately; it is never dropped or quietly shrunk to illegibility.
const figures = config.figures.map((figure, index) => {
  const categories = figure.categories, series = figure.series;
  if (!Array.isArray(categories) || !categories.length || categories.some(c => typeof c !== 'string' || !c.trim())) throw new Error(`Figure ${figure.id}: invalid categories.`);
  if (!Array.isArray(series) || !series.length) throw new Error(`Figure ${figure.id}: no series.`);
  if (categories.length > 18 || series.length > 5 || categories.length * series.length > 30) throw new Error(`Figure ${figure.id}: too dense for one readable horizontal-chart slide (maximum 18 categories, 5 series, and 30 bars). Split the figure explicitly.`);
  if (palette.length < series.length) throw new Error(`Figure ${figure.id}: provide a distinct color for each series.`);
  if (categories.some(c => units(c) > 52)) throw new Error(`Figure ${figure.id}: category labels are too long for this layout; shorten them explicitly or use another layout.`);
  const data = series.map(group => {
    if (typeof group.name !== 'string' || !group.name.trim()) throw new Error(`Figure ${figure.id}: unnamed series.`);
    if (!Array.isArray(group.values) || group.values.length !== categories.length || group.values.some(v => typeof v !== 'number' || !Number.isFinite(v) || v < 0 || v > 1)) throw new Error(`Figure ${figure.id}/${group.name}: invalid percentage values.`);
    const name = group.n == null ? group.name : `${group.name}（N=${group.n}）`;
    return { ...group, chartName: name, values: group.values.map(normalized) };
  });
  if (series.length > 1 && data.reduce((n, g) => n + units(g.chartName) + 6, 0) > 132) throw new Error(`Figure ${figure.id}: legend is too wide; simplify series names explicitly or use another layout.`);
  const digits = percentDigits(data.flatMap(g => g.values));
  if (digits > 6) throw new Error(`Figure ${figure.id}: more than six percentage decimal places requires a different label layout; source values were not rounded.`);
  const titleLines = wrap(config.title || figure.name || `图 ${figure.id || index + 1}`, 64);
  if (titleLines.length > 2) throw new Error(`Figure ${figure.id}: title exceeds two lines; provide a shorter title.`);
  const subtitleParts = [`图 ${figure.id || index + 1}`, figure.subtitle || ''];
  if (series.length === 1 && data[0].n != null && !(figure.subtitle || '').includes(`N=${data[0].n}`)) subtitleParts.push(`N=${data[0].n}`);
  const subtitleLines = wrap(subtitleParts.filter(Boolean).join('  '), 110);
  if (subtitleLines.length > 2) throw new Error(`Figure ${figure.id}: subtitle exceeds two lines.`);
  const footer = [`来源：${sourceLabel || source.path || '见配置文件'}`, figure.sourcePages ? `原文页码：${figure.sourcePages}` : ''].filter(Boolean).join('  ');
  const footerLines = wrap(footer, 160);
  if (footerLines.length > 2) throw new Error(`Figure ${figure.id}: source footer exceeds two lines.`);
  const chartTop = 30 + titleLines.length * 54 + 16 + subtitleLines.length * 32 + 14;
  const chartBottom = footerLines.length > 1 ? 824 : 834;
  const chartHeight = chartBottom - chartTop;
  const barCount = categories.length * series.length;
  const labelSize = barCount > 21 ? 19 : 22;
  const usablePlotHeight = chartHeight - (series.length > 1 ? 80 : 48);
  if (usablePlotHeight / (categories.length * (series.length + 0.48)) < labelSize * 0.85) throw new Error(`Figure ${figure.id}: title/legend leaves insufficient chart height; split or simplify the figure.`);
  return { figure, index, data, digits, titleLines, subtitleLines, footerLines, chartTop, chartHeight, labelSize };
});

for (const item of figures) {
  const { figure, index, data, digits, titleLines, subtitleLines, footerLines, chartTop, chartHeight, labelSize } = item;
  const slide = presentation.slides.add();
  slide.background.fill = '#FFFFFF';
  titleLines.forEach((line, i) => text(slide, `title-${i}`, line, 60, 30 + i * 54, 1470, 60, 44, '#243F5B', true));
  const subtitleTop = 30 + titleLines.length * 54 + 16;
  subtitleLines.forEach((line, i) => text(slide, `subtitle-${i}`, line, 62, subtitleTop + i * 32, 1460, 36, 25, '#51677C'));
  const pctFormat = `0.${'0'.repeat(digits)}%`;
  const scale = valueAxis(data.flatMap(g => g.values));
  const chart = slide.charts.add('bar', {
    position: { left: 42, top: chartTop, width: 1516, height: chartHeight },
    categories: figure.categories,
    series: data.map((group, j) => ({ name: group.chartName, values: group.values, fill: palette[j], line: { fill: palette[j], width: 0 }, valuesFormatCode: pctFormat })),
    barOptions: { direction: 'bar', grouping: 'clustered', gapWidth: data.length >= 3 ? 48 : 80, overlap: 0 },
    hasLegend: data.length > 1,
    legend: { position: 'top', overlay: false, textStyle: { fontSize: 22, fill: '#334155' } },
    xAxis: { visible: true, textStyle: { fontSize: 22, fill: '#334155' }, majorGridlines: null, line: { fill: '#A9B5C1', width: 1 }, labelOffsetPercent: 50 },
    yAxis: { visible: true, numberFormatCode: '0%', min: 0, max: scale.max, majorUnit: scale.majorUnit, textStyle: { fontSize: 20, fill: '#64748B' }, majorGridlines: { fill: '#DDE3EA', width: 1 }, line: { fill: '#A9B5C1', width: 1 } },
    dataLabels: { showValue: true, showCategoryName: false, showSeriesName: false, numberFormatCode: pctFormat, numberFormatSourceLinked: false, position: 'outEnd', textStyle: { fontSize: labelSize, fill: '#243746' } },
    chartFill: '#FFFFFF', plotAreaFill: '#FFFFFF', chartLine: { fill: 'none', width: 0 }, plotAreaLine: { fill: 'none', width: 0 },
  });
  applyPresentationChartFont(chart, { fontFamily: font });
  footerLines.forEach((line, i) => text(slide, `source-${i}`, line, 62, footerLines.length > 1 ? 839 + i * 23 : 851, 1470, 27, 18, '#657487'));
  const sourceDetails = [`来源文件：${(source.path ? path.basename(source.path) : '未填写')}`, `来源名称：${sourceLabel}`, `图号：${figure.id || index + 1}`, `原文页码：${figure.sourcePages || '未填写'}`, `PDF页码：${figure.pdfPages?.join('、') || '未填写'}`];
  const dataDetails = data.map(group => [group.name, group.n == null ? '' : `N=${group.n}`, group.counts == null ? '' : `数量：${group.counts.map(v => v == null ? '未提供' : v).join(', ')}`, `比例：${group.values.map(v => `${(v * 100).toFixed(digits)}%`).join(', ')}`].filter(Boolean).join('\n')).join('\n\n');
  slide.speakerNotes.text = [...sourceDetails, `分类：${figure.categories.join('；')}`, dataDetails, figure.note || '', '比例按原文精度列示。'].filter(Boolean).join('\n');
  summaries.push({ id: figure.id, slide: index + 1, categoryCount: figure.categories.length, seriesCount: data.length, percentageDecimalPlaces: digits, sourcePages: figure.sourcePages || null, pdfPages: figure.pdfPages || [] });
}

await fs.mkdir(draftDir, { recursive: true });
await fs.mkdir(finalDir, { recursive: true });
const rawCandidatePath = path.join(draftDir, 'candidate.pptx');
const candidatePath = path.join(draftDir, 'candidate-axis.pptx');
await (await PresentationFile.exportPptx(presentation)).save(rawCandidatePath);
const patch = spawnSync(runtimePython, [path.join(scriptDir, 'axis_order.py'), rawCandidatePath, candidatePath], { encoding: 'utf8' });
if (patch.status !== 0) throw new Error(patch.stderr || patch.stdout || 'Chart axis order adjustment failed.');
const result = await finalizePresentation({
  workspaceDir, candidatePath, finalPath, pythonExecutable: runtimePython,
  integrityValidatorPath: path.join(skillDir, 'container_tools/inspect_presentation_package_integrity.py'),
  layoutValidatorPath: path.join(skillDir, 'container_tools/inspect_presentation_layout_geometry.py'),
  layoutArgs: ['--expected-slide-size-emu', '15240000,8572500', '--validate-bullet-geometry', '--validate-heading-fit'],
  explicitTotalSlideCount: config.figures.length,
  requiredNativeChartOwnerSlides: config.figures.map((_, i) => i + 1),
  requiredNativeTableOwnerSlides: [],
  materializeLiteralChartWorkbooks: true,
  fontPolicy: { basis: 'design', families: [font] },
  verifyArtifactToolImport: true,
  receiptPath: path.join(draftDir, 'validation.json'),
});
const finalDeck = await PresentationFile.importPptx(await FileBlob.load(finalPath));
for (const [i, slide] of finalDeck.slides.items.entries()) {
  const blob = await finalDeck.export({ slide, format: 'png', scale: 1 });
  await fs.writeFile(path.join(draftDir, `final-slide-${String(i + 1).padStart(2, '0')}.png`), new Uint8Array(await blob.arrayBuffer()));
}
await fs.writeFile(path.join(draftDir, 'figures.json'), JSON.stringify({ configPath, source, figures: summaries, finalPath, finalSha256: result.finalSha256 }, null, 2));
console.log(JSON.stringify({ finalPath, slideCount: config.figures.length, receiptPath: path.join(draftDir, 'validation.json'), previewDirectory: draftDir }));
