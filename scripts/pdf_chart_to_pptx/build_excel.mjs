import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

// Usage: node build_excel.mjs <config.json> <new_run_directory>
// The caller validates the configuration and marks artifact creation first.
const [configArg, runArg] = process.argv.slice(2);
if (!configArg || !runArg) throw new Error('Usage: node build_excel.mjs <config.json> <run_dir>');
const runtimeModules = process.env.RUNTIME_NODE_MODULES;
if (!runtimeModules) throw new Error('RUNTIME_NODE_MODULES must point to the bundled Node modules directory.');
const runtimeRequire = createRequire(path.join(path.resolve(runtimeModules), '_workflow_loader.cjs'));
const { Workbook, SpreadsheetFile } = await import(pathToFileURL(runtimeRequire.resolve('@oai/artifact-tool')).href);
const configPath = path.resolve(configArg);
const config = JSON.parse((await fs.readFile(configPath, 'utf8')).replace(/^\uFEFF/, ''));
const outputDir = path.join(path.resolve(runArg), 'excel');
const outputFile = path.join(outputDir, 'data.xlsx');
try { await fs.access(outputFile); throw new Error(`Output already exists; use a new run directory: ${outputFile}`); }
catch (error) { if (error.code !== 'ENOENT') throw error; }
if (!Array.isArray(config.figures) || !config.figures.length) throw new Error('config.figures must be non-empty.');
const font = config.fontFamily || 'Microsoft YaHei';
const source = config.source || {};
const sourceLabel = [source.organization, source.title ? `《${source.title}》` : '', source.path ? `（${path.basename(source.path)}）` : ''].filter(Boolean).join(' ');
const workbook = Workbook.create();
const records = [];
const sheetNames = new Set();

function column(number) {
  let label = '';
  for (let n = number; n > 0; n = Math.floor((n - 1) / 26)) label = String.fromCharCode(65 + (n - 1) % 26) + label;
  return label;
}
function normalized(value) {
  // Excel has 15 significant decimal digits. This removes binary-division tails,
  // e.g. 0.10529999999999999, without changing the source's displayed percentage.
  return Number(value.toPrecision(15));
}
function percentDigits(values) {
  return Math.max(2, ...values.map(value => {
    const [mantissa, exp = '0'] = normalized(value).toString().toLowerCase().split('e');
    return Math.max(0, (mantissa.split('.')[1]?.length || 0) - Number(exp) - 2);
  }));
}
function splitLine(text, budget = 84) {
  const result = []; let line = '', width = 0;
  for (const ch of String(text)) {
    const advance = /[\u0000-\u00ff]/.test(ch) ? 1 : 2;
    if (ch === '\n' || width + advance > budget) { result.push(line); line = ''; width = 0; }
    if (ch !== '\n') { line += ch; width += advance; }
  }
  if (line) result.push(line);
  return result;
}
function writeWideText(sheet, start, text, last, size = 10, color = '#5B6671', bold = false) {
  let row = start;
  for (const line of splitLine(text, size >= 15 ? 90 : 110)) {
    sheet.getRange(`A${row}`).values = [[line]];
    sheet.getRange(`A${row}:${last}${row}`).format.font = { name: font, size, color, bold };
    row++;
  }
  return row;
}

