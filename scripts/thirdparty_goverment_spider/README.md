# 北京两条官方线：goverment_spider 站点脚本

`repos/` 目录被 `.gitignore` 排除，所以这里保留**受版本管理的正本**；实际运行时脚本必须放在
`repos/goverment_spider/` 下（该库通过相对路径读 `key_words.txt`、写 `files/`、`xls_files/`）。

## 部署

```powershell
$repo = "E:\CAICTBigData\coding\repos\goverment_spider"
Copy-Item .\scripts\thirdparty_goverment_spider\site_fetch.py $repo -Force
Copy-Item .\scripts\thirdparty_goverment_spider\1600004.*.py $repo\codes -Force
Copy-Item .\scripts\thirdparty_goverment_spider\1600005.*.py $repo\codes -Force
```

## 运行（经 runner，不直接调脚本）

```powershell
$py = "D:\Anaconda3\envs\BigData\python.exe"
& $py -B -m pipeline run --tree-id <tree> --theme "..." --delivery json `
    --site 北京市政府采购网 --start-date 2026-10-27
& $py -B -m pipeline run --tree-id <tree> --theme "..." --delivery json `
    --site 北京公共资源交易平台 --start-date 2026-10-27
```

`--site` 按文件名子串匹配 `codes/*.py`，所以这两个脚本的序号和关键词不要和库内其它脚本重名。
`--all-sites` 会把 140 多个站点全跑一遍，与本任务无关，不要用。

## 三个脚本的关键差异

| | 1600004 政采网 | 1600005 公资平台 | 1600006 全国平台 |
|---|---|---|---|
| 入口 | `http://www.ccgp-beijing.gov.cn`（443 端口 TCP 不通，80 可通） | `https://ggzyfw.beijing.gov.cn`（国密 SM2 TLS） | `https://www.ggzy.gov.cn`（POST 接口，见下） |
| 翻页 | `A002004001002index_N.htm` | `index_N.html` | 接口参数 `PAGENUMBER` |
| 取页 | requests 直连即可 | 必须走系统 TLS 栈，requests 会 `SSL: BAD_ECPOINT` | POST `/information/...`（近一年，本机 404）与 `/his/information/...`（历史，code 400）双接口，WAF 间歇拦 API 路径 |

1600006 状态（2026-10-28）：接口契约完整、脚本可运行且失败留痕，但两接口均未取得 `code=200`，详见
`docs/medical-digital-tender-validation-20261028/national-ggzy-20261028/report.md`。

## 输出

- 5 列 TSV（部门名称/类型/标题/日期/链接）：`repos/goverment_spider/files/<年月>/<日期>/市级/<部门名>.txt`
- 同名 `.json` 旁证：项目编号、采购人、中标供应商、金额、失败明细（runner 只读 `*.txt`，JSON 不影响导出）

## 合规边界

- 只采公开公告页；robots.txt 两站均为 404（无规则）。
- UA 自报 `CAICTMedicalResearchBot/1.0 (public-source research)`，不伪装浏览器。
- 证书一律校验；`site_fetch` 没有关闭校验的开关，`curl=60` 按失败抛出。
- 同站点请求间隔 ≥1.2 秒，单栏目默认 2 页。
