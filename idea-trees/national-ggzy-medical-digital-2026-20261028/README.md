# 全国公共资源交易平台采集：技术与复用入口

本案例保存于 2026-10-28T14:42:31+08:00，采集整体状态为 **partial**。当前采集可继续推进，本包是这一时刻的技术与代码快照。

- [想法树](tree.md)：需求、方法、实测、口径、缺口与复用节点。
- [技术与复用手册](TECHNICAL-REUSE.md)：技术栈、链路、参数、迁移步骤和故障处理。
- [代码索引](CODE-INDEX.md)：各模块的作用、依赖和可复用范围。
- [源码哈希清单](SOURCE-MANIFEST.json)：复制来源、SHA256及大小。
- [依赖版本](DEPENDENCIES.json)：本机验证版本，环境和浏览器不在包内。
- [采集与Excel状态快照](PROGRESS-SNAPSHOT.json)：分别记录时间戳，实时状态看 E:\CAICTBigData\coding\outputs\national-ggzy-medical-digital-2026-20261028\job.json。
- [复用包独立验证](REUSE-VERIFICATION.json)：在快照目录运行22项离线回归、入口参数预检和模块路径检查。
- [真实公告样本](artifacts/evidence/samples.json)：正文、文本、字段及原网址。
- [压缩包](national-ggzy-reuse-20261028.zip)：包含文档、源码和三份公开样本，解压后可离线查看。

生产源码为 E:\CAICTBigData\coding\pipeline\research\national_ggzy.py；本树 artifacts/code 是复制校验过的快照，不自动接管或重启生产任务。本轮使用确定性规则与本地浏览器，不调用大模型。browser-use、Skyvern、ScrapeGraphAI和Firecrawl的部署资料见 [已有爬虫部署树](../local-crawler-agents-20261027/tree.md)，这些框架未参与本次生产采集。
