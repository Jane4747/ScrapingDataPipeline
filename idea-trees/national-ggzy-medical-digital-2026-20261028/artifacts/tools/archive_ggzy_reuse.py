"""Archive the verified GGZY case and its reusable components; never read secrets."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
from datetime import datetime
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

p=argparse.ArgumentParser()
p.add_argument('--repo',default='E:/CAICTBigData/coding')
p.add_argument('--tree-id',default='national-ggzy-medical-digital-2026-20261028')
a=p.parse_args()
repo=Path(a.repo).resolve()
tree_dir=repo/'idea-trees'/a.tree_id
root=repo/'outputs/national-ggzy-medical-digital-2026-20261028'
delivery=repo/'outputs/01a17c0d-96d1-79a3-9665-f4fc255ee0c7'
stamp=datetime.now().astimezone().replace(microsecond=0).isoformat()
key=datetime.now().strftime('%Y%m%dT%H%M%S')
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def textfile(name,text):
    target=tree_dir/name
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(text.strip()+'\n',encoding='utf-8')
    return target
tree=read(tree_dir/'tree.json')
history=tree_dir/'history'/key
history.mkdir(parents=True,exist_ok=False)
for name in ['tree.json','tree.md']:shutil.copy2(tree_dir/name,history/name)
job=read(root/'job.json')
state=read(root/'collection-v2/state.json')
dataset=read(delivery/'delivery-dataset.json')
snapshot={'captured_at':stamp,'job':job,'government_progress':read(root/'collection-v2/progress.json'),'successful_workbook':{k:dataset[k] for k in ['updated_at','source_record_count','deduplicated_notice_count','award_records','award_lot_rows','tender_records','scope_status']},'warning':'检查点计数与最后成功导出的Excel计数各有时间戳，不能混用。','workbook_lock_file_present':(delivery/'~$全国公共资源交易平台_医疗数字化_2026.xlsx').exists()}
write(tree_dir/'PROGRESS-SNAPSHOT.json',snapshot)
versions={}
for name in ['playwright','beautifulsoup4','requests','truststore','httpx','lxml']:
    try:versions[name]=metadata.version(name)
    except metadata.PackageNotFoundError:versions[name]=None
node=Path('C:/Users/Jane/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
artifact=read(delivery/'support/node_modules/@oai/artifact-tool/package.json')
chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
dependencies={'captured_at':stamp,'python':sys.version,'python_executable':sys.executable,'collector_required_packages':{k:versions[k] for k in ['playwright','beautifulsoup4','requests','truststore']},'installed_but_not_required_by_collector_core':{k:versions[k] for k in ['httpx','lxml']},'node_version':subprocess.check_output([str(node),'--version'],text=True).strip(),'artifact_tool_version':artifact['version'],'chrome_executable':str(chrome),'chrome_observed_version':'149.0.7827.197','windows_curl_observed_version':'8.13.0, Schannel','dependencies_bundled':False,'notes':['版本是本机验证快照，不是最新版推荐。','只归档自己编写/仓库共享代码，不打包解释器、node_modules、浏览器、虚拟环境、真实环境配置、密钥、Cookie或用户浏览器档案。']}
write(tree_dir/'DEPENDENCIES.json',dependencies)
entries=[]
copies=[
('pipeline/__init__.py','artifacts/code/pipeline/__init__.py'),
('pipeline/research/__init__.py','artifacts/code/pipeline/research/__init__.py'),
('pipeline/research/national_ggzy.py','artifacts/code/pipeline/research/national_ggzy.py'),
('pipeline/research/zycg.py','artifacts/code/pipeline/research/zycg.py'),
('pipeline/research/bid_common.py','artifacts/code/pipeline/research/bid_common.py'),
('pipeline/research/fetch.py','artifacts/code/pipeline/research/fetch.py'),
('pipeline/research/tenders.py','artifacts/code/pipeline/research/tenders.py'),
('pipeline/research/config.py','artifacts/code/pipeline/research/config.py'),
('scripts/__init__.py','artifacts/code/scripts/__init__.py'),
('scripts/thirdparty_goverment_spider/__init__.py','artifacts/code/scripts/thirdparty_goverment_spider/__init__.py'),
('scripts/thirdparty_goverment_spider/site_fetch.py','artifacts/code/scripts/thirdparty_goverment_spider/site_fetch.py'),
('tests/test_national_ggzy_collector.py','artifacts/code/tests/test_national_ggzy_collector.py'),
('scripts/idea_tree_writer.py','artifacts/tools/idea_tree_writer.py'),
]
for name in ['build.mjs','native_links.py','run_collection.mjs']:
    copies.append((str((delivery/'support'/name).relative_to(repo)),'artifacts/code/support/'+name))
for source_rel,target_rel in copies:
    source=repo/source_rel
    if not source.exists():continue
    target=tree_dir/target_rel
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,target)
    assert sha(source)==sha(target)
    entries.append({'path':target_rel,'source':str(source),'sha256':sha(target),'bytes':target.stat().st_size,'kind':'code'})
archiver_target=tree_dir/'artifacts/tools/archive_ggzy_reuse.py'
if Path(__file__).resolve()!=archiver_target.resolve():shutil.copy2(__file__,archiver_target)
requirements=textfile('artifacts/code/requirements-collector.txt','\n'.join(f'{k}=={v}' for k,v in dependencies['collector_required_packages'].items()))
sample_refs=[]
for token in ['龙岗中心医院扩建工程信息化项目','江苏省人民医院资产管理信息系统','南宁市第四人民医院机房建设']:
    selected=next(((i,r) for i,r in state['records'].items() if token in r['项目名称']),None)
    if not selected:continue
    i,r=selected
    base=tree_dir/'artifacts/evidence'/i
    base.mkdir(parents=True,exist_ok=True)
    for src,dest in [(Path(r['_evidence_html']),base/'body.html'),(root/'collection-v2/texts'/(i+'.txt'),base/'text.txt')]:
        if src.exists():
            shutil.copy2(src,dest)
            entries.append({'path':str(dest.relative_to(tree_dir)).replace('\\','/'),'source':str(src),'sha256':sha(dest),'bytes':dest.stat().st_size,'kind':'public_evidence'})
    selected_fields=['项目名称','产品','招标单位','客户标签','中标单位','运营商类型','中标金额（万元）','场景','相关网页','公告日期','公告类型','中标金额原文','信息缺口','_body_url','_fetched_at','_parsed_at','_parser_version','_award_rows']
    write(base/'record.json',{k:r.get(k) for k in selected_fields})
    sample_refs.append({'title':r['项目名称'],'record':str((base/'record.json').relative_to(tree_dir)).replace('\\','/'),'amount_wan':r['中标金额（万元）'],'url':r['相关网页']})
write(tree_dir/'artifacts/evidence/samples.json',sample_refs)
textfile('README.md',f'''# 全国公共资源交易平台采集：技术与复用入口

本案例保存于 {stamp}，采集整体状态为 **partial**。当前采集可继续推进，本包是这一时刻的技术与代码快照。

- [想法树](tree.md)：需求、方法、实测、口径、缺口与复用节点。
- [技术与复用手册](TECHNICAL-REUSE.md)：技术栈、链路、参数、迁移步骤和故障处理。
- [代码索引](CODE-INDEX.md)：各模块的作用、依赖和可复用范围。
- [源码哈希清单](SOURCE-MANIFEST.json)：复制来源、SHA256及大小。
- [依赖版本](DEPENDENCIES.json)：本机验证版本，环境和浏览器不在包内。
- [采集与Excel状态快照](PROGRESS-SNAPSHOT.json)：分别记录时间戳，实时状态看 {root/'job.json'}。
- [复用包独立验证](REUSE-VERIFICATION.json)：在快照目录运行22项离线回归、入口参数预检和模块路径检查。
- [真实公告样本](artifacts/evidence/samples.json)：正文、文本、字段及原网址。
- [压缩包](national-ggzy-reuse-20261028.zip)：包含文档、源码和三份公开样本，解压后可离线查看。

生产源码为 {repo/'pipeline/research/national_ggzy.py'}；本树 artifacts/code 是复制校验过的快照，不自动接管或重启生产任务。本轮使用确定性规则与本地浏览器，不调用大模型。browser-use、Skyvern、ScrapeGraphAI和Firecrawl的部署资料见 [已有爬虫部署树](../local-crawler-agents-20261027/tree.md)，这些框架未参与本次生产采集。
''')
textfile('CODE-INDEX.md','''# 代码索引与复用范围

| 快照文件 | 作用 | 复用时需要做什么 |
|---|---|---|
| [national_ggzy.py](artifacts/code/pipeline/research/national_ggzy.py) | 全国平台列表查询、分窗翻页、正文解析、缓存、检查点和CLI | 同站点改日期、关键词、来源及新输出目录；跨站点重写接口契约、URL及正文选择器 |
| [site_fetch.py](artifacts/code/scripts/thirdparty_goverment_spider/site_fetch.py) | Requests取页、系统curl/Schannel兜底、自报UA、代理选择、基础节流 | 适合公开静态HTML；调用方仍须限定URL与范围，不能当通用安全沙箱 |
| [bid_common.py](artifacts/code/pipeline/research/bid_common.py) | 金额万元转换、客户/运营商/场景规则等纯函数 | 规则具有医卫口径；改行业须先定义新词表及样本，避免直接修改影响已有站点 |
| [zycg.py](artifacts/code/pipeline/research/zycg.py) | 提供复用的parse_detail及标的/字段提取 | 本次仅调用解析函数；该文件自带的央采联网入口未在本次任务调用 |
| [fetch.py](artifacts/code/pipeline/research/fetch.py)、[tenders.py](artifacts/code/pipeline/research/tenders.py)、[config.py](artifacts/code/pipeline/research/config.py) | zycg在导入时所需的传递依赖 | 保留以保证包可导入；全国平台主抓取实际走site_fetch，不能据这些模块存在就认定其DNS/robots/体积控制已应用于本次链路 |
| [run_collection.mjs](artifacts/code/support/run_collection.mjs) | 启动有限批次、轮转政府采购/工程建设、记录PID与日志、触发Excel更新 | 修改repo/root/python/node/phases/日期；预算元数据和实际spawn参数都要一致。无跨进程互斥锁，启动前核实PID |
| [build.mjs](artifacts/code/support/build.mjs) | 归并重复公告、生成九字段和四张工作表、预览、Excel导出 | 修改runDir/outDir/工程目录/日期文案/超链接Python路径；依赖Codex artifact-tool运行时 |
| [native_links.py](artifacts/code/support/native_links.py) | 用stdlib ZIP/XML补原生网页超链接 | 只改链接关系，不写业务单元格；域名断言锁定www.ggzy.gov.cn，换站须重审。源、目标、映射文件是三个位置参数 |
| [test_national_ggzy_collector.py](artifacts/code/tests/test_national_ggzy_collector.py) | 22项离线回归 | 新行业/新表格布局需加真实问题的最小样本；离线通过不代表联网或全量完成 |
| [idea_tree_writer.py](artifacts/tools/idea_tree_writer.py) | 结构校验后从tree.json重建tree.md | 编辑JSON后重建，保持节点ID唯一；不要只改渲染结果 |
| [archive_ggzy_reuse.py](artifacts/tools/archive_ggzy_reuse.py) | 本次快照归档和哈希校验工具 | 仍含本任务输出目录及日期约定；复用归档工具前调整，不是通用任务运行器 |

完整 Python 包目录结构一起保留，入口脚本依赖相邻的共享解析与取页模块。快照不会附带node_modules、Conda环境、Chrome或真实配置文件。
本包验证的独立入口是national_ggzy及其核心测试；供导入的共享模块自身CLI可能仍需要原仓库的配置或额外依赖，不能据导入成功认定它们的独立业务流程也已打包完整。
''')
textfile('TECHNICAL-REUSE.md',f'''# 技术方案与跨项目复用手册

记录时间：{stamp}。生产分支：feat/national-ggzy-medical-digital。解析器版本：6。状态：partial。

## 1. 本轮实际使用的技术

| 层 | 实际技术 | 在本轮解决什么问题 |
|---|---|---|
| 浏览器检索 | Playwright {versions['playwright']} + 本机Chrome 149.0.7827.197 | 打开官方检索页，在正常页面会话中执行同源fetch，取得列表JSON |
| 正文取页 | Requests {versions['requests']}，Windows curl 8.13.0/Schannel | 获取全国平台真正的正文HTML；TLS/连接异常时使用已校验证书的系统取页路径 |
| 证书信任 | truststore {versions['truststore']} | 将Windows系统信任链接入Python SSL；浏览器ignore_https_errors=False，未关闭证书校验 |
| HTML解析 | BeautifulSoup {versions['beautifulsoup4']} + Python html.parser | 定位正文、识别表格列、提取标的/采购人/供应商等文本；处理布局表和嵌套表 |
| 采集调度 | Python 3.11.17、asyncio、asyncio.to_thread、argparse | 浏览器异步流程；同步Requests放在线程中执行，但主流程仍按请求节流，不是并发扫站 |
| 检查点与证据 | JSON、UTF-8 BOM CSV、SHA256、原子替换 | 保存窗口、页码、候选、记录、历史失败、文件来源；支持resume及原文重解析 |
| 本机批次监督 | Node.js v24.22.1 child_process + PowerShell隐藏启动 | 启动有上限的批次、记录真实PID/日志、切换两个采集阶段和更新表格 |
| Excel | @oai/artifact-tool {artifact['version']} | 生成工作表、数值金额、日期、筛选、冻结与预览；交付前检查结构及错误 |
| 原生链接补齐 | Python标准库zipfile + ElementTree | 当前运行时HYPERLINK未实现，只给导出的OOXML补链接，不重写表格内容 |

主链路不调用LLM，也不需要DeepSeek密钥。HTTPX/lxml虽然已安装，但不是这个采集器核心代码的必需依赖。browser-use/Skyvern/ScrapeGraphAI/Firecrawl未用于本批生产采集；本案例复用已有Playwright和共享取页/解析代码。全国平台采集模块目前通过CLI由Codex调用，没有新增专用MCP工具。

## 2. 从检索到表格的链路

```mermaid
flowchart TD
  A[日期/关键词/来源/栏目] --> B[本地Chrome官方检索会话]
  B --> C[同源POST列表接口]
  C --> D[按月检索与日期二分/翻页]
  D --> E[保存原始JSON并筛选标题]
  E --> F[定位a外壳对应的b正文]
  F --> G[Requests/系统curl取正文]
  G --> H[BeautifulSoup+字段规则]
  H --> I[HTML/文本/JSON/CSV检查点]
  I --> J[重复公告归并与标包拆分]
  J --> K[中标成交/中标分项/采购线索/覆盖缺口]
```

真实请求入口是 https://www.ggzy.gov.cn/deal/dealList.html；列表为POST /information/pubTradingInfo/getTradList。表单使用DEAL_CLASSIFY、DEAL_STAGE、SOURCE_TYPE、DEAL_TIME=06、TIMEBEGIN、TIMEEND、FINDTXT、PAGENUMBER。实际返回code 200有保存的JSON；早期直接请求的404和历史接口结束时间错误仍留在旧任务。正常浏览器会话与早期直连结果不同是观测结果，具体网关/WAF规则没有被完整证明。

源码从官方前端和实际iframe确认：/information/deal/html/a/是详情外壳，正文使用/html/b/。该路径变换只适用于已确认的全国平台页面，不能照搬到其他网站。正文虽可标text/plain，内容实际是HTML，按已验证的站点契约处理。

来源枚举：1省平台、2央企招投标、3财政部、4自然资源部、6商务部。本次更正财政部为3；原source4任务单独保留。政府采购用02和0202/0201；工程建设用01和0104/0101。财政部0201的通用“公告信息”中也会有结果公告，因此用明确结果标题辅助判断，不能只看栏目编号。CLI列出23/90不代表这些类别已完成验证。

## 3. 复用方式与要改的地方

**同一全国平台的新任务：**复用入口和取页代码，明确新日期、关键词、来源、栏目、输出目录及预算。改日期/关键词/来源范围要另建任务；成功缓存只在相同配置下resume。新项目领域还需改HEALTH/STRONG/PHYSICAL/SOFTWARE和标签规则，并增加离线及少量真实验证。

**不同采购网站：**复用金额转换、证据归档、表格生成思路和检查点模式；重新勘察列表接口、登录/会话要求、栏目含义、分页上限、详情地址和表格选择器。保留新站点自己的抓取器，先拿一份真实公开样本验证。修改bid_common会影响央采/北京/雄安等已有采集器，优先站点局部覆盖或新行业模块。

**其他操作系统/另一台电脑：**需要提供Python、Playwright、已有Chrome和四项Python依赖；national_ggzy.py内的Chrome路径、run_collection.mjs的repo/root/python/node/PATH/日期/阶段、build.mjs的runDir/outDir/日期文案/原生链接Python路径都需要调整。不能把Windows证书/curl/Conda路径当作跨平台配置。包内不附带运行环境。

**只需要数据，不需要原样Excel：**采集器直接产出公告明细.csv及state.json，不依赖artifact-tool。原样Excel仍依赖Codex桌面的artifact-tool及相应Node/Python运行时；包内没有该专有运行时，不保证在任意裸Node环境可直接npm安装后运行。

这个入口是站点专用CLI，不是统一health_deployment版本1任务JSON；request.json是范围记录，不能直接传给run-local.ps1 task --spec。job.json是本机批次状态文件，不是互斥锁。

## 4. 最小使用示例（先离线校验，联网另行执行）

在原仓库根目录或解压后的artifacts/code目录运行。以下目录名为新任务示例，运行前确认没有同名任务。依赖已具备时，无需再次安装或下载浏览器。requirements-collector.txt只记录已验证版本，不自动执行安装。

```powershell
$python = 'D:/Anaconda3/envs/BigData/python.exe'
$env:PATH = 'D:/Anaconda3/envs/BigData/Library/bin;D:/Anaconda3/envs/BigData;' + $env:PATH
$env:PYTHONIOENCODING = 'utf-8'
& $python -B -m pipeline.research.national_ggzy --start 2026-10-21 --end 2026-10-28 --keywords 医院 --sources 1 --business 02 --notice-types 0202 --output E:/CAICTBigData/coding/outputs/ggzy-reuse-example-new --max-api-calls 5 --max-details 10 --dry-run
```

确认范围与预算后，对同一个新任务删除--dry-run参数执行；这一步会联网。dry-run只校验日期/节流/预算和计算初始窗口，不证明浏览器、证书或网络正常。原任务续跑用完全相同的范围并加--resume，不能同时启动同目录的两个采集进程。--max-api-calls是本次调用预算；--max-details是该目录累计详情请求上限。网络重试也可能产生底层额外尝试，计数不是逐包HTTP总量。

```powershell
# 离线重解析已有正文：仍须先确认该目录没有存活采集进程
& $python -B -m pipeline.research.national_ggzy --output E:/CAICTBigData/coding/outputs/ggzy-reuse-example-new --start 2026-10-21 --end 2026-10-28 --keywords 医院 --sources 1 --business 02 --notice-types 0202 --resume --stage reparse
# 入口解析回归（快照包含22项）
& $python -B -m unittest discover -s tests -p test_national_ggzy_collector.py -q
```

--stage discover只做列表、--stage details处理已发现正文、--stage reparse只读已保存正文。--retry-failed仅在失败原因已处理后显式使用；它不是绕过验证码的开关。同步取页默认不继承本地代理，如需本来授权的代理，在启动进程前设置SITE_FETCH_USE_PROXY=1；不能把切代理写成自动绕过访问限制的步骤。

## 5. 字段、金额与覆盖口径

九项字段：项目名称、产品、招标单位、客户标签、中标单位、运营商类型、中标金额（万元）、场景、相关网页。额外保留公告日期、公告类型、省份、项目编号、金额原文、信息缺口和标签依据。

实体和标的从原文取；缺失或不可靠就留空。客户、运营商和场景是名称/标题规则标签，不是人工核验或企业股权穿透结论。“非运营商”仅表示名称规则未识别。医学教育/科研机构也可能进入广义线索，需要按项目研究口径复核。标题筛选会漏掉只在正文出现的医疗/数字化内容，也可能保留广义机构IT线索。

只将明确中标/成交金额换算为万元，预算、报价排名、单价、折扣和百分比不当总额。候选人公示、更正、终止及采购公告不填最终中标事实。多标包无明确总额时主表金额留空，分项表逐条留金额；产品未自动匹配到分项，留空待核，主表和分项不可相加。自动重复归并保留evidence_ids及所有URL，公告数不是去重项目数。

## 6. 检查点、故障和恢复经验

- **列表1000条上限：**先按月，再递归二分日期。单日仍达1000时停止，需要实现进一步来源/地域细分；这部分没有实现。
- **限流和验证码：**每次显式请求至少间隔3.2秒；HTTP 401/403/429或code 829/800会停止，不自动解验证码。列表fetch设45秒AbortController；失败响应与重试尝试各自保留。
- **TLS：**启用系统信任，保留证书校验；Requests失败按site_fetch的系统curl路径处理，连续证书失败会停止。不能用verify=False恢复。
- **嵌套表格：**只按tr最近的table解释列，过滤页布局表；产品排除表头、品目号、联系方式及畸形长尾。上述问题均有离线回归。
- **进程与预算：**监督器每15秒读检查点，最多12轮、每阶段每批500次检索、每阶段累计6000次详情。达到预算留下窗口后进入后续批次；无跨进程互斥锁和操作系统崩溃自动恢复。所有启动都要先核实旧PID和输出目录。
- **人工暂停：**在运行阶段目录创建pause.request，等待检查点及真实进程退出；归档旧job和日志后，再处理自己创建的暂停控制文件并恢复。不要删除任务锁强行继续。
- **Excel被占用：**本次发现~$工作簿锁文件，os.replace报WinError 5。采集仍推进，最后成功Excel和delivery-dataset.json可能落后于state.json/CSV；job.last_export_error可定位。用户关闭占用该文件的Excel后，后续有新记录或阶段结束时可重试。不要强制关闭用户应用或删除~$锁。当前没有已验证的锁定自动旁路导出功能。
- **刷新时间：**180秒是最小导出间隔，还需记录数变化触发，不是严格每180秒一次；Excel被占用或生成失败时不会保证最新。生成单独临时文件后原子替换，旧的有效交付仍保留。

## 7. 已验证内容与仍需完成

原仓库22项采集器回归和11项旧脚本回归合计33项已通过；本快照单独带22项核心采集器测试。真实网络已取得列表及正文，三个样本含可核对的金额单位转换。Excel曾逐项核对九列、原生URL、数值金额、日期范围、非结果空中标事实、ZIP完整性并查看四页预览。每次字段或布局变更仍需重查，不能把旧验证声明当作未来导出自动认证。

归档的首次独立预检发现zycg还有fetch、tenders、config三项传递依赖，随后一起补入快照。最终检查直接在artifacts/code中运行，导入路径指向快照本身，避免误用生产仓库造成“看似可复用”。每次归档会保存REUSE-VERIFICATION.json；预检未通过时停止打包。

截至本快照，政府采购与工程建设范围仍为partial；工程队列以job.json为准。尚缺未处理窗口、单日上限进一步细分、标包级产品映射、实体/金额缺口补核、跨站适配和独立项目归并核验。没有实现通用全自动任意网站采集、登录验证码处理、LLM字段补核或全量覆盖证明。

实时原始记录：{root/'collection-v2'}。成功工作簿目录：{delivery}。本树提供代码和三份公开样本，完整原文/解释器/虚拟环境未全部打包。
''')
nodes={n['id']:n for n in tree['nodes']}
def upsert(i,parent,kind,status,text):
    if i in nodes:nodes[i].update(parent=parent,kind=kind,status=status,text=text)
    else:
        node={'id':i,'parent':parent,'kind':kind,'status':status,'text':text}
        tree['nodes'].append(node);nodes[i]=node
upsert('reuse','need','reuse','completed','技术与复用资料已归档：README.md、TECHNICAL-REUSE.md、CODE-INDEX.md、DEPENDENCIES.json、SOURCE-MANIFEST.json、源码快照、真实公告样本及national-ggzy-reuse-20261028.zip。包中不包含解释器、浏览器、node_modules和真实配置。')
upsert('reuse-stack','reuse','technology','completed','本轮实际栈：Python/asyncio、Playwright+Chrome、Requests/Windows curl+Schannel、truststore、BeautifulSoup、JSON/CSV/SHA256、Node子进程监督、artifact-tool与OOXML超链接补齐。没有调用大模型或四个已部署智能体框架。')
upsert('reuse-boundary','reuse','boundary','completed','site_fetch和金额/证据/表格模式可复用；全国平台接口、来源枚举、a/b正文、医疗筛选和硬编码路径要逐项适配。当前为CLI模块，未新增MCP工具；request.json不是统一任务spec。')
upsert('reuse-quickstart','reuse','usage','completed','手册包含新任务dry-run、有限预算采集、相同范围resume、离线reparse及22项核心测试命令；调整来源/关键词/日期须新目录，启动前核实PID。')
upsert('reuse-lock','reuse','issue','partial','归档时采集进程仍活跃；发现工作簿~$占用锁及WinError 5，采集检查点继续推进，Excel刷新暂失败。保留最后成功版本及错误，不关闭用户应用；恢复方法见手册第6节。')
upsert('reuse-snapshot','reuse','evidence','completed',f"{stamp}快照：政府正文{len(state['records'])}条；最后成功Excel时间{dataset['updated_at']}，去重公告{dataset['deduplicated_notice_count']}条，其中结果{dataset['award_records']}、线索{dataset['tender_records']}；分项{dataset['award_lot_rows']}条。时间不同的计数不能混用，不能认定全量。")
nodes['live']['text']=f"{stamp}核对job状态{job['status']}，进程仍在运行（监督{job.get('supervisor_pid')}，采集{job.get('collector_pid')}）。最小180秒且记录变化时尝试导出；当前存在Excel占用错误，详细状态见PROGRESS-SNAPSHOT.json和原任务job.json。"
nodes['excel']['text']=f"最后成功导出快照{dataset['updated_at']}：{dataset['award_records']}条结果公告、{dataset['award_lot_rows']}条分项、{dataset['tender_records']}条线索。工作簿当前占用导致后续刷新失败，原始state/CSV仍增长；详见快照时间。"
tree['updated_at']=stamp
tree['status']='partial'
write(tree_dir/'tree.json',tree)
sys.path.insert(0,str(repo/'scripts'))
from idea_tree_writer import render_tree
render_tree(tree_dir/'tree.json')
main=repo/'README.md'
existing=main.read_text(encoding='utf-8-sig')
line='- [全国平台技术与复用手册](idea-trees/national-ggzy-medical-digital-2026-20261028/TECHNICAL-REUSE.md)：源码快照、实用参数、依赖版本、跨项目适配与故障经验。\n'
if line not in existing:main.write_text(existing.rstrip()+'\n'+line,encoding='utf-8')
code_dir=tree_dir/'artifacts/code'
checks=[]
for label,args in [
    ('offline_tests',[sys.executable,'-B','-m','unittest','discover','-s','tests','-p','test_national_ggzy_collector.py','-q']),
    ('dry_run',[sys.executable,'-B','-m','pipeline.research.national_ggzy','--start','2026-10-21','--end','2026-10-28','--keywords','医院','--sources','1','--business','02','--notice-types','0202','--output',str(repo/'outputs/ggzy-reuse-example-validation'),'--max-api-calls','5','--max-details','10','--dry-run']),
    ('module_path',[sys.executable,'-B','-c','import pipeline.research.national_ggzy as m; print(m.__file__)']),
]:
    done=subprocess.run(args,cwd=code_dir,capture_output=True,text=True,encoding='utf-8',timeout=60)
    checks.append({'name':label,'exit_code':done.returncode,'stdout':done.stdout.strip(),'stderr':done.stderr.strip()})
    if done.returncode!=0:
        write(tree_dir/'REUSE-VERIFICATION.json',{'at':stamp,'status':'failed','checks':checks})
        raise RuntimeError(label+' failed: '+done.stderr[-1200:])
    if label=='module_path':assert Path(done.stdout.strip()).resolve().is_relative_to(code_dir.resolve())
write(tree_dir/'REUSE-VERIFICATION.json',{'at':stamp,'status':'passed','network_used':False,'checks':checks,'scope':'全国平台CLI及22项核心回归，不代表所附其他模块自身CLI、任意网站或异机环境均已验证。'})
tracked={e['path']:e for e in entries}
for relative in ['README.md','TECHNICAL-REUSE.md','CODE-INDEX.md','tree.json','tree.md','DEPENDENCIES.json','PROGRESS-SNAPSHOT.json','validation-snapshot.json','REUSE-VERIFICATION.json','artifacts/tools/archive_ggzy_reuse.py','artifacts/code/requirements-collector.txt','artifacts/evidence/samples.json']:
    path=tree_dir/relative
    tracked.setdefault(relative,{'path':relative,'source':'generated or prior validation snapshot','sha256':sha(path),'bytes':path.stat().st_size,'kind':'documentation_or_metadata'})
for path in tree_dir.glob('artifacts/evidence/*/record.json'):
    relative=str(path.relative_to(tree_dir)).replace('\\','/')
    tracked[relative]={'path':relative,'source':'selected public fields from state.json','sha256':sha(path),'bytes':path.stat().st_size,'kind':'public_evidence'}
manifest={'tree_id':a.tree_id,'captured_at':stamp,'branch':'feat/national-ggzy-medical-digital','files':list(tracked.values()),'not_bundled':['runtime executables','node_modules','Conda/virtualenv','Chrome browser/profile','secrets/env/cookies','all collected pages'],'notes':['只读复制生产源码和公开样本，未修改运行中的采集器、原文或任务配置。','未进行Git暂存、提交或推送。']}
write(tree_dir/'SOURCE-MANIFEST.json',manifest)
for e in manifest['files']:assert sha(tree_dir/e['path'])==e['sha256']
zip_path=tree_dir/'national-ggzy-reuse-20261028.zip'
with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED) as z:
    for relative in [*[e['path'] for e in manifest['files']],'SOURCE-MANIFEST.json']:
        z.write(tree_dir/relative,a.tree_id+'/'+relative)
with zipfile.ZipFile(zip_path) as z:
    assert z.testzip() is None
    for e in manifest['files']:assert hashlib.sha256(z.read(a.tree_id+'/'+e['path'])).hexdigest()==e['sha256']
result={'tree':str(tree_dir/'tree.md'),'manual':str(tree_dir/'TECHNICAL-REUSE.md'),'zip':str(zip_path),'files':len(manifest['files']),'code_files':sum(e['kind']=='code' for e in manifest['files']),'samples':len(sample_refs),'nodes':len(tree['nodes']),'archive_bytes':zip_path.stat().st_size,'zip_sha256':sha(zip_path),'status':'archived','collection_status':'partial'}
write(tree_dir/'ARCHIVE-VERIFICATION.json',result)
print(json.dumps(result,ensure_ascii=False))
