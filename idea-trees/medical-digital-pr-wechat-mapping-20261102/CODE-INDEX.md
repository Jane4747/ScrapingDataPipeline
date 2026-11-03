# 代码与交付物索引

源目录：`E:/CAICTBigData/coding`。下列链接均指向本树独立快照，原件未改动。

[工作思路](DETAILS.md) · [代码学习总结](CODE_SUMMARY.md) · [想法树](tree.md) · [SHA256清单](SOURCE-MANIFEST.json)

| 文件 | 分类 | 用途 |
| --- | --- | --- |
| [wxnum_probe.py](artifacts/code/wxnum_probe.py) | probe_source | 按认证主体抓取省级运营商公众号的探针脚本（含卡片切块解析、限速与重试） |
| [probe2.json](artifacts/evidence/probe2.json) | verification_evidence | 广东、四川两省试跑的原始召回结果，用于判定收录源覆盖偏差 |
| [medical-digital-pr-url-map.html](artifacts/delivery/medical-digital-pr-url-map.html) | previous_delivery | 网址地图交付物副本（原件仍在 docs/） |
| [medical-digital-pr-wechat-matrix.html](artifacts/delivery/medical-digital-pr-wechat-matrix.html) | previous_delivery | 公众号矩阵交付物副本；原件已移至移交目录，此副本防止再次散落 |
| [idea_tree_writer.py](artifacts/archive-tool/idea_tree_writer.py) | repository_tree_tool | 父仓库已有的树渲染/校验工具，保留以便重现渲染结果 |
| [archive_medical_pr_mapping.py](artifacts/archive-tool/archive_medical_pr_mapping.py) | archive_tool | 本树的归档生成与离线校验脚本自身 |

## 范围说明

归档内容为本任务链自编脚本、试跑证据、两份 HTML 交付物副本，以及仓库树渲染工具与本归档脚本。
不含真实密钥、Cookie、运行环境或第三方框架库。探针脚本全量模式未跑完，
`artifacts/evidence/probe2.json` 只是两省试跑结果，不能当作省级覆盖率统计依据。
