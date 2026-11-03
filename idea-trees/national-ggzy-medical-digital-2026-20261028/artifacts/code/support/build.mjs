import fs from 'node:fs/promises';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const runDir = 'E:/CAICTBigData/coding/outputs/national-ggzy-medical-digital-2026-20261028/collection-v2';
const outDir = 'E:/CAICTBigData/coding/outputs/01a17c0d-96d1-79a3-9665-f4fc255ee0c7';
const outPath = path.join(outDir,'全国公共资源交易平台_医疗数字化_2026.xlsx');
const state = JSON.parse(await fs.readFile(path.join(runDir,'state.json'),'utf8'));
const phaseStats=[{title:'政府采购',status:state.status,updated_at:state.updated_at}];
let job=null;
try {job=JSON.parse(await fs.readFile(path.join(path.dirname(runDir),'job.json'),'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;}
for(const name of ['collection-engineering']) {
  try {
    const next=JSON.parse(await fs.readFile(path.join(path.dirname(runDir),name,'state.json'),'utf8'));
    phaseStats.push({title:'工程建设',status:next.status,updated_at:next.updated_at});
    state.pending.push(...next.pending.map(x=>({...x,business:next.config.business})));
    state.completed_windows.push(...next.completed_windows.map(x=>({...x,business:next.config.business})));
    state.failures.push(...next.failures);
    Object.assign(state.notices,next.notices);
    Object.assign(state.records,next.records);
  } catch(e) {if(e.code!=='ENOENT')throw e;}
}
const grouped = new Map();
for (const [id,record] of Object.entries(state.records)) {
  if (state.notices[id]?._scope_rejected) continue;
  if (!(record['公告日期']>=state.config.start && record['公告日期']<=state.config.end)) continue;
  const lot=(record._source?.title??'').match(/采购包\s*[（(]?[A-Za-z0-9一二三四五六七八九十]+|标项[一二三四五六七八九十\d]+|第[一二三四五六七八九十\d]+包|[A-Z]包/)?.[0]??'';
  const moneySignature=record['中标金额（万元）']!==null?record['中标金额（万元）']:(record._award_rows?.length>1&&record._award_rows.every(a=>a.amount_wan!==null)?JSON.stringify(record._award_rows.map(a=>[a.supplier,a.amount_wan]).sort()):null);
  const consistent=record['项目编号']&&record['招标单位']&&record['中标单位']&&moneySignature!==null;
  const key = consistent?JSON.stringify([record['项目编号'],record['项目名称'],record['公告日期'],record['公告类型'],record['招标单位'],record['中标单位'],moneySignature,lot]):(record._body_hash ? `${record._body_hash}|${record['公告日期']}|${record['公告类型']}` : record['相关网页']);
  if (!grouped.has(key)) grouped.set(key,{...record,_urls:[record['相关网页']],_ids:[id],evidence_ids:[id]});
  else {
    const r=grouped.get(key);r._urls.push(record['相关网页']);r._ids.push(id);r.evidence_ids.push(id);
  }
}
const rows=[...grouped.values()].sort((a,b)=>b['公告日期'].localeCompare(a['公告日期'])||a['项目名称'].localeCompare(b['项目名称'],'zh-CN'));
const columns=['项目名称','产品','招标单位','客户标签','中标单位','运营商类型','中标金额（万元）','场景','相关网页','公告日期','公告类型','省份','项目编号','中标金额原文','信息缺口','标签依据'];
const isAward=r=>r._is_final_award??(r._source?.informationType==='0202'||/中标|成交|结果/.test(r['公告类型']??''));
const awardRows=rows.filter(isAward), tenderRows=rows.filter(r=>!isAward(r));
const carrier=s=>/中国移动|中移/.test(s)?'中国移动':/中国电信|中电信|天翼/.test(s)?'中国电信':/中国联通|联通/.test(s)?'中国联通':/中国广电|广电网络/.test(s)?'中国广电':'非运营商';
const lotRows=awardRows.flatMap(r=>(r._award_rows?.length>1?r._award_rows:[]).map((a,i)=>({...r,'产品':'','中标单位':a.supplier,'运营商类型':carrier(a.supplier),'中标金额（万元）':a.amount_wan,'中标金额原文':a.amount_raw,'信息缺口':`中标结果表第${i+1}条，仅为分项金额；产品未细分至本行，请对照主表及原文`,_products:[]})));
const workbook=Workbook.create();
const font='Arial';
const dataUpdatedAt=phaseStats.map(x=>x.updated_at).sort().at(-1);
const stamp=new Date(dataUpdatedAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
const shortProducts = r => {
  const all=r._products?.length?r._products:(r['产品']??'').split('、').filter(Boolean);
  return all.length>8?all.slice(0,8).join('、')+`等${all.length}项，详见原文`:all.join('、');
};

function makeTable(name,records,tableName,note=null) {
  const sheet=workbook.worksheets.add(name);
  const last=Math.max(6,records.length+5);
  sheet.showGridLines=false;
  sheet.tabColor='#24476B';
  sheet.getRange(`A2:P${last}`).format.font={name:font,size:10,color:'#222C38'};
  sheet.getRange('A2').values=[[`全国公共资源交易平台医疗数字化${name}`]];
  sheet.getRange('A2').format.font={name:font,size:15,bold:true,color:'#183858'};
  sheet.getRange('A3').values=[[`2026-01-01至2026-10-28；更新于${stamp}。当前${records.length}条${name==='中标分项'?'中标分项':'公告'}，分批结果及覆盖情况见末表。`]];
  sheet.getRange('A4').values=[[note??'金额单位：万元。空白为未披露或未可靠提取；产品列列示主要标的，完整清单见原文。客户、运营商和场景为规则标签。']];
  sheet.getRange('A3:P4').format.font={name:font,size:10,color:'#5C6775'};
  sheet.getRange('A5:P5').values=[columns];
  if(records.length) {
    const matrix=records.map(r=>columns.map(c=>c==='产品'?shortProducts(r):c==='公告日期'?new Date(`${r[c]}T00:00:00Z`):c==='相关网页'?'查看公告原文':(r[c]??null)));
    sheet.getRange(`A6:P${last}`).values=matrix;
    sheet.getRange(`A6:P${last}`).format.wrapText=true;
    sheet.getRange(`A6:P${last}`).format.verticalAlignment='top';
    sheet.getRange(`G6:G${last}`).setNumberFormat('#,##0.0000');
    sheet.getRange(`J6:J${last}`).setNumberFormat('yyyy-mm-dd');
    sheet.getRange(`I6:I${last}`).format.font={name:font,size:10,color:'#245A9C'};
    const table=sheet.tables.add(`A5:P${last}`,true,tableName);
    table.showFilterButton=true;
  }
  sheet.getRange('A5:P5').format={fill:'#24476B',font:{name:font,size:10,bold:true,color:'#FFFFFF'},rowHeight:30,verticalAlignment:'center',wrapText:true};
  const widths=[50,48,34,22,36,18,18,24,24,15,18,20,30,36,42,46];
  widths.forEach((width,i)=>sheet.getRangeByIndexes(4,i,last-4,1).format.columnWidth=width);
  for(let i=0;i<records.length;i++) {
    const r=records[i];
    const display=[r['项目名称'],shortProducts(r),r['中标单位'],r['信息缺口']];
    const chars=Math.max(...display.map(s=>(s??'').length));
    sheet.getRangeByIndexes(i+5,0,1,16).format.rowHeight=Math.max(74,Math.min(200,Math.ceil(chars/24)*14+12));
  }
  sheet.freezePanes.freezeRows(5);
  sheet.freezePanes.freezeColumns(1);
  return sheet;
}
makeTable('中标成交',awardRows,'NationalMedicalAward');
if(lotRows.length) makeTable('中标分项',lotRows,'NationalMedicalAwardLots','本表为主表多标包公告的结果表分项，金额单位万元；不与主表金额相加。产品未按分项匹配，留空供对照原文。');
if(tenderRows.length) makeTable('采购线索',tenderRows,'NationalMedicalTender');

const coverage=workbook.worksheets.add('覆盖与缺口');
coverage.showGridLines=false;
coverage.getRange('A2:I18').format.font={name:font,size:10,color:'#222C38'};
coverage.getRange('A2').values=[['检索范围与未完成项']];
coverage.getRange('A2').format.font={name:font,size:15,bold:true,color:'#183858'};
coverage.getRange('A3').values=[['政府采购与工程建设分批采集；不同来源、栏目及窗口的实际完成情况见下表，不代表全国平台全量覆盖。']];
coverage.getRange('A4').values=[['重复发布按正文或项目编号、日期、标包、供应商及金额一致性合并，保留各条证据；不同标包不合并。']];
coverage.getRange('A6:B13').values=[['采集状态',job?.status==='running'?'采集中':job?.status==='completed_selected_scope'?'所选窗口已处理':'部分完成'],['范围开始',new Date(state.config.start+'T00:00:00Z')],['范围结束',new Date(state.config.end+'T00:00:00Z')],['已解析公告（去重）',rows.length],['其中中标成交',awardRows.length],['待检索/翻页的窗口',state.pending.length],['历史失败记录',state.failures.length],['尚未恢复的失败',state.failures.filter(f=>!f.resolved_at&&!f.excluded_from_active_scope).length]];
coverage.getRange('B7:B8').setNumberFormat('yyyy-mm-dd');
coverage.getRange('A14').values=[['下表逐项列出已完成窗口与尚未完成窗口，空白条数表示尚无可用统计。']];
coverage.getRange('A15').values=[[`采集队列：${(job?.phases??[]).map(p=>p.title+' '+({queued:'待启动',running:'采集中',partial:'已有检查点',completed:'所选窗口已处理'}[p.status]??p.status)).join('；')}。数据更新于${stamp}。`]];
const names={'1':'省平台','2':'央企招投标','3':'财政部','4':'自然资源部','6':'商务部'},types={'0202':'中标成交','0201':'采购公告','0104':'工程结果公示','0101':'工程招标/资审'};
const crows=[...state.completed_windows.map(x=>({...x,_status:'已完成'})),...state.pending.map(x=>({...x,_status:x.page>1?'翻页未完成':'待检索'}))].map(x=>[names[x.source]??x.source,types[x.stage]??x.stage,x.word,new Date(x.start+'T00:00:00Z'),new Date(x.end+'T00:00:00Z'),x._status,x._status==='已完成'?x.page:Math.max(0,x.page-1),x.reported_total??null]);
coverage.getRange('A16:H16').values=[['数据来源','公告范围','检索词','窗口开始','窗口结束','状态','已取页数','报告条数']];
if(crows.length) {
  coverage.getRange(`A17:H${16+crows.length}`).values=crows;
  coverage.getRange(`D17:E${16+crows.length}`).setNumberFormat('yyyy-mm-dd');
  coverage.tables.add(`A16:H${16+crows.length}`,true,'NationalMedicalCoverage').showFilterButton=true;
}
coverage.getRange('A16:H16').format={fill:'#24476B',font:{name:font,size:10,bold:true,color:'#FFFFFF'},rowHeight:28};
coverage.getRange(`A17:H${16+crows.length}`).format.rowHeight=24;
[18,18,18,17,17,22,16,18].forEach((w,i)=>coverage.getRangeByIndexes(15,i,crows.length+1,1).format.columnWidth=w);
coverage.getRange('A6:A12').format.columnWidth=30;
coverage.freezePanes.freezeRows(16);

workbook.recalculate();
await fs.mkdir(outDir,{recursive:true});
const preview=await workbook.render({sheetName:'中标成交',range:'A1:I10',scale:1.2,format:'png'});
await fs.writeFile(path.join(outDir,'ggzy-main-preview.png'),new Uint8Array(await preview.arrayBuffer()));
const coveragePreview=await workbook.render({sheetName:'覆盖与缺口',range:'A1:H21',scale:1.2,format:'png'});
await fs.writeFile(path.join(outDir,'ggzy-coverage-preview.png'),new Uint8Array(await coveragePreview.arrayBuffer()));
for(const name of ['中标分项','采购线索']) {
  if((name==='中标分项'&&lotRows.length)||(name==='采购线索'&&tenderRows.length)) {
    const img=await workbook.render({sheetName:name,range:'A1:I9',scale:1.2,format:'png'});
    await fs.writeFile(path.join(outDir,name+'-preview.png'),new Uint8Array(await img.arrayBuffer()));
  }
}
const inspected=await workbook.inspect({kind:'region',sheetId:'中标成交',range:'A5:P8',maxChars:2500,tableMaxRows:4,tableMaxCols:16});
await fs.writeFile(path.join(outDir,'workbook-inspection.json'),JSON.stringify(inspected));
const errors=await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:100},summary:'final formula error scan'});
await fs.writeFile(path.join(outDir,'formula-scan.json'),JSON.stringify(errors));
const xlsx=await SpreadsheetFile.exportXlsx(workbook);
const tempPath=outPath.replace('.xlsx','.building.xlsx');
await xlsx.save(tempPath);
const linkMap={};
for(const [name,records] of [['中标成交',awardRows],['中标分项',lotRows],['采购线索',tenderRows]]) {
  if(records.length)linkMap[name]=records.map((r,i)=>({cell:`I${i+6}`,url:r._urls[0]}));
}
const linkMapPath=path.join(outDir,'native-link-map.json');
await fs.writeFile(linkMapPath,JSON.stringify(linkMap));
// HYPERLINK is documented but returns an unimplemented placeholder in this
// runtime. Add only the missing native hyperlink feature to the exported ZIP.
console.log(execFileSync('C:/Users/Jane/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',[path.join(path.dirname(fileURLToPath(import.meta.url)),'native_links.py'),tempPath,outPath,linkMapPath],{encoding:'utf8',windowsHide:true}).trim());
await fs.unlink(tempPath);
await fs.writeFile(path.join(outDir,'delivery-dataset.json'),JSON.stringify({updated_at:dataUpdatedAt,source_record_count:Object.keys(state.records).length,deduplicated_notice_count:rows.length,award_records:awardRows.length,tender_records:tenderRows.length,award_lot_rows:lotRows.length,scope_status:'partial',rows,lotRows},null,2));
console.log(JSON.stringify({workbook:outPath,rows:rows.length,awards:awardRows.length,lot_rows:lotRows.length,tenders:tenderRows.length,pending_windows:state.pending.length}));
