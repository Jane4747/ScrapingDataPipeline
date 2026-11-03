# 第一批90个医院官网入口采集（分支说明）

本目录是想法树分支 `hospital-site-crawl-90-20261028`，来源为
`E:\CAICTBigData\移动项目沟通\北京雄安医院网站爬虫\第一批_97家医院_北京雄安医院官网数字化招采_爬虫智能体任务表_20261028.xlsx`
的“爬虫任务”子表。

## 范围

- 只采医院官网：90条“栏目采集”任务（P0 1条、P1 62条、P2 26条、P3 1条），89个唯一域名，关联104条机构记录。
- 日期：2024-01-01 至 2026-10-28。
- 不含 428条“官网栏目发现”（P4）待定位机构；不含政府采购平台成果。

## 文件

| 文件 | 内容 |
|---|---|
| `entrances.csv` / `entrances.json` | 90条入口清单：任务ID、批次、医院、关联医院ID、栏目类型、栏目路径、入口网址、日期范围 |
| `probe/entry_probe.csv` / `.json` | 2026-10-28 入口只读核验：状态码、标题、正文规模、robots、分类 |
| `tree.json` / `tree.md` | 想法树节点与执行记录（由 `scripts/idea_tree_writer.py` 渲染） |

采集产物在 `outputs/hospital-site-crawl-90-20261028/`（P0 试采目录为 `pilot-puh3-v4`）。

## 当前进度（2026-10-28）

1. 入口核验：78 可读、7 需渲染/维护、3 入口404、2 不可达。
2. P0 北医三院试采：44 页列表、528 条、2024 年以来 518 条、72 条关键词候选、72 份详情正文、0 失败。
3. P1/P2/P3 尚未开跑。

## 复跑命令

```bash
python3 scripts/hospital_entry_probe.py \
  --entrances idea-trees/hospital-site-crawl-90-20261028/entrances.json \
  --output idea-trees/hospital-site-crawl-90-20261028/probe --workers 6

python3 scripts/puh3_pilot_crawl.py \
  --output outputs/hospital-site-crawl-90-20261028/pilot-puh3-v4 \
  --since 2024-01-01 --max-pages 52
```

## 试采中发现并修正的问题

- 真实分页是 `zbcg.htm` 加 `zbcg/90.htm` 至 `zbcg/40.htm`（共52页），用递增页码会全站返回同一页。
- 列表条目在 `<li id="line_...">` 行内，不在 `title` 属性里；只按 `title` 抓会漏九成。
- 子页详情的相对路径是 `../../../info/...`，必须用 `urljoin`，否则拼出 `/../info/` 全部404。

## 下一步

按 78 个可读入口推进 P1：单站限速 1 请求/秒，单站落盘 list+detail，按日截断到 2024-01-01；标题关键词只做预筛，最终以正文采购标的判定；每站输出条目表与失败原因，回填任务表对应行。