for (const [figureIndex, figure] of config.figures.entries()) {
  const showTotals = !figure.multiResponse;
  const unit = figure.countUnit ? '（' + figure.countUnit + '）' : '';
  const categories = figure.categories;
  const groups = figure.series;
  if (!Array.isArray(categories) || !categories.length || categories.some(c => typeof c !== 'string' || !c.trim())) throw new Error(`Figure ${figure.id}: invalid categories.`);
  if (!Array.isArray(groups) || !groups.length) throw new Error(`Figure ${figure.id}: no series.`);
  for (const group of groups) {
    if (typeof group.name !== 'string' || !group.name.trim()) throw new Error(`Figure ${figure.id}: unnamed series.`);
    if (!Array.isArray(group.values) || group.values.length !== categories.length || group.values.some(v => typeof v !== 'number' || !Number.isFinite(v) || v < 0 || v > 1)) throw new Error(`Figure ${figure.id}/${group.name}: invalid percentage values.`);
    if (group.counts != null && (!Array.isArray(group.counts) || group.counts.length !== categories.length || group.counts.some(v => v != null && (!Number.isSafeInteger(v) || v < 0)))) throw new Error(`Figure ${figure.id}/${group.name}: invalid counts.`);
  }
  const sheetName = figure.name || `图 ${figure.id || figureIndex + 1}`;
  if (sheetName.length > 31 || /[\\/?*\[\]:]/.test(sheetName) || sheetNames.has(sheetName.toLowerCase())) throw new Error(`Invalid or duplicate Excel worksheet name: ${sheetName}`);
  sheetNames.add(sheetName.toLowerCase());
  const sheet = workbook.worksheets.add(sheetName);
  const last = column(groups.length + 1);
  const layoutLast = column(Math.max(4, groups.length + 1));
  const expectedRows = categories.length * 2 + 36;
  sheet.showGridLines = false;
  sheet.tabColor = '#294D70';
  const all = sheet.getRange(`A1:${layoutLast}${expectedRows}`);
  all.format.font = { name: font, size: 11, color: '#202A35' };
  all.format.verticalAlignment = 'center';
  all.format.rowHeight = 24;
  sheet.getRange(`A1:A${expectedRows}`).format.columnWidthPx = Math.max(250, Math.min(500, Math.max(...categories.map(c => c.length)) * 17));
  sheet.getRange(`B1:${layoutLast}${expectedRows}`).format.columnWidthPx = Math.max(190, Math.min(360, Math.max(...groups.map(g => g.name.length)) * 17));
  sheet.getRange('A1').format.rowHeight = 10;
  let row = 2;
  row = writeWideText(sheet, row, `图 ${figure.id || figureIndex + 1}  ${config.title || ''}`, layoutLast, 15, '#243E58', true);
  sheet.getRange(`A2:${layoutLast}${row - 1}`).format.rowHeight = 32;
  sheet.getRange(`A${row - 1}:${layoutLast}${row - 1}`).format.borders = { bottom: { style: 'thin', color: '#9BAFC1' } };
  if (figure.subtitle) row = writeWideText(sheet, row, figure.subtitle, layoutLast, 11, '#294D70', true);
  if (sourceLabel) row = writeWideText(sheet, row, `来源：${sourceLabel}`, layoutLast);
  const locator = [figure.sourcePages ? `原文页码：${figure.sourcePages}` : '', figure.pdfPages?.length ? `PDF页码：${figure.pdfPages.join('、')}` : ''].filter(Boolean).join('；');
  if (locator) row = writeWideText(sheet, row, locator, layoutLast);
  row++;
  sheet.getRange(`A${row}`).values = [['比例']];
  sheet.getRange(`A${row}`).format.font = { name: font, size: 11, bold: true, color: '#294D70' };
  const headerRow = ++row, firstDataRow = headerRow + 1, lastDataRow = headerRow + categories.length, sumRow = lastDataRow + 1;
  const headers = ['分类', ...groups.map(g => g.name)];
  sheet.getRange(`A${headerRow}:${last}${headerRow}`).values = [headers];
  sheet.getRange(`A${firstDataRow}:${last}${lastDataRow}`).values = categories.map((category, i) => [category, ...groups.map(g => normalized(g.values[i]))]);
  if (showTotals) sheet.getRange(`A${sumRow}`).values = [['比例合计（仅作核对）']];
  const groupDetails = [];
  for (const [i, group] of groups.entries()) {
    const col = column(i + 2), digits = percentDigits(group.values), format = `0.${'0'.repeat(digits)}%`;
    sheet.getRange(`${col}${firstDataRow}:${col}${sumRow}`).setNumberFormat(format);
    if (showTotals) sheet.getRange(`${col}${sumRow}`).formulas = [[`=SUM(${col}${firstDataRow}:${col}${lastDataRow})`]];
    groupDetails.push({ name: group.name, n: group.n ?? null, valueRange: `${col}${firstDataRow}:${col}${lastDataRow}`, sumCell: showTotals ? `${col}${sumRow}` : null, sumRatio: normalized(group.values.reduce((a, b) => a + b, 0)), percentDecimalPlaces: digits });
  }
  const headerRows = [headerRow], totalRows = showTotals ? [sumRow] : [], dataBlocks = [[firstDataRow, lastDataRow]];
  row = sumRow + 2;
  if (groups.some(g => g.n != null)) {
    sheet.getRange(`A${row}:${last}${row}`).values = [['样本量 N' + unit, ...groups.map(g => g.n ?? null)]];
    sheet.getRange(`B${row}:${last}${row}`).setNumberFormat('#,##0');
    sheet.getRange(`A${row}:${last}${row}`).format.fill = '#EDF2F7';
    row += 2;
  }
  if (groups.some(g => g.counts != null)) {
    sheet.getRange(`A${row}`).values = [['数量' + unit]];
    sheet.getRange(`A${row}`).format.font = { name: font, size: 11, bold: true, color: '#294D70' };
    const countHeader = row + 1, countStart = row + 2, countEnd = countHeader + categories.length, countSum = countEnd + 1;
    headerRows.push(countHeader); if (showTotals) totalRows.push(countSum); dataBlocks.push([countStart, countEnd]);
    sheet.getRange(`A${countHeader}:${last}${countHeader}`).values = [headers];
    sheet.getRange(`A${countStart}:${last}${countEnd}`).values = categories.map((category, i) => [category, ...groups.map(g => g.counts?.[i] ?? null)]);
    sheet.getRange(`B${countStart}:${last}${countSum}`).setNumberFormat('#,##0');
    if (showTotals) sheet.getRange(`A${countSum}`).values = [['数量合计']];
    for (const [i, group] of groups.entries()) {
      const col = column(i + 2);
      if (showTotals && group.counts && group.counts.every(v => v != null)) {
        sheet.getRange(`${col}${countSum}`).formulas = [[`=SUM(${col}${countStart}:${col}${countEnd})`]];
        groupDetails[i].countSum = group.counts.reduce((a, b) => a + b, 0);
        groupDetails[i].countSumCell = `${col}${countSum}`;
      }
      groupDetails[i].countRange = `${col}${countStart}:${col}${countEnd}`;
    }
    row = countSum + 2;
  }
  for (const hr of headerRows) {
    const range = sheet.getRange(`A${hr}:${last}${hr}`);
    range.format.fill = '#294D70';
    range.format.font = { name: font, size: 11, bold: true, color: '#FFFFFF' };
    range.format.horizontalAlignment = 'center'; range.format.rowHeight = 30;
    range.format.borders = { insideVertical: { style: 'thin', color: '#FFFFFF' } };
  }
  for (const tr of totalRows) {
    sheet.getRange(`A${tr}:${last}${tr}`).format.font = { name: font, size: 11, bold: true, color: '#243E58' };
    sheet.getRange(`A${tr}:${last}${tr}`).format.borders = { top: { style: 'thin', color: '#9BAFC1' } };
  }
  for (const [start, end] of dataBlocks) {
    sheet.getRange(`B${start}:${last}${end + 1}`).format.horizontalAlignment = 'right';
    for (let r = start; r <= end; r += 2) sheet.getRange(`A${r}:${last}${r}`).format.fill = '#F5F7FA';
  }
  row = writeWideText(sheet, row, (showTotals ? '比例按原文精度列示。' : '同一样本可对应多个类别，各项按本组样本量计算。'), layoutLast);
  if (figure.note) row = writeWideText(sheet, row, figure.note, layoutLast);
  if (categories.length > 10) sheet.freezePanes.freezeRows(headerRow);
  records.push({ id: figure.id, sheet: sheetName, copyRange: `A${headerRow}:${last}${lastDataRow}`, previewRange: `A1:${layoutLast}${row - 1}`, groups: groupDetails });
}

