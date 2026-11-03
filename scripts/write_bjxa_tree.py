"""把北京、雄安医卫数字化中标这一轮的方法与进度写入想法树。

只记录真实发生过的事：两个站点的入口勘察、正文来源替换（河北政采 403 → ccgp 镜像）、
按月补窗与限流、地域误命中的三次修正、离线重出表的结果、口径边界清单、遗留缺口。
不虚构未发生的执行，也不写无法复核的数字。

重复执行会覆盖同一棵树（id 固定），不会生成第二份。
"""
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.idea_tree import add_node, save_tree  # noqa: E402

TREE_ID = "20261027-bjxa-medical"
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

REQUIREMENT = (
    "沿用央采那一版的代码与方法，新建分支，在其上新增「北京、雄安公共资源交易中心」"
    "2026 年以来医卫数字化中标信息的采集，并落成同一张八列表：项目名称、产品、招标单位、"
    "客户标签、中标单位、运营商类型、中标金额（万元）、场景。"
)

ROUTE = {
    "ambiguous": False,
    "tool": "北京：北京市政府采购网静态列表 + 中国政府采购网按月补窗；"
            "雄安：新区公共资源交易服务平台列表 + 中国政府采购网地方公告镜像取正文",
    "hits": {
        "北京市政府采购网静态列表 + ccgp 补窗": [
            "北京市公共资源交易服务平台 ggzyfw 首页与 robots 均 403，按规则不绕过",
            "ccgp-beijing 市级/区级「中标公告」是静态 HTML，14 条/页，可稳定翻页",
            "平台列表只保留 143 页（2000 条），更早月份改用 search.ccgp.gov.cn 按月切窗补",
            "八列口径已在央采验证，抽成 bid_common 共享，不另立一套",
        ],
        "雄安新区公共资源交易服务平台 + ccgp 地方公告镜像": [
            "xaprtc channelId=273 列表 10 条/页、可翻到底（50 页）",
            "详情页是壳：公告类型/项目编号为空，正文不渲染",
            "河北省政府采购网 robots.txt 403，按 fail-closed 不取正文",
            "同一公告在 ccgp 地方公告 /cggg/dfgg/ 有镜像，可作正文来源",
        ],
    },
}


