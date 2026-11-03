"""把北京两条官方线的本轮成果写入想法树 20261027-213520。

只做两件事：
1) 修复历史节点 id 重复（run 固定 id 导致 tree.md 重复渲染）；
2) 追加本轮结果、纠错、沉淀、缺口与后续方向节点，并写入顶层事实字段。
不虚构未发生的执行。
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TREE_ID = "20261027-213520"
FOLDER = ROOT / "idea-trees" / TREE_ID
NOW = datetime.now().astimezone().isoformat(timespec="seconds")

SITE = {"1600004": "北京市政府采购网", "1600005": "北京公共资源交易平台"}


def site_of(result: dict) -> str:
    for token in result.get("command") or []:
        for code, name in SITE.items():
            if code in str(token):
                return name
    return "未标注站点"


def repair(nodes: list) -> list:
    """同一 id 只保留第一次出现，后续按出现顺序加序号，保证 parent 仍可解析。"""
    seen = {}
    remap = {}
    out = []
    for index, node in enumerate(nodes):
        node = dict(node)
        node_id = node["id"]
        if node_id in seen:
            seen[node_id] += 1
            node["id"] = f"{node_id}-{seen[node_id]}"
        else:
            seen[node_id] = 1
        remap[index] = node["id"]
        out.append(node)
    # parent 指向同 id 的兄弟时，改指向第一个（主题/交付只有一个真实归属）
    for node in out:
        parent = node.get("parent")
        if parent and parent in seen and seen[parent] > 1 and "-" not in parent:
            node["parent"] = f"{parent}-2" if f"{parent}-2" in {n['id'] for n in out} else parent
    return out


def main() -> None:
    tree = json.loads((FOLDER / "tree.json").read_text(encoding="utf-8"))
    nodes = repair(tree["nodes"])

    # 主题/交付只留一份，其余同名决策折叠为执行记录
    theme = next(n for n in nodes if n["id"] == "theme")
    theme["text"] = "主题确认为：北京两条官方线经本机第三方库采集医疗招采公告"
    delivery = next(n for n in nodes if n["id"].startswith("delivery"))
    delivery["parent"] = "theme"
    delivery["text"] = "交付格式确认为：json（站点5列TSV + 详情JSON）"

    runs = [n for n in nodes if n["id"].startswith("run")]
    sites = []
    for order, node in enumerate(runs, 1):
        result = node.get("result") or {}
        site = site_of(result)
        sites.append((order, site, result.get("success_count", 0), result.get("failure_count", 0)))
        node["id"] = f"run-{order}"
        node["parent"] = "delivery"
        node["kind"] = "action"
        node["text"] = (
            f"第{order}次执行 · {site}：成功{result.get('success_count', 0)}条、"
            f"失败{result.get('failure_count', 0)}条"
        )

    keep = [n for n in nodes if not (n["id"].startswith("theme") and n["id"] != "theme")]
    keep = [n for n in keep if not (n["id"].startswith("delivery") and n["id"] != delivery["id"])]

    def node(node_id, parent, kind, text="", **extra):
        keep.append({"id": node_id, "parent": parent, "kind": kind, "at": NOW,
                     "text": text, "status": "completed", **extra})

    node("result", "delivery", "结果",
         "两站均为 2026-10-27 当日、各翻 2 页：北京市政府采购网 11 条（医卫数智3/设备6/其他2），"
         "北京公共资源交易平台 4 条（设备3/其他1），失败均为 0。字段含项目编号、采购人、"
         "中标供应商、金额，属真实公告事实，未做规模推算。")
    node("result-mix", "result", "口径提醒",
         "公资平台“中标成交公告”当日 20 条里确无医卫项目（多为公安、环保、会议服务），4 条不是漏采；"
         "政采网仅覆盖 2 页，更早日期需放大页数或改日期窗。")
    node("result-samples", "result", "实例",
         "海淀医院信息化升级改造中标 1169.58 万；市属医院 2026 医用设备带量采购放射组预算 11182 万"
         "（采购人北京市医院管理中心）；通州妇幼保健院 1790.79 万；天坛医院超融合扩容 259.65 万；"
         "隆福医院中医药示范设备 589.46 万。")

    node("correction", "result", "已修正错误",
         "推翻本轮之前两条“不可采”结论，证据留在规则配置与台账。")
    node("correction-ccgp", "correction", "纠错1：政采网",
         "此前只测 443 端口，两轮网络均 TCP 不通，误判为站点/网络准入限制。补测 80 端口：TCP 可连，"
         "http:// 首页 200（约90KB）、不跳转 https、robots.txt 为 404。真实结论是“仅 HTTP 入口可用”，"
         "规则新增 transport=http_only。")
    node("correction-ggzy", "correction", "纠错2：公资平台",
         "此前记为“WAF 按 UA 拦爬虫”。逐 UA 对照后该判断不成立：被拦的只有 UA 含 python-requests 的请求，"
         "自报 UA CAICTMedicalResearchBot、curl/8.4.0、不发 UA 均返回 200，robots.txt 为 404。"
         "唯一障碍是国密 SM2 TLS（OpenSSL 报 SSL: BAD_ECPOINT），本轮未使用浏览器 UA。")

    node("code", "result", "代码沉淀",
         "按 goverment_spider 库约定新增两个站点脚本，经 runner --site 执行而非直接调用："
         "codes/1600004.北京市政府采购网-医疗中标.py、codes/1600005.北京公共资源交易平台-医疗中标.py；"
         "共用 site_fetch.py（先 requests，TLS 失败才换系统 TLS 栈的 curl，证书始终校验，curl=60 直接报错）。"
         "repos/ 被 gitignore，正本另存 scripts/thirdparty_goverment_spider/。")
    node("code-fix", "code", "本轮修的问题",
         "① 扩充数字化关键词（超融合/服务器/存储/云平台/DRG 等），否则设备类以外的数智项目会漏；"
         "② 取页默认直连：本机代理曾把公资平台 index_2.html 拦成 502，改直连后失败清零；"
         "③ 想法树写入：cmd_run 原用固定 id 写 theme/delivery/run，同一棵树连跑多次会产生重复节点，"
         "tree.md 把 5 次执行渲染成 125 条重复项，现改为 upsert + 递增 run 节点 id。")

    node("verify", "result", "验证",
         "规则版本升至 2026-10-27.6，两站 rule_status 均为 third_party_script_verified 并写入 third_party 脚本映射；"
         "新增 tests/test_beijing_official_scripts.py 11 项离线回归（列表解析、详情字段、关键词正负例、分页地址）；"
         "全库 271 项测试 270 通过，唯一失败 test_full_install_fails_preflight_before_installing_missing_repositories "
         "经 stash 复测确认为与本轮无关的既有问题（install 预检读 stderr 为 None）。")
    node("evidence", "result", "证据位置",
         "台账 docs/medical-digital-tender-validation-20261027/beijing-thirdparty-20261027/"
         "（report.md + 两站逐条 JSON + 任务树快照）；规则 configs/medical_digital_tender_rules.json；"
         "原始首页与栏目样本 outputs/beijing-thirdparty-20261027/。")

    node("gaps", "result", "缺口")
    node("gap-pages", "gaps", "覆盖深度",
         "仅当日 2 页，未按日期窗回溯到 2024 起的存量；未验收全量页数下的翻页稳定性。")
    node("gap-dedup", "gaps", "跨站去重",
         "同一项目在两站重复出现（如“市属医院设备带量采购”），尚未按项目编号做跨站归并。")
    node("gap-channels", "gaps", "栏目缺口",
         "公资平台的中标候选人公示、合同公示未纳入；政采网区级招标/合同公告仅登记未采。")
    node("gap-authorize", "gaps", "仍需授权",
         "浙江（根证书不受信任）、河南（证书主机名不匹配）保持不可采，未关闭校验也未加例外；"
         "商业 API 无授权不发计费请求。")

    node("next", "result", "后续方向",
         "① 按项目编号跨站去重；② 把合同公示/候选人公示纳入；③ 给 runner 透传 --max-pages；"
         "④ 按日期窗回溯并与 ccgp 中央网北京属地数据交叉核对完整性。")

    tree["nodes"] = keep
    tree["status"] = "completed"
    tree["status_note"] = "两条官方线本机实采通过；此前两条不可采判断已更正，证据与失败口径留在节点内。"
    tree["theme"] = "北京两条官方线经本机第三方库采集医疗招采公告"
    tree["rules_version"] = "2026-10-27.6"
    tree["result"] = {
        "北京市政府采购网": {"records": 11, "failures": 0, "pages": 2, "date": "2026-10-27"},
        "北京公共资源交易平台": {"records": 4, "failures": 0, "pages": 2, "date": "2026-10-27"},
        "new_regression_tests": 11,
        "full_regression": "271 项 / 270 通过（1 项既有 install 预检失败，与本轮无关）",
    }
    tree["artifacts"] = [
        "docs/medical-digital-tender-validation-20261027/beijing-thirdparty-20261027/report.md",
        "docs/medical-digital-tender-validation-20261027/beijing-thirdparty-20261027/北京市政府采购网-医疗公告.json",
        "docs/medical-digital-tender-validation-20261027/beijing-thirdparty-20261027/北京市公共资源交易平台-医疗公告.json",
        "scripts/thirdparty_goverment_spider/README.md",
        "scripts/thirdparty_goverment_spider/1600004.北京市政府采购网-医疗中标.py",
        "scripts/thirdparty_goverment_spider/1600005.北京公共资源交易平台-医疗中标.py",
        "scripts/thirdparty_goverment_spider/site_fetch.py",
        "configs/medical_digital_tender_rules.json",
        "tests/test_beijing_official_scripts.py",
    ]
    tree["provenance"] = (
        "节点来自本轮真实执行记录（runner 5 次运行结果）与本机实测诊断；"
        "纠错节点保留被推翻的旧判断与推翻依据，不删除历史。"
    )
    tree["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    ids = [n["id"] for n in keep]
    assert len(ids) == len(set(ids)), "节点 id 仍有重复"
    valid = {"need", "route"} | set(ids)
    for n in keep:
        assert n.get("parent") is None or n["parent"] in valid, f"孤儿节点 {n['id']} -> {n.get('parent')}"

    from pipeline.idea_tree import save_tree
    save_tree(tree)
    print(f"节点数 {len(keep)}；id 唯一；父子关系可解析")
    print("执行记录：", sites)


if __name__ == "__main__":
    main()
