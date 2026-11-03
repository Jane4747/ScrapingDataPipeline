"""Build an offline research report from collected papers and reviewed notes."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path

def e(value):
    return html.escape(str(value or ""), quote=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--notes",type=Path,default=Path(__file__).with_name("architecture_notes.json"))
    a=p.parse_args()
    root=a.root.resolve()
    notes=json.loads(a.notes.read_text(encoding="utf8"))
    records=json.loads((root/"catalog.json").read_text(encoding="utf8"))
    manifest=json.loads((root/"manifest.json").read_text(encoding="utf8"))
    lookup={r["arxiv_id"]:r for r in records}
    rows=[]; cards=[]; analysis=[]
    labels=[("执行结构","executor"),("持久更新","changes"),("反馈来源","feedback"),("接受与验证","gate"),("原文证据 / 作者报告","evidence"),("证据边界 / 本次评阅","limit"),("设计启发 / 本次推断","lesson")]
    for n in notes["papers"]:
        r=lookup.get(n["id"],{})
        if not r.get("in_scope"):
            continue
        analysis.append({**n,"title":r.get("title"),"source_url":r.get("abs_url"),"version_id":r.get("version_id"),"pdf_path":r.get("pdf_path"),"text_path":r.get("text_path"),"review_status":"source_claim_and_reviewer_interpretation","numerical_results":"author-reported; not reproduced"})
        rows.append('<tr data-group="'+e(n["group"])+'"><td><a href="#p'+n["id"]+'">'+e(n["short"])+'</a><small>'+e(r.get("version_id"))+'<br>'+e(r.get("first_submitted"))+'</small></td>'+''.join('<td>'+e(n[k])+'</td>' for k in ["group","executor","changes","gate","lesson"])+'</tr>')
        links='<a href="'+e(r.get("pdf_path"))+'">PDF · '+str(r.get("pages","?"))+'页</a> <a href="'+e(r.get("text_path"))+'">逐页文本</a> <a href="'+e(r.get("abs_url"))+'">arXiv原文</a>'
        cards.append('<article class="paper" id="p'+n["id"]+'" data-group="'+e(n["group"])+'"><div class="tag">'+e(n["group"])+' · 阅读优先级 '+str(n["priority"])+'</div><h3>'+e(n["short"])+'</h3><p class="muted">'+e(r.get("title"))+'</p><p class="links">'+links+' <span>'+e(r.get("first_submitted"))+' · v'+str(r.get("selected_version","?"))+'</span></p><dl>'+''.join('<dt>'+label+'</dt><dd>'+e(n[key])+'</dd>' for label,key in labels)+'</dl><p class="note">原文定位：'+e(n["section"])+'。逐页文本保留PDF页码；数字均为作者报告，未复现。</p></article>')
    groups=Counter(n["group"] for n in analysis)
    filters='<button class="active" data-filter="all">全部 '+str(len(analysis))+'</button>'+''.join('<button data-filter="'+e(k)+'">'+e(k)+' '+str(v)+'</button>' for k,v in groups.items())
    document='''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>2026物理与具身RSI · 文献与系统架构</title>
<style>
:root{--ink:#172b45;--muted:#52647a;--blue:#17689b;--line:#dce4ec;--pale:#edf6fb}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;font:16px/1.8 "Microsoft YaHei","Noto Sans SC",sans-serif;color:var(--ink);background:#f6f8fb}main{max-width:1180px;margin:auto;padding:42px 32px 72px}header{border-top:5px solid var(--blue);padding:25px 0}h1{font-size:37px;line-height:1.4;margin:10px 0 14px}h2{font-size:25px;line-height:1.5;margin:0 0 20px}h3{font-size:20px;margin:5px 0 12px}p{margin:10px 0 16px}a{color:#116b9d;text-decoration:none}a:hover{text-decoration:underline}small{display:block;font-size:12px;color:var(--muted);margin-top:8px}.tag,.eyebrow{font-size:13px;font-weight:700;color:var(--blue)}.muted,.note{color:var(--muted)}.note{font-size:13px}nav{display:flex;gap:20px;flex-wrap:wrap;margin:20px 0 28px;border-bottom:1px solid var(--line);padding-bottom:18px}section{background:white;border:1px solid var(--line);border-radius:12px;padding:28px;margin:24px 0}.lead{font-size:20px;font-weight:600;background:var(--pale);padding:22px;border-left:4px solid var(--blue)}.stats{display:flex;gap:32px;flex-wrap:wrap}.stats strong{font-size:28px;color:var(--blue)}.stats span{display:block;font-size:13px;color:var(--muted)}.lane{display:grid;grid-template-columns:140px 1fr;gap:18px;padding:20px 0;border-bottom:1px solid var(--line)}.lane:last-child{border:0}.lane b{color:var(--blue)}.nodes{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.node{padding:10px 14px;background:var(--pale);border:1px solid #c3dce9;border-radius:7px}.arrow{color:var(--blue);font-size:21px}.two{display:grid;grid-template-columns:1fr 1fr;gap:20px}.module{padding:18px 20px;background:#f7f9fc;border-radius:8px}.module h3{font-size:17px}.source,.links{font-size:13px}.links{display:flex;gap:16px;flex-wrap:wrap}.tablewrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px;line-height:1.7}th,td{padding:14px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{background:var(--pale)}td{min-width:145px}td:first-child{min-width:155px}.filters{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}button{font:inherit;font-size:13px;border:1px solid #bacbd8;border-radius:20px;background:white;padding:6px 13px;color:var(--ink);cursor:pointer}button.active{background:var(--blue);color:white;border-color:var(--blue)}input{font:inherit;border:1px solid #bacbd8;border-radius:6px;padding:9px 12px;width:100%;max-width:460px}.paper{border-top:2px solid #a1c7dc;padding:24px 0;margin-top:24px;break-inside:avoid}.paper h3{font-size:22px}dl{display:grid;grid-template-columns:145px 1fr;gap:9px 18px;margin:18px 0}dt{font-size:14px;font-weight:700}dd{margin:0;font-size:14px}pre{font:13px/1.7 Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere;background:#112c43;color:#e8f4ff;padding:20px;border-radius:8px}footer{color:var(--muted);font-size:13px}[hidden]{display:none!important}
@media(max-width:760px){main{padding:20px 16px}h1{font-size:28px}section{padding:20px 16px}.two{grid-template-columns:1fr}.lane{grid-template-columns:1fr;gap:8px}dl{grid-template-columns:1fr;gap:3px}dd{margin-bottom:10px}.stats{gap:20px}}@media print{body{background:white}main{padding:0;max-width:none}section{border:0;padding:15px 0}nav,.filters,.searchbox{display:none}.tablewrap{overflow:visible}table{font-size:10px}td{min-width:0!important}a{color:inherit}h1{font-size:27px}}
</style></head><body><main>
<header><div class="eyebrow">RESEARCH LIBRARY / 2026</div><h1>物理与具身 RSI<br>文献库与系统架构分析</h1><p class="muted">@@INTERPRETATION@@<br>检索截止：2026年10月25日 · 以arXiv首次提交日期限定年份 · 所选版本不晚于截止日</p><div class="stats"><div><strong>@@COUNT@@</strong><span>纳入论文</span></div><div><strong>@@DOWNLOADED@@</strong><span>有效PDF下载</span></div><div><strong>@@PAGES@@</strong><span>PDF总页数</span></div><div><strong>@@MB@@ MB</strong><span>PDF体积（十进制）</span></div></div></header>
<nav><a href="#findings">关键判断</a><a href="#loops">架构闭环</a><a href="#design">采摘机器人设计</a><a href="#matrix">论文对照</a><a href="#papers">逐篇笔记</a><a href="#reproduce">采集与复核</a></nav>
<section id="findings"><h2>从论文中可以得出的判断</h2><p class="lead">可落地的主线是：执行系统、实验改进系统、独立验收系统分开；以结构化失败证据决定改代码、补数据还是训练；验证通过的版本进入下一轮。</p><p>文献中的self-improvement涵盖策略变好、技能与记忆丰富、采数分布改变、训练程序改变，以及改进器自身改变。两篇Physical RSI综述均强调，任务成功率提高不足以证明系统更擅长改进自己；严格递归收益需要后续任务、固定预算和独立评测支持。<a href="https://arxiv.org/abs/2610.29677">[综述1]</a> <a href="https://arxiv.org/abs/2610.18842">[综述2]</a></p><p>本报告比较哪些模块改变、反馈如何到达这些模块、什么被继承，以及什么证据允许接受变化。所有工程建议为本次综合推断；论文结果未复现，不把不同任务的成功率汇总成排行榜。</p><div class="two"><div class="module"><h3>优先组合的机制</h3><p>AdaRSI的失败归因与按需训练；EmbodiRSI的失败状态纠错与定向采数；Recursia的技能交接契约；RegenHarness的证据提交与回滚。</p><p class="source"><a href="https://arxiv.org/abs/2610.20474">AdaRSI</a> · <a href="https://arxiv.org/abs/2609.38905">EmbodiRSI</a> · <a href="https://arxiv.org/abs/2610.24464">Recursia</a> · <a href="https://arxiv.org/abs/2609.27612">RegenHarness</a></p></div><div class="module"><h3>尽早测出的瓶颈</h3><p>关系感知错误、早期失败遮蔽后序技能、评价器错误和不适用的历史记忆。123轮失败案例显示，持续生成补丁不保证端到端能力累积。</p><p class="source"><a href="https://arxiv.org/abs/2609.31760">What Stops RSI? §5–7</a> · <a href="https://arxiv.org/abs/2610.18792">SEAR §3–4</a></p></div></div></section>
<section id="loops"><h2>建议的三层闭环</h2><p class="note">跨论文综合的参考架构，不是单篇原图，也不是已实现的机器人控制系统。</p>
<div class="lane"><b>① 执行闭环<br>一次任务内</b><div><div class="nodes"><span class="node">传感与结构化状态</span><span class="arrow">→</span><span class="node">技能选择与契约</span><span class="arrow">→</span><span class="node">控制器 / VLA</span><span class="arrow">→</span><span class="node">观测与完成验证</span><span class="arrow">↺</span></div><p class="note">输出实际动作、状态、接触、结果和证据；动作结束不自动提交任务完成。</p></div></div>
<div class="lane"><b>② 改进闭环<br>试验之间</b><div><div class="nodes"><span class="node">失败归因</span><span class="arrow">→</span><span class="node">修代码 / 定向采数 / 微调</span><span class="arrow">→</span><span class="node">配对验证与回归</span><span class="arrow">→</span><span class="node">版本发布 / 回滚</span><span class="arrow">↺</span></div><p class="note">可改技能、策略、数据或仿真；发布绑定代码、模型、数据、标定和测试版本。</p></div></div>
<div class="lane"><b>③ 元改进闭环<br>跨任务/世代</b><div><div class="nodes"><span class="node">修复历史与成本</span><span class="arrow">→</span><span class="node">修改实验选择 / 诊断 / 训练流程</span><span class="arrow">→</span><span class="node">独立后续任务评价</span><span class="arrow">→</span><span class="node">继承有效改进过程</span><span class="arrow">↺</span></div><p class="note">证实新改进器在同预算下产生更好的后续改进；仅有第二层反复运行还不够。</p></div></div>
<p class="source">依据：<a href="https://arxiv.org/html/2610.18842v1">Who Improves the Robot? §2.2</a>、<a href="https://arxiv.org/html/2610.29677v1">Toward RSI in Physical AI §2.2、§3.3–3.4</a>。不自行给单篇论文授予L5等级。</p></section>
<section id="design"><h2>面向木耳采摘机器人的模块设计</h2><p><b>本次工程建议：</b>下面是供项目验证的设计假设；论文中的桌面、厨房和内镜结果不能直接证明采摘效果。建议先围绕“识别目标→接近→建立抓持→分离→投放→核验”建立可复现基线，再加入自主改进。</p><div class="two">
<div class="module"><h3>1. 状态与证据服务</h3><p>融合RGB-D、关节与夹爪状态；如有力/触觉，记录接触和拉脱过程。每个目标保存实例ID、附着区域、成熟度置信度、遮挡和可达性；把观测事实、状态估计和已验证完成分字段存储。</p></div>
<div class="module"><h3>2. 带契约的技能运行时</h3><p>接口声明入口条件、动作、完成条件、超时、恢复和证据。分离完成后，还需确认抓持稳定且姿态满足投放入口；失败返回原因与证据引用。</p></div>
<div class="module"><h3>3. 失败归因与实验选择</h3><p>区分关系识别、标定、路径、滑脱、分离能力、技能交接与验收误判。先用回放/仿真配对试验区分假设，按信息收益、真机时间、复位和样本成本选下一次实验。</p></div>
<div class="module"><h3>4. 双通道更新</h3><p>调用顺序、入口姿态和恢复逻辑问题优先修改技能代码；入口条件成立后仍无法产生所需动作，才针对失败状态采演示、训练专用策略。默认策略与专用策略保留适用范围。</p></div>
<div class="module"><h3>5. 仿真与数据工厂</h3><p>用菌棒/架体几何建立场景，变化密度、遮挡、视角和附着位置。分离力与形变参数由实测校准；仿真先验证可达性、路径和流程，接触分离必须以真实样本检验。</p></div>
<div class="module"><h3>6. 独立评价与版本服务</h3><p>同时度量成功、损伤、残留、邻近目标扰动、节拍与人工干预。开发样本与未见菌棒/批次隔离；候选通过选择检查及旧场景回归后发布，外部验收与控制约束使用独立权限。</p></div></div>
<h3 style="margin-top:24px">每轮改进的最小记录</h3><pre>experiment_id / parent_system_version / improver_version
scene_id / sample_batch / calibration_version / initial_state
hypothesis / failure_type / evidence_refs / changed_component
code_hash / policy_hash / dataset_hash / simulator_hash
paired_validation / held_out_test / regressions / robot_time
accepted_or_rejected / reason / rollback_version</pre><p>先开展三组同预算对照：原系统重试、只改技能/编排、按归因选择改编排或训练。检验元改进时，在后续任务上比较旧/新改进器，保持基础执行系统和资源预算一致；仅在新场景复用旧技能不足以证明递归。</p><p class="source">机制依据：<a href="https://arxiv.org/abs/2610.20474">AdaRSI</a>、<a href="https://arxiv.org/abs/2610.10498">EmbodiedRSI</a>、<a href="https://arxiv.org/abs/2610.24464">Recursia</a>、<a href="https://arxiv.org/abs/2609.27612">RegenHarness</a>、<a href="https://arxiv.org/abs/2610.18792">SEAR</a>；模块、采摘指标和实施顺序为本次推断。</p></section>
<section id="matrix"><h2>论文系统架构对照</h2><div class="searchbox"><label for="q">筛选论文（标题、机制或关键词）</label><br><input id="q" type="search" placeholder="例如：失败、策略、仿真、验证"></div><div class="filters">@@FILTERS@@</div><p class="note" id="count" aria-live="polite"></p><div class="tablewrap"><table><thead><tr><th>论文 / 首次提交</th><th>路线</th><th>谁执行</th><th>什么被改进并继承</th><th>如何接受变化</th><th>可借鉴设计</th></tr></thead><tbody>@@ROWS@@</tbody></table></div></section>
<section id="papers"><h2>逐篇阅读笔记</h2><p class="note">优先级1为优先精读建议，2为扩展阅读，不代表论文质量评级。</p>@@CARDS@@</section>
<section id="reproduce"><h2>范围、资料与可复核性</h2><p>@@SCOPE@@</p><p>检索入口包括arXiv和作者维护的Physical RSI目录。引用追踪可能偏向该目录范围；未检索付费全文库，未覆盖2026年10月25日后论文。不把2025年首发、2026年修订的论文自动计为2026新论文。arXiv记录不等于已同行评审。</p><ul><li><a href="catalog.csv">文献目录 CSV</a> · <a href="catalog.json">完整元数据 JSON</a> · <a href="references.bib">BibTeX</a></li><li><a href="architecture_analysis.json">逐篇结构化分析</a> · <a href="manifest.json">下载统计</a> · <a href="failures.json">失败记录</a> · <a href="verification.json">完整性核验</a></li><li>pdfs/为固定版本全文；text/为带页码文本；metadata/、raw/、receipts/保存元数据、原始网页和请求结果。</li><li><a href="../../literature/collector.py">采集下载代码</a> · <a href="../../literature/README.txt">运行说明</a></li></ul><p>查询由本次联网检索执行，主题筛选后的候选输入下载程序。程序自身不会调用搜索引擎；queries仅记录检索式。下载复用pipeline.research.fetch.Fetcher，遵守robots、至少15秒间隔、TLS校验、域名边界和体积上限。扫描页或文本异常记录在text_status/text_warning；不执行OCR。</p><pre>python -B literature/collector.py --spec literature/rsi_2026.json --dry-run --json
python -B literature/collector.py --spec literature/rsi_2026.json --resume --json
python -B -m unittest discover -s literature -p test_collector.py -v
python -B literature/verify.py --root outputs/physical-embodied-rsi-20261025
python -B literature/build_report.py --root outputs/physical-embodied-rsi-20261025</pre><p class="note">首次新任务去掉--resume。改变年份、候选或范围时使用新task_id与独立目录；固定版本PDF不被不同内容静默覆盖。</p></section>
<footer>研究日期：2026-10-25（Asia/Shanghai） · 可离线阅读 · 作者陈述与工程推断分开呈现</footer></main><script>
(()=>{let group='all';const input=document.getElementById('q'),rows=[...document.querySelectorAll('tbody tr')],cards=[...document.querySelectorAll('.paper')];function filter(){const q=input.value.trim().toLowerCase();let count=0;rows.forEach((r,i)=>{const c=cards[i];const visible=(group==='all'||r.dataset.group===group)&&(!q||(r.textContent+' '+c.textContent).toLowerCase().includes(q));r.hidden=!visible;c.hidden=!visible;if(visible)count++});document.getElementById('count').textContent='当前显示 '+count+' / '+rows.length+' 篇';}document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{group=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('active',x===b));filter()}));input.addEventListener('input',filter);filter()})();
</script></body></html>'''
    replacements={"INTERPRETATION":e(notes["interpretation"]),"COUNT":len(analysis),"DOWNLOADED":manifest["downloaded_count"],"PAGES":sum(r.get("pages",0) for r in records),"MB":f'{sum(r.get("bytes",0) for r in records)/1e6:.1f}',"FILTERS":filters,"ROWS":"".join(rows),"CARDS":"".join(cards),"SCOPE":e(notes["scope"])}
    for key,value in replacements.items():
        document=document.replace("@@"+key+"@@",str(value))
    if "@@" in document:
        raise ValueError("Unresolved template field")
    (root/"architecture_report.html").write_text(document,encoding="utf8")
    (root/"architecture_analysis.json").write_text(json.dumps({"reviewed_on":notes["reviewed_on"],"scope":notes["scope"],"papers":analysis},ensure_ascii=False,indent=2),encoding="utf8")
    print(json.dumps({"report":str(root/"architecture_report.html"),"papers":len(analysis)},ensure_ascii=False))

if __name__=="__main__":
    main()