workbook.recalculate();
await fs.mkdir(outputDir, { recursive: true });
for (const [i, record] of records.entries()) {
  const sheet = workbook.worksheets.getItem(record.sheet);
  for (const group of record.groups) {
    if (!group.sumCell) continue;
    const actual = sheet.getRange(group.sumCell).values[0][0];
    if (typeof actual !== 'number' || Math.abs(actual - group.sumRatio) > 1e-12) throw new Error(`Formula sum mismatch: ${record.sheet}/${group.name}`);
    if (group.countSumCell && sheet.getRange(group.countSumCell).values[0][0] !== group.countSum) throw new Error(`Count sum mismatch: ${record.sheet}/${group.name}`);
  }
  const preview = await workbook.render({ sheetName: record.sheet, range: record.previewRange, scale: 1.5, format: 'png' });
  const previewPath = path.join(outputDir, `preview-${String(i + 1).padStart(2, '0')}.png`);
  await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
  record.previewPath = previewPath;
}
const scan = await workbook.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!', options: { useRegex: true, maxResults: 50 }, summary: 'final formula error scan', maxChars: 5000 });
await fs.writeFile(path.join(outputDir, 'formula-scan.ndjson'), scan.ndjson || '');
await (await SpreadsheetFile.exportXlsx(workbook)).save(outputFile);
await fs.writeFile(path.join(outputDir, 'verification.json'), JSON.stringify({ configPath, source, records }, null, 2));
console.log(JSON.stringify({ outputFile, sheetCount: records.length, verification: path.join(outputDir, 'verification.json') }));
