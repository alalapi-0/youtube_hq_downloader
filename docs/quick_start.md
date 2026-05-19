# 快速开始

Ad URL Scout 当前主线只做一件事：把你手动调好的 YouTube 搜索结果页批量转成候选视频 URL，并做本地硬筛选。

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 run.py
```

## 使用

1. 打开 YouTube。
2. 搜索品牌或关键词，例如 `Dior commercial 4K`。
3. 使用 YouTube 页面里的过滤器。
4. 复制地址栏中的搜索结果页 URL。
5. 回到控制台粘贴 URL，最后输入 `END`。

程序不会下载视频文件，只会通过 `yt-dlp` 读取公开视频元数据和格式列表。
