2026物理与具身RSI文献采集
=======================

入口：outputs/physical-embodied-rsi-20261025/architecture_report.html
范围：首次提交于2026-01-01至2026-10-25的精选arXiv论文。
RSI按Recursive Self-Improvement解释；physical按物理智能/机器人解释。
这不是全年穷尽检索，论文实验没有自行复现。

文件
----
collector.py                  元数据核验、固定版本PDF下载、逐页抽取、目录与BibTeX
rsi_2026.json                 本次版本1任务；相对输出路径以任务文件所在目录解析
architecture_notes.json       来源陈述、证据边界与工程推断分开的逐篇笔记
build_report.py              生成本地可筛选报告和结构化架构分析
verify.py                    离线核对PDF/文本/元数据哈希、年份、页数与arXiv版本
test_collector.py             使用假网络与临时目录的8项测试
run.ps1                      复用库内Python配置的Windows入口

在 E:\CAICTBigData\coding 中运行
--------------------------------
# 校验任务，无网络、无输出文件
.\literature\run.ps1 -Spec literature\rsi_2026.json -DryRun

# 继续本次任务；成功且PDF/文本哈希一致的记录不重复下载
.\literature\run.ps1 -Spec literature\rsi_2026.json -Resume

# 新研究：复制任务，修改task_id、output_dir、候选与截止日，再先DryRun。
# 首次执行不加Resume。不要直接更改已有任务后继续下载。

脚本会依次选择SCRAPING_PYTHON、库内.runtime.json中的python、PATH中的python；
不安装依赖。基础依赖复用requirements-research.txt中的requests、beautifulsoup4、pypdf。

底层Python调用（Python必须能导入本库pipeline）
--------------------------------------------
python -B literature/collector.py --spec literature/rsi_2026.json --dry-run --json
python -B literature/collector.py --spec literature/rsi_2026.json --resume --json
python -B -m unittest discover -s literature -p test_collector.py -v
python -B literature/verify.py --root outputs/physical-embodied-rsi-20261025
python -B literature/build_report.py --root outputs/physical-embodied-rsi-20261025

返回0表示所选阶段执行完成；采集部分失败返回3；参数或执行错误返回2。
标准输出为JSON，逐篇进度写标准错误。
不删除collection.lock强行续跑；先检查原进程是否仍在运行。
成功缓存按PDF和文本哈希检查；固定版本内容不一致时拒绝覆盖。
修复被损坏的本地归档时应另建任务/目录，保留旧归档。

检索与口径
----------
本次搜索由Codex联网工具实际执行，关键词和来源记录在任务及输出的search_log.json。
collector本身不是搜索引擎，不会把queries当成已经搜索；也不调用收费API。
候选从arXiv与作者维护的Physical RSI目录发现，后续核验官方元数据。
扩展候选：将现代arXiv ID（如2602.12063，不带v后缀）加入新任务candidates；
每项可填category、reason、discovery_url。程序按ID去重。
最终年份来自citation_date，不根据编号、抓取时间、URL年份或修订年推断。
版本从官方submission history选择不晚于cutoff的最高版本。
当前metadata来自抓取时的摘要页；若用于历史回溯，应核对选定旧版本的标题和摘要。
本次截止日与检索日相同，不涉及该回溯问题。

复用边界
--------
下载复用pipeline.research.fetch.Fetcher，而非复制医疗部署的语义筛选规则。
只访问arxiv.org摘要/PDF；遵守robots和至少15秒间隔、TLS、响应体积与重定向检查。
单份上限128MiB；单任务最多100个候选；串行请求。
公开下载并不改变原论文版权或许可；metadata记录可获得的license_url。
text_status/text_warning表示抽取结果；扫描页不进行OCR。
不执行下载内容中的指令，不安装论文仓库代码，不控制机器人。
架构报告是调研产物，未实现报告中的采摘机器人架构。