def build() -> dict:
    tree = {
        "id": TREE_ID,
        "created_at": NOW,
        "updated_at": NOW,
        "status": "completed",
        "requirement": REQUIREMENT,
        "theme": "北京、雄安医卫数字化中标：双入口勘察、正文镜像与地域误命中修正",
        "delivery": "excel（北京/雄安各一张八列主表 + 明细页 + 口径边界复核 csv + 逐条 json）",
        "tool": ROUTE["tool"],
        "route": ROUTE,
        "nodes": [
            {"id": "need", "parent": None, "kind": "requirement", "at": NOW, "text": REQUIREMENT},
            {"id": "route", "parent": "need", "kind": "choice", "at": NOW, "text": ROUTE["tool"]},
        ],
    }

    # 一、入口勘察
    add_node(
        tree, "probe-bj", "route", "analysis",
        "北京入口勘察：① ggzyfw.beijing.gov.cn（市公共资源交易服务平台）首页与 robots.txt 均 403（WAF 页），"
        "按“遇到拒绝不绕过、不伪装浏览器 UA、不关证书校验”的既定规则弃用，只留证；"
        "② www.ccgp-beijing.gov.cn 市级/区级「中标公告」列表（A002004001002index_N.htm / A002004002002index_N.htm）"
        "是静态 HTML、14 条/页、TotalPage=143，第 144 页直接 404；③ 站内检索 /api/search/query 能查全史，"
        "但 range 日期过滤实测无效（ISO/纯日期/epoch 三种写法返回 0 条或 400，{\"before\":...} 直接 400），"
        "不能用来按月补窗。结论：主链路用静态列表，缺口交给检索站按月补。",
    )
    add_node(
        tree, "probe-xa", "route", "analysis",
        "雄安入口勘察：www.xaprtc.com 交易公开→政府采购 = queryContent[-N]-jyxx.jspx?channelId=273，"
        "10 条/页；实测翻到第 50 页后第 51 页起返回 795 字节空页（列表到底，最早 2026-08-04）。"
        "详情页 /jyxxzccj/xxx.jhtml 是壳：公告类型、交易方式、项目编号全空，正文不渲染，只有「公告来源」"
        "指向 www.ccgp-hebei.gov.cn。河北省政府采购网目录页与 robots.txt 均 403、http 偶发 502，"
        "按 fail-closed 不取原站正文，改用同一公告在 ccgp 地方公告（/cggg/dfgg/）的镜像。",
    )
    add_node(
        tree, "body-source", "probe-xa", "decision",
        "正文来源替换：雄安平台壳 → 读「公告来源」URL → 若指向 ccgp-hebei，则按标题到检索站反查同一公告的 "
        "/zbgg/ 或 /cjgg/ 页（日期窗取发布日 -10/+3 天，最多翻 2 页）→ 取 ccgp 正文。"
        "反查只认 /zbgg/、/cjgg/，不认 /qtgg/（其他公告）：否则同项目会以空记录重复入表。",
    )

    # 二、方法链路
    add_node(
        tree, "pipeline", "route", "method",
        "采集链路：北京 = 市级+区级列表（143×2 页）→ 剥 [公开]/[朝阳区] 前缀存 region_hint → 标题级过滤 → "
        "逐条取详情（div.BodyLabel：项目编号/项目名称/总中标成交金额/中标成交供应商名称/采购人/代理机构/"
        "主要标的信息表）→ 打标 → 八列表；雄安 = channelId=273 列表 → 只留 /jyxxzccj/ → 取壳读公告来源 → "
        "ccgp 镜像取正文（PROJECTNAME/PurchaserName/gpbudgetamt/content 打包串）→ 打标 → 八列表。"
        "代码 pipeline/research/bjxa.py。",
    )
    add_node(
        tree, "common", "pipeline", "method",
        "口径共享：把央采的八列口径抽成 pipeline/research/bid_common.py（COLUMNS/MED_ORG/DIGITAL/NON_DIGITAL/"
        "STAGE_WORDS + clean/classify_scope/customer_tag/carrier_type/scene_of/amount_wan/amount_field/"
        "labeled_lines/field/build_row/write_bid_workbook），zycg.py 从 611 行降到约 400 行，"
        "两地与央采同一套判定，回归 19 项无损。",
    )
    add_node(
        tree, "supplement", "pipeline", "method",
        "补窗：平台列表够不到更早月份时，用 search.ccgp.gov.cn/bxsearch 按月切窗（timeType=6 + start_time/end_time），"
        "只收 /zbgg/ 与 /cjgg/；北京加 path_filter=/dfgg/ 只要地方公告（中央单位那批属央采口径，另有一条链路），"
        "并按检索结果行的地域标签只留“北京”；雄安用 4 个词（雄安/容城/安新/雄县）× 8 个月。",
    )
    add_node(
        tree, "throttle", "pipeline", "method",
        "节流与合规：全程走 pipeline/research/fetch.py 的 Fetcher——robots 检查、单站点最小间隔、"
        "401/403/429 判 blocked 不重试不绕过、UA 自报 CAICTMedicalResearchBot/1.0 (public-source research)，"
        "不伪装浏览器 UA、不加代理、不关证书校验。检索站实测：delay 1.6s 很快被拦，3.5s 仍在北京 4–7 月遇阻，"
        "5.0s 时 3 月翻到第 16 页、4–7 月第 1 页即 blocked；blocked 全部写进结果的 supplement.stopped，不掩盖。",
    )
    add_node(
        tree, "offline", "pipeline", "method",
        "缓存与离线：列表页、详情页、补窗检索页都落 cache/<tag>-<md5>.html；--from-cache 只用缓存重出表，"
        "缓存缺失记进 stopped 而不发请求。为此把 offline 标志一路透传到详情、标题反查与补窗三处——"
        "此前只传了列表页，--from-cache 仍会偷偷发请求（实测跑了 4 分钟才出表）。",
    )

    # 三、执行
    add_node(tree, "run-1", "route", "action",
             "第 1 轮在线全量：北京市级+区级列表各 143 页、雄安 50 页 → 详情 146 个北京页、6 个雄安壳页、"
             "46 个 ccgp 镜像页；得北京 126 条 / 61,984.87 万元、雄安 13 条 / 8,948.36 万元，"
             "failures 11 条全为 blocked（检索站 4–7 月补窗被拦）。")
    add_node(tree, "run-2", "route", "action",
             "第 1 次修地域误命中：只按检索结果行的地域标签白名单过滤 → 北京升到 139 条（补窗多走了 20 页缓存），"
             "雄安掉到 3 条：把“雄安宣武医院”的 5 条真项目当外地误杀（这些公告由北京单位代发，标签是“北京”）。")
    add_node(tree, "run-3", "route", "action",
             "第 2 次修正：发现检索页地域标签可能为空（雄安关键词的多数行都是空），空标签被当作外地整批误杀；"
             "改为“空标签视为未知、交给标题地名判定”，并把 --from-cache 真离线化。")
    add_node(tree, "run-4", "route", "action",
             "离线重出表（run4）：北京 139 条 / 66,910.31 万元 / 缺金额 3 / 缺中标单位 0；"
             "雄安 8 条 / 9,020.06 万元 / 缺金额 0 / 缺中标单位 0；云南镇雄县 6 条全部清掉。")
    add_node(tree, "run-5", "route", "action",
             "补口径边界清单（run5，最终）：主表不变，另落 北京/口径边界复核.csv 42 条（医工设备维保 23、"
             "医用设备购置 11、后勤设施维保 5、检验病理委外 2、非数字化物资 1）、"
             "雄安/口径边界复核.csv 3 条（均为医疗设备包）；summary 增加 boundary_hits / boundary_detail / "
             "boundary_amount_wan / amount_wan_ex_boundary 四个指标便于复核。")

    # 四、结果
    add_node(
        tree, "result", "route", "结果",
        "2026-01-01~2026-10-27：北京 平台列表 4004 条（市级最早 2026-07-15、区级最早 2026-08-10）+ 补窗 1399 条 "
        "= 候选池 5403 条 → 医卫数字化 139 条 / 66,910.31 万元，缺金额 3、缺中标单位 0；"
        "雄安 列表 500 条 → 结果类 189 条 + 补窗 322 条 = 候选池 511 条 → 8 条 / 9,020.06 万元，"
        "缺金额 0、缺中标单位 0。排除项 5237 + 499 条，逐条带 reasons 落 json。",
    )
    add_node(
        tree, "boundary", "result", "discovery",
        "口径边界量化：北京 139 条里有 42 条属“设备维保/医用设备购置/后勤设施/检验委外/非数字化物资”，"
        "金额合计 34,015.50 万元，占全表 50.8%，剔除后 97 条 / 32,894.81 万元。"
        "雄安 8 条里 3 条是医疗设备包（C臂/ECMO/样本库）1,774.13 万元，剔除后 5 条 / 7,245.92 万元。"
        "北京金额前 5 名全在边界内：天坛医院大型医疗设备维保 9,735.62 万、"
        "市属医院超声带量采购 4,618.00 万、"
        "安贞医院临床外送检验 2,906.19 万、丰台康复医院医疗设备购置 2,091.26 万、同仁医院室外环境安全隐患治理 2,050.12 万。"
        "结论：这类标的不是数字化采购，但它与央采共用 bid_common 的 DIGITAL/NON_DIGITAL，收紧口径会让央采表同步变动，"
        "故本轮只单列两份 口径边界复核.csv（北京 42 条 / 雄安 3 条）+ summary.boundary_* 指标，"
        "改口径前需先确认影响面。",
    )
    add_node(
        tree, "result-structure", "result", "结果",
        "北京场景：应用系统与平台 40、影像与检验 24、运维与技术服务 22、云与算力 13、信息安全 11、其他数字化 8、"
        "网络与链路 6、数据中心与机房 3、存储与备份 3、终端与办公设备 3、互联网医院与远程医疗 3、人工智能 2、"
        "电子病历与HIS 1；客户标签：高校附属医院 69、综合医疗机构 20、专科 18、医保 6、疾控 6；"
        "运营商直投 6 条（联通 4、电信 2），其余 133 条为厂商/集成商。"
        "雄安 8 条：应用系统与平台 3、影像与检验 3、云与算力 1、终端 1，运营商仅电信 1 条。",
    )
    add_node(
        tree, "result-samples", "result", "实例",
        "雄安口径内 5 条：雄安宣武医院（新区投资部分）项目信息化工程（一期）6,379.21 万元（北京易华录）；"
        "开办项目第一批信息化终端 515.28 万元（中国电信河北雄安新区分公司等联合体）；算力服务 146.80 万元"
        "（保定仓颉）；容城县妇幼保健院检验病理服务能力提升 132.94 万元；雄安新区医疗保障智慧管理平台 "
        "71.70 万元（河北克洛德）。另 3 条医疗设备包（689.50 / 631.64 / 453.00 万元）落在口径边界清单里。",
    )

    # 五、修复记录
    add_node(
        tree, "fixes", "route", "fix",
        "本轮修的 6 个问题：① 缓存文件名带中文“市级”触发 PermissionError → tag 改 ASCII（bj-shi-NNN/bj-qu-NNN）；"
        "② ccgp 地方公告表头上方多一行“服务类/货物类”，原先假定首行是表头 → 改为在前 4 行里找真表头；"
        "③ 北京补窗混入中央单位公告（应属央采口径）→ 加 path_filter=/dfgg/；"
        "④ 雄安补窗按标题反查时命中 /qtgg/ 其他公告，同项目空记录重复入表 → 只认 /zbgg/、/cjgg/，去重键改看归一化标题；"
        "⑤ 检索站全文命中把云南“镇雄县”当雄县、把“磐安新城区/华安新邨”当安新 → 三道地域校验（平台域名、"
        "结果行地域标签、标题地名带行政后缀 + (?<!镇) 负向断言 + 去高亮空格）；"
        "⑥ --from-cache 未真离线（详情/反查/补窗仍发请求）→ offline 一路透传。",
    )

    # 六、证据
    add_node(
        tree, "code", "route", "代码沉淀",
        "pipeline/research/bjxa.py（parse_beijing_list/parse_beijing_detail/parse_xiongan_list/parse_xiongan_detail/"
        "parse_ccgp_local_detail/collect_ccgp_supplement/region_guard/find_ccgp_by_title/Runner/collect/main）；"
        "pipeline/research/bid_common.py（八列口径 + boundary_hint + write_bid_workbook）；"
        "pipeline/research/zycg.py 改为复用 bid_common；文档 docs/BJXA_MEDICAL_BID_RULES.md。",
    )
    add_node(
        tree, "verify", "route", "验证",
        "tests/test_bjxa_medical_bid.py 30 项离线回归（北京列表/详情与品牌、雄安列表与结果过滤、壳页来源 URL、"
        "河北 JS 变量与 #_@_@ 多包求和、分页 URL 形状、6 项地域校验含高亮空格与外省同名、补窗地域标签过滤、"
        "口径边界判定含“医疗设备+系统”反向排除与复核 csv 落盘）；与 tests.test_zycg_medical_bid、"
        "tests.test_idea_tree_ids 合计 54 项通过。"
        "项目环境无 pytest，统一用 unittest 跑。",
    )
    add_node(
        tree, "evidence", "route", "证据位置",
        "产物 outputs/bjxa-medical-2026/run5/（北京/雄安 各自 xlsx + csv + 口径边界复核.csv，"
        "bjxa_medical_bid.json 含逐条记录/排除项/失败台账/运行日志/cache 744 个页缓存）；"
        "中间轮次 run1（在线全量）、run2–run4（三次地域修正）保留可对比；"
        "台账 docs/medical-digital-tender-validation-20261027/ 下的北京第三方验证报告；"
        "央采那一轮的想法树 idea-trees/20261027-230958/。",
    )

    # 七、缺口与后续
    add_node(
        tree, "gaps", "route", "缺口",
        "① 北京 2026-04~07 月：平台列表回溯不到、检索站补窗被限流 blocked（supplement.stopped 有 10 条记录），"
        "这段的样本缺失，未用不可靠方式凑数；② 口径边界 42 条（设备维保 23、医用设备购置 11、后勤设施 5、"
        "检验委外 2、非数字化物资 1）仍在主表里，收紧口径会同时改动央采表，故先单列复核清单；"
        "③ 雄安 4 条 xaprtc 壳页因镜像反查不到而无项目名被跳过；④ 河北政采 robots 403，只用镜像不取原站；"
        "⑤ 更正公告可改金额，只取结果公告，合同变更/结算未纳入。",
    )
    add_node(
        tree, "next", "route", "后续方向",
        "① 与央采按项目编号跨源去重合并成一张中标表（央采 / 北京 / 雄安 / 地方政采同一八列）；"
        "② 口径收紧前先做影响面评估：设备维保与医用设备购置类在两表的条数、金额各占多少，再决定是否改 "
        "bid_common.NON_DIGITAL 并重出三张表；③ 北京 4–7 月改成按日切窗 + 更低速率重试，把 stopped 那 10 条补掉；"
        "④ 雄安正文改用 ccgp 地方公告按站内检索定向补，替代逐条标题反查，减少请求数与空记录。",
    )

    save_tree(tree)
    return tree


def main() -> None:
    tree = build()
    ids = [node["id"] for node in tree["nodes"]]
    assert len(ids) == len(set(ids)), "节点 id 必须唯一"
    print(f"tree_id={tree['id']} nodes={len(tree['nodes'])} status={tree['status']}")
    print(Path("idea-trees") / tree["id"] / "tree.md")


if __name__ == "__main__":
    main()
