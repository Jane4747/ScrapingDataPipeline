# 代码索引与复用范围

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
