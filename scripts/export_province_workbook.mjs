import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const [taskDir, moduleDir] = process.argv.slice(2);
if (!taskDir || !moduleDir) throw new Error('Task directory and bundled module directory are required');
const resolver = createRequire(path.join(moduleDir, '_artifact_resolver.cjs'));
const { Workbook, SpreadsheetFile } = await import(pathToFileURL(resolver.resolve('@oai/artifact-tool')).href);
const request = JSON.parse(await fs.readFile(path.join(taskDir, 'request.json'), 'utf8'));
const summary = JSON.parse(await fs.readFile(path.join(taskDir, 'summary.json'), 'utf8'));
const rows = JSON.parse(await fs.readFile(path.join(taskDir, 'delivery', 'records.json'), 'utf8'));
const headers = request.fields;
const wb = Workbook.create();
const sheet = wb.worksheets.add('公告明细');
sheet.showGridLines = false;
const col = n => { let value = ''; for (let x = n; x > 0; x = Math.floor((x - 1) / 26)) value = String.fromCharCode(65 + (x - 1) % 26) + value; return value; };
const endCol = col(headers.length);
const literal = value => typeof value === 'string' && /^[=+@]/.test(value) ? "'" + value : value;
const matrix = rows.map(row => headers.map(key => {
  let value = row[key] ?? null;
  if (key === '时间') return /^\d{4}-\d{2}-\d{2}$/.test(value ?? '') ? new Date(value + 'T00:00:00Z') : null;
  if (key === '中标金额（万元）') return typeof value === 'number' && Number.isFinite(value) ? value : null;
  if (typeof value === 'string' && value.length > 32700) value = value.slice(0, 32620) + '\n内容超过单元格长度，完整内容请查看本行原文网址。';
  return literal(value);
}));
const lastRow = Math.max(6, matrix.length + 5);
sheet.getRange('A2').values = [[`分省医疗数字化采购公告（第${request.batch}批）`]];
sheet.getRange('A2').format.font = { name: 'Arial', size: 14, bold: true };
sheet.getRange('A3').values = [[`${request.start} 至 ${request.end}；当前保留 ${rows.length} 条公告；采集状态：${summary.status}；入口：${request.entry}`]];
sheet.getRange('A3').format.font = { name: 'Arial', size: 10, italic: true, color: '#475569' };
sheet.getRange(`A5:${endCol}5`).values = [headers];
if (matrix.length) sheet.getRange(`A6:${endCol}${lastRow}`).values = matrix;
const used = sheet.getRange(`A5:${endCol}${lastRow}`);
used.format.font = { name: 'Arial', size: 10, color: '#172B4D' };
used.format.rowHeight = 65;
used.format.wrapText = true;
used.format.verticalAlignment = 'top';
sheet.getRange(`A5:${endCol}5`).format = { fill: '#1F4E78', font: { name: 'Arial', size: 10, bold: true, color: '#FFFFFF' }, rowHeight: 42, wrapText: true, horizontalAlignment: 'center', verticalAlignment: 'center' };
const widths = [13, 54, 38, 38, 22, 38, 18, 21, 24, 34, 50, 24, 16, 32, 30, 58, 45, 78, 78, 34, 55, 55];
widths.forEach((width, i) => { sheet.getRange(`${col(i + 1)}5:${col(i + 1)}${lastRow}`).format.columnWidth = width; });
if (matrix.length) {
  sheet.getRange(`A6:A${lastRow}`).setNumberFormat('yyyy-mm-dd');
  sheet.getRange(`H6:H${lastRow}`).setNumberFormat('#,##0.0000');
  sheet.getRange(`H6:H${lastRow}`).format.horizontalAlignment = 'right';
  sheet.tables.add(`A5:${endCol}${lastRow}`, true, 'ProvinceProcurementNotices');
}
sheet.freezePanes.freezeRows(5);
sheet.freezePanes.freezeColumns(2);

