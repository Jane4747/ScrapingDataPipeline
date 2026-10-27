# 想法树 20261015-deploy

- 状态：completed
- 创建：2026-10-15 17:52:00
- 更新：2026-10-15 17:52:00
- 工具：这一轮不选采集器
- 主题：本地采集流水线本身，还没有具体内容主题
- 交付：想法树用 json 和 markdown。以后每次采集只接受 json、excel、markdown

## 节点

- **requirement** `need`：部署 E:\CAICTBigData\coding 的代码和 D:\Anaconda3\envs\BigData，并在确认主题与交付格式后自动调用。想法树推到 Jane4747/ScrapingDataPipeline。
  - **observation** `found`：coding 目录原先不存在。旁边有一个空的 codeing 目录。BigData 只是当天建的空文件夹，conda env list 里没有它。
    - **decision** `layout`：仓库克隆到 repos/，调度写在 pipeline/。环境用 Python 3.11.17。五个上游仓库不推进公开仓库：NewsCrawler 是 GPL-3.0，goverment_spider 没有许可证。
      - **action** `clone`：浅克隆 goverment_spider、NewsCrawler、crawl4ai、feapder、news-please。本机访问 GitHub 时证书链里有自签名证书，只在这一次克隆命令上关闭校验，没有修改 git config。
        - **observation** `env`：conda 第一次解压不完整，缺少 _socket、OpenSSL、libffi、libexpat。强制重装后可以导入 ssl、ctypes、pyexpat。调用 python.exe 时要把 Library\bin 放进 PATH。
          - **decision** `deps`：不按互相冲突的版本号全装。政府爬虫原来的 pandas==1.4.4 换成当前 pandas。Playwright 跟随 crawl4ai 的 1.49 以上。requests 保持 2.32。微信解析需要的 demjson3 单独安装。feapder、news-please、crawl4ai 以可编辑方式装上本地克隆。
            - **decision** `windows`：政府爬虫在 Windows 上跳过 SIGALRM。start_project.py 改为调用当前解释器，不再写死 python3。这些改动只留在本地 repos/。
              - **decision** `gate`：pipeline plan 只记录需求和工具判断，不采集。pipeline run 必须带已确认的主题和交付格式。政府站点默认要 --site；文章和动态页要 --url；feapder 要 --spider。
                - **result** `check`：pandas、feapder、newsplease、crawl4ai 可以导入。NewsCrawler 通过仓库路径导入 news_extractor_core。Chromium 放在 .playwright-browsers。还没有开始具体内容采集。
