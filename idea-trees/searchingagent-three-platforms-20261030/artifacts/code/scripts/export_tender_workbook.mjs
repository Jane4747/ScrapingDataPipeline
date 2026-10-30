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
const col = n => { let value=''; for(let x=n;x>0;x=Math.floor((x-1)/26))value=String.fromCharCode(65+(x-1)%26)+value; return value; };
const endCol=col(headers.length);
const literal = value => typeof value==='string' && /^[=+@]/.test(value) ? "'"+value : value;
const matrix = rows.map(row => headers.map(key => {
  let value = row[key] ?? null;
  if (key==='时间') return /^\d{4}-\d{2}-\d{2}$/.test(value ?? '') ? new Date(value+'T00:00:00Z') : null;
  if (key==='中标金额（万元）') return typeof value==='number' && Number.isFinite(value) ? value : null;
  if(typeof value==='string' && value.length>32700) value=value.slice(0,32620)+'\n内容超过单元格长度，完整内容请查看本行原文网址。';
  return literal(value);
}));
sheet.getRange('A2').values=[['医疗数字化采购公告']];
sheet.getRange('A2').format.font={name:'Arial',size:14,bold:true};
sheet.getRange('A3').values=[[`${request.start} 至 ${request.end}；当前保留 ${rows.length} 条公告；采集状态：${summary.status}`]];
sheet.getRange('A3').format.font={name:'Arial',size:10,italic:true,color:'#475569'};
sheet.getRange(`A5:${endCol}5`).values=[headers];
if(matrix.length) sheet.getRange(`A6:${endCol}${matrix.length+5}`).values=matrix;
const used=sheet.getRange(`A5:${endCol}${Math.max(6,matrix.length+5)}`);
used.format.font={name:'Arial',size:10,color:'#172B4D'};
used.format.rowHeight=65;
used.format.wrapText=true;
used.format.verticalAlignment='top';
sheet.getRange(`A5:${endCol}5`).format={fill:'#1F4E78',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:42,wrapText:true,horizontalAlignment:'center',verticalAlignment:'center'};
const widths=[13,54,38,38,22,38,18,21,24,34,50,24,16,32,30,58,45,78,78,28,55,55];
widths.forEach((width,i)=>{sheet.getRange(`${col(i+1)}5:${col(i+1)}${Math.max(6,matrix.length+5)}`).format.columnWidth=width;});
if(matrix.length){
 sheet.getRange(`A6:A${matrix.length+5}`).setNumberFormat('yyyy-mm-dd');
 sheet.getRange(`H6:H${matrix.length+5}`).setNumberFormat('#,##0.0000');
 sheet.getRange(`H6:H${matrix.length+5}`).format.horizontalAlignment='right';
 sheet.tables.add(`A5:${endCol}${matrix.length+5}`,true,'ProcurementNotices');
}
sheet.freezePanes.freezeRows(5);
sheet.freezePanes.freezeColumns(2);
const scope=wb.worksheets.add('采集范围');
scope.showGridLines=false;
scope.getRange('A2').values=[['采集范围与覆盖状态']];
scope.getRange('A2').format.font={name:'Arial',size:14,bold:true};
scope.getRange('A4:E4').values=[['来源平台','状态','公告记录','未完成检索窗口','说明']];
const states={completed:'已完成声明的执行范围',running:'采集中',queued:'等待执行',partial:'覆盖不完整',failed:'执行失败'};
const stateRows=summary.sources.map(s=>[s.source_name,states[s.status]??s.status,s.records??0,s.pending_search_windows??null,s.stop_reason??s.error??s.message??'']);
scope.getRange(`A5:E${4+stateRows.length}`).values=stateRows;
scope.getRange('A4:E7').format.font={name:'Arial',size:10};
scope.getRange('A4:E4').format={fill:'#1F4E78',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},horizontalAlignment:'center',rowHeight:25};
scope.getRange('A5:E7').format.rowHeight=48;
scope.getRange('A5:E7').format.wrapText=true;
[32,28,18,24,100].forEach((w,i)=>scope.getRange(`${col(i+1)}4:${col(i+1)}9`).format.columnWidth=w);
scope.getRange('A9').values=[['时间按公告发布日期；未提取到的资格、专家和金额留空，具体缺口见主表。']];
scope.getRange('A10').values=[['资格要求仅在项目编号和采购人均一致、内容唯一时关联，出处保留在主表。']];
scope.getRange('A11').values=[['公告记录不等于独立项目；同名公告不自动归并，规则标签不代表事实核验。']];
wb.recalculate();
const check=await wb.inspect({kind:'region',sheetId:sheet.name,range:`A5:${endCol}${Math.min(8,matrix.length+5)}`,maxChars:1800,tableMaxRows:3,tableMaxCols:22,tableMaxCellChars:55});
console.log(check.ndjson);
const outDir=path.join(taskDir,'delivery');
await fs.mkdir(outDir,{recursive:true});
const book=await SpreadsheetFile.exportXlsx(wb);
const out=path.join(outDir,'三平台医疗数字化采购_2024年至今.xlsx');
const temp=path.join(outDir,'workbook-building.xlsx');
await book.save(temp);
await fs.rename(temp,out);
if(process.env.TENDER_RENDER_QA==='1'){
 for(const [name,range] of [['main-left','A2:K8'],['main-right',`L5:${endCol}8`]]){
  const pic=await wb.render({sheetName:sheet.name,range,scale:1,format:'png'});
  await fs.writeFile(path.join(outDir,name+'.png'),new Uint8Array(await pic.arrayBuffer()));
 }
 const pic=await wb.render({sheetName:scope.name,range:'A2:E11',scale:1,format:'png'});
 await fs.writeFile(path.join(outDir,'coverage.png'),new Uint8Array(await pic.arrayBuffer()));
}
console.log(JSON.stringify({status:'exported',rows:rows.length,columns:headers.length,file:out}));