const scope = wb.worksheets.add('采集范围');
scope.showGridLines = false;
scope.getRange('A2').values = [['分省采集范围与覆盖状态']];
scope.getRange('A2').format.font = { name: 'Arial', size: 14, bold: true };
scope.getRange('A4:F4').values = [['区域', '口径', '状态', '公告记录', '未完成检索窗口', '说明']];
const states = { completed: '已完成声明的执行范围', running: '采集中', queued: '等待执行', partial: '覆盖不完整', failed: '执行失败', not_started: '未开始' };
const scopeRows = summary.sources.map(s => [s.source_name, s.scope === 'city' ? '市级' : '省级', states[s.status] ?? s.status, s.records ?? 0, s.pending_search_windows ?? null, s.stop_reason ?? '']);
const scopeLast = Math.max(5, 4 + scopeRows.length);
scope.getRange(`A5:F${scopeLast}`).values = scopeRows;
scope.getRange(`A4:F${scopeLast}`).format.font = { name: 'Arial', size: 10 };
scope.getRange('A4:F4').format = { fill: '#1F4E78', font: { name: 'Arial', size: 10, bold: true, color: '#FFFFFF' }, horizontalAlignment: 'center', rowHeight: 25 };
scope.getRange(`A5:F${scopeLast}`).format.rowHeight = 32;
scope.getRange(`A5:F${scopeLast}`).format.wrapText = true;
[16, 12, 22, 12, 18, 90].forEach((w, i) => scope.getRange(`${col(i + 1)}4:${col(i + 1)}${scopeLast + 2}`).format.columnWidth = w);
const notes = [
  ['时间按公告发布日期；未提取到的资格、专家和金额留空，具体缺口见主表。'],
  ['省级记录来自全国公共资源交易平台省级聚合检索，覆盖以该入口收录为限，不等于各省门户全量。'],
  ['深圳、广州为市级口径，与广东省级窗口存在重叠，已按原文网址去重。'],
  ['资格要求仅在项目编号和采购人均一致、内容唯一时关联；公告记录不等于独立项目，规则标签不代表事实核验。'],
  [`本轮完成声明的区域 ${summary.regions_completed}/${summary.regions_total} 个；去重 ${summary.duplicates_removed} 条；市级归属未标注 ${summary.city_unconfirmed} 条。`]
];
notes.forEach((line, i) => { scope.getRange(`A${scopeLast + 2 + i}`).values = [line]; });
scope.getRange(`A${scopeLast + 2}:A${scopeLast + 1 + notes.length}`).format.font = { name: 'Arial', size: 10, color: '#475569' };
wb.recalculate();
const check = await wb.inspect({ kind: 'region', sheetId: sheet.name, range: `A5:${endCol}${Math.min(8, lastRow)}`, maxChars: 1500, tableMaxRows: 3, tableMaxCols: 22, tableMaxCellChars: 45 });
console.log(check.ndjson);
const outDir = path.join(taskDir, 'delivery');
await fs.mkdir(outDir, { recursive: true });
const book = await SpreadsheetFile.exportXlsx(wb);
const out = path.join(outDir, request.workbook_name || '分省医疗数字化采购.xlsx');
const temp = path.join(outDir, 'workbook-building.xlsx');
await book.save(temp);
// The delivery workbook is often open in Excel/WPS while a rerun finishes;
// a locked target must not fail the whole workflow.
const place = async (from, to, tries = 4) => {
  for (let i = 0; i < tries; i++) {
    try {
      await fs.rename(from, to);
      return to;
    } catch (error) {
      if (i === tries - 1) {
        const stamp = new Date().toISOString().replace(/[-:]/g, '').slice(0, 13);
        const alt = to.replace(/\.xlsx$/i, '') + '_' + stamp + '.xlsx';
        await fs.rename(from, alt);
        console.warn(JSON.stringify({ status: 'target_locked', target: to, wrote: alt, reason: String(error.code || error.message) }));
        return alt;
      }
      await new Promise(resolve => setTimeout(resolve, 1200 * (i + 1)));
    }
  }
};
const written = await place(temp, out);
if (process.env.TENDER_RENDER_QA === '1') {
  for (const [name, range] of [['main-left', 'A2:K8'], ['main-right', `L5:${endCol}8`]]) {
    const pic = await wb.render({ sheetName: sheet.name, range, scale: 1, format: 'png' });
    await fs.writeFile(path.join(outDir, name + '.png'), new Uint8Array(await pic.arrayBuffer()));
  }
  const pic = await wb.render({ sheetName: scope.name, range: `A2:F${scopeLast + 2}`, scale: 1, format: 'png' });
  await fs.writeFile(path.join(outDir, 'coverage.png'), new Uint8Array(await pic.arrayBuffer()));
}
console.log(JSON.stringify({ status: 'exported', rows: rows.length, columns: headers.length, regions: scopeRows.length, file: written }));
