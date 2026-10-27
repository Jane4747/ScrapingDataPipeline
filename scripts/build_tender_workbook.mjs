import fs from 'node:fs/promises';
import path from 'node:path';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
// Optional runtime: @oai/artifact-tool. This script does not collect data.
const [bundleDir, previewDir]=process.argv.slice(2);
if(!bundleDir || !previewDir) throw new Error('Usage: node scripts/build_tender_workbook.mjs <bundle-dir> <new-preview-dir>');
const out=path.resolve(bundleDir);
const work=path.resolve(previewDir);
const exists=async p=>{try{await fs.access(p);return true;}catch(e){if(e.code==='ENOENT')return false;throw e;}};
if(await exists(work)) throw new Error('Preview directory already exists; choose a new directory');
const read=async f=>JSON.parse(await fs.readFile(path.join(out,f),'utf8'));
const [records,candidates,search,roster,scope]=await Promise.all(['records.validated.json','candidate_notices.json','hospital_search_log.json','hospital_roster.json','collection_scope.json'].map(read));
const bookName=scope.workbook_filename||'北京一级医院数智化招标中标信息_2024年至今.xlsx';
if(path.basename(bookName)!==bookName || !bookName.endsWith('.xlsx')) throw new Error('Invalid workbook filename');
const file=path.join(out,bookName);
if(await exists(file)) throw new Error('Workbook already exists; preserve it and use a new bundle directory');
await fs.mkdir(work,{recursive:true});
const channelMode=scope.round_type==='channel_supplement';
const byId=new Map(roster.map(h=>[h.id,h]));
const wb=Workbook.create();
const links=[];
let sheetCount=0;
function setup(name,title,notes,headers,rows,widths,height=72){
 const sh=wb.worksheets.add(name);sh.showGridLines=false;sh.tabColor='#244C73';
 sh.getRange('A2').values=[[title]];sh.getRange('A2').format.font={name:'Microsoft YaHei',size:16,bold:true,color:'#193C5E'};
 for(let i=0;i<notes.length;i++){sh.getRangeByIndexes(3+i,0,1,1).values=[[notes[i]]];sh.getRangeByIndexes(3+i,0,1,1).format.font={name:'Microsoft YaHei',size:10,color:'#526475'};}
 sh.getRange('A2:A6').format.wrapText=false;
 const n=rows.length||1,cols=headers.length;
 sh.getRangeByIndexes(6,0,1,cols).values=[headers];sh.getRangeByIndexes(7,0,n,cols).values=rows.length?rows:[Array(cols).fill(null)];
 const range=sh.getRangeByIndexes(6,0,n+1,cols);sh.tables.add(range,true,'TenderTable'+(++sheetCount));
 range.format.font={name:'Microsoft YaHei',size:10,color:'#243748'};range.format.verticalAlignment='center';range.format.wrapText=true;
 sh.getRangeByIndexes(7,0,n,cols).format.fill='#FFFFFF';sh.getRangeByIndexes(7,0,n,cols).format.rowHeight=height;
 for(let i=0;i<n;i++)if(i%2===1)sh.getRangeByIndexes(7+i,0,1,cols).format.fill='#F0F4F8';
 const hdr=sh.getRangeByIndexes(6,0,1,cols);hdr.format={fill:'#244C73',font:{name:'Microsoft YaHei',size:11,bold:true,color:'#FFFFFF'},wrapText:true,horizontalAlignment:'center',verticalAlignment:'center',rowHeight:40};
 widths.forEach((w,i)=>sh.getRangeByIndexes(0,i,n+7,1).format.columnWidthPx=w);
 rows.forEach((row,i)=>{
  const lines=Math.max(...row.map((v,j)=>String(v??'').split('\n').reduce((sum,t)=>sum+Math.max(1,Math.ceil(t.length/Math.max(5,Math.floor(widths[j]/12)))),0)));
  sh.getRangeByIndexes(i+7,0,1,cols).format.rowHeight=Math.min(409.5,Math.max(height,lines*15+16));
 });
 sh.freezePanes.freezeRows(7);sh.freezePanes.freezeColumns(1);
 return sh;
}
const mainHeaders=['项目名称','产品','招标单位','客户标签','中标单位','中标金额（万元）','来源与追溯'];
const mainRows=records.map((r,i)=>{
 const trace=[r.url,`${r.date}｜${r.announcement_type}`,`对应医院：${r.hospital_name}`,r.project_number?`项目编号：${r.project_number}`:'',r.amount_quote||'',(r.source_note||'').replaceAll('amount_wan','中标金额'),...(r.additional_urls||[]).map(u=>'关联来源：'+u),r.evidence_path?`留存证据：${r.evidence_path}`:''].filter(Boolean).join('\n');
 links.push({sheet:1,cell:'G'+(i+8),url:r.url});
 return [r.project_name,r.product||'',r.purchaser||'',r.customer_label,r.winner||'未披露',r.amount_wan??null,trace];
});
const main=setup('招标中标信息','北京一级医院数智化招标中标信息'+(channelMode?'｜渠道补查版':''),[
 `范围：提供名单所列${roster.length}家一级医院；公告日期${scope.since}至${scope.until}。`,
 `累计整理${records.length}条公告记录。每行一份公告中的一个采购包，招标与中标公告分别留存。`,
 '客户标签取自医院名单。中标金额空白表示本公告未披露或尚非成交阶段；转载来源在末列标明。'
],mainHeaders,mainRows,[345,310,250,185,230,155,650],174);
main.getRangeByIndexes(7,5,Math.max(records.length,1),1).setNumberFormat('#,##0.00####');
mainRows.forEach((r,i)=>{
 const lines=Math.max(...r.map((v,j)=>String(v??'').split('\n').reduce((n,t)=>n+Math.max(1,Math.ceil(t.length/[25,23,18,13,16,11,46][j])),0)));
 main.getRangeByIndexes(i+7,0,1,7).format.rowHeight=Math.min(409.5,Math.max(110,lines*15+16));
});
const candidateRows=candidates.map((r,i)=>{
 links.push({sheet:2,cell:'E'+(i+8),url:r.url});
 return [r.hospital_name||byId.get(Number(r.hospital_id))?.name||'',r.project_name||r.title||'',r.date||'待核',r.status||'待核',r.url||'',r.reason||r.source_note||r.note||'',r.evidence_path||''];
});
setup('待核与排除','待核线索及范围外记录',[
 '本表不计入已整理公告。未取得正文、医院用途不明或日期不符合范围的线索在此保留。',
 '金额、供应商和对象关系未核对前，不据列表页或候选人公示填写正式中标字段。'
],['对应医院','候选项目名称','公告日期/待核日期','处理状态','公告或线索网址','待核或排除原因','留存证据'],candidateRows,[250,350,140,170,590,600,280],116);
const searchRows=search.sort((a,b)=>Number(a.hospital_id)-Number(b.hospital_id)).map(r=>{
 const h=byId.get(Number(r.hospital_id));const found=records.filter(x=>(x.hospital_ids||[x.hospital_id]).map(Number).includes(h.id));
 let queries=r.queries??r.query??[];if(!Array.isArray(queries))queries=[queries];
 const qs=queries.map(q=>typeof q==='string'?q:(q.q||q.query||JSON.stringify(q))).join('\n');
 return [h.id,h.name,h.level+'；'+h.category,h.district,(r.query_count?`实际查询${r.query_count}条\n`:'')+qs,channelMode?(r.status||'已检索'):(found.length?`已整理${found.length}条公告；`+r.status:(r.status||'已检索')),Array.isArray(r.search_evidence)?r.search_evidence.join('\n'):(r.search_evidence||r.evidence_path||''),h.source_sheet+'!C'+h.source_row];
});
setup('逐院检索记录',(channelMode?'上轮':'')+roster.length+'家一级医院逐院检索记录',[
 '医院名称、等级、类别和区域沿用用户提供名单，未重新评定医院等级。',
 '未检索到符合条件的公告，不代表医院没有采购项目；渠道未公开、索引遗漏及访问受限均可能造成缺口。',
 channelMode?`保留上轮${scope.query_count}条逐院查询；本轮平台补查另列“本轮渠道补查”表。`:(scope.query_count?`本轮逐院实际执行${scope.query_count}条查询，每家至少${scope.minimum_queries_per_hospital}条。补查官网栏目和原文另留证据。`:'参考：北京雄安医院清单.xlsx，“03-一级医院”和“09-招标渠道对照”；查询返回原文存于同目录evidence文件夹。')
],['清单序号','医院名称','名单等级与类别','区域','已执行检索词',channelMode?'上轮检索情况':'本轮检索情况','检索证据文件','名单来源位置'],searchRows,[85,335,175,110,650,410,330,180],92);
if(channelMode){
 const channelLogs=await read('channel_search_log.json');
 const channelRows=channelLogs.flatMap(r=>(r.queries||[]).map(q=>[
  (r.hospital_ids||[]).map(i=>byId.get(Number(i))?.name||String(i)).join('、')||'渠道入口校核（不计医院覆盖）',
  r.channel||r.platform||({central:'中央政府采购网、中国政府采购网及采购人官网',beijing:'北京市政府采购网及公共资源交易平台',enterprise:'集团采购及采购代理渠道',root:'高校与平台入口补查'}[r.group])||'',q,r.status||'',
  [...(r.evidence_files||[]).slice(0,5),(r.evidence_files||[]).length>5?`另${r.evidence_files.length-5}份证据，完整列表见channel_search_log.json`:''].filter(Boolean).join('\n')
 ]));
 setup('本轮渠道补查','本轮平台定向补查记录',[
  `范围仍为原${roster.length}家；本轮重点补查${scope.channel_searched_hospitals}家，实际保存并去重的查询${scope.channel_query_count}条。`,
  '表内保留跨院查询的各院关联，因此展示行数可能大于去重查询数；未表示再次全名单穷尽抓取。',
  '渠道含政府采购、公共资源交易、集团及采购人官网；举办主体标签仅作检索线索。'
 ],['对应医院','定向渠道','已执行查询','本轮核对结果','留存证据'],channelRows,[330,260,650,640,520],90);
 const platforms=await read('platform_channels.json');
 const platformRows=platforms.map((r,i)=>{links.push({sheet:5,cell:'B'+(i+8),url:r.url});return [r.name,r.url,r.use,r.status,r.note,r.evidence];});
 setup('平台入口与口径','平台入口及采集口径核对',[
  '依据用户渠道表及本轮公开页面核对；原表对一级医院的举办主体多为规则推断，不能据此限制检索。',
  '中标金额只取确定结果；采购预算、投标报价、候选排名及拟定供应商均不直接填入中标字段。'
 ],['平台','入口网址','检索用途','本次核对情况','取数注意事项','依据与证据'],platformRows,[260,520,550,550,650,400],120);
}
wb.recalculate();
console.log((await wb.inspect({kind:'table',range:'招标中标信息!A7:G11',include:'values',tableMaxRows:5,tableMaxCols:7,tableMaxCellChars:90,maxChars:3500})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!',options:{useRegex:true,maxResults:20},maxChars:700})).ndjson);
await (await SpreadsheetFile.exportXlsx(wb)).save(file);
for(const [sheetName,range,label] of [['招标中标信息','A1:G'+Math.min(7+records.length,11),'results'],['招标中标信息',`A${Math.max(8,records.length+5)}:G${records.length+7}`,'results-bottom'],['待核与排除','A1:G10','candidates'],['逐院检索记录','A1:H10','search']]){
 const img=await wb.render({sheetName,range,scale:1,format:'png'});await fs.writeFile(path.join(work,label+'.png'),new Uint8Array(await img.arrayBuffer()));
}
if(channelMode)for(const [sheetName,range,label] of [['本轮渠道补查','A1:E10','channels'],['平台入口与口径','A1:F10','platforms'],['招标中标信息','A12:G14','results-shared']]){
 const img=await wb.render({sheetName,range,scale:1,format:'png'});await fs.writeFile(path.join(work,label+'.png'),new Uint8Array(await img.arrayBuffer()));
}
await fs.writeFile(path.join(work,'hyperlinks.json'),JSON.stringify(links));
console.log(JSON.stringify({file,records:records.length,candidates:candidates.length,roster:searchRows.length}));
