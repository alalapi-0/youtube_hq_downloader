# Ad URL Scout

**Ad URL Scout 是一个 YouTube 搜索结果页 URL 采集与 4K 筛选工具。**

它不需要 OpenRouter，不需要 YouTube API Key，也不是视频下载器。你在 YouTube 手动搜索并设置过滤器后，只需要复制搜索结果页 URL，程序会用 `yt-dlp` 批量提取视频链接、读取公开视频元数据、探测可用格式，并在本地筛掉不符合要求的候选。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 run.py
```

当前版本不需要填写 `.env`。

## 推荐用法

1. 在 YouTube 搜索品牌或关键词。
2. 手动设置 YouTube 过滤器，例如 4K、上传日期、时长等。
3. 复制浏览器地址栏里的搜索结果页 URL。
4. 运行 `python3 run.py`。
5. 选择「从 YouTube 搜索结果页采集 URL」。
6. 粘贴一个或多个搜索结果页 URL，最后输入 `END`。
7. 等待生成 `review_sheet.csv`。

程序会自动执行：

```text
YouTube 搜索结果页 URL
  -> yt-dlp flat playlist 提取视频 URL
  -> yt-dlp 读取 metadata 和 formats，不下载视频
  -> 本地过滤 2160p / 60 秒以内 / 两年内 / 负面词
  -> 本地查重
  -> 导出人工审核表
```

如果 YouTube 返回 `Sign in to confirm you’re not a bot`，可以在控制台选择「设置 Cookie」，启用 Chrome Cookie 或手动指定 `cookies.txt`。Cookie 只用于读取你本机已可访问的公开视频信息，不下载视频。

## 输出在哪里

每次任务都会写入独立目录：

```text
output/tasks/task_YYYYMMDD_NNN/
  search_pages.txt
  collected_urls.jsonl
  candidates_raw.jsonl
  duplicates.jsonl
  dedupe_report.json
  url_analysis.jsonl
  filtered.jsonl
  final_candidates.jsonl
  rejected.jsonl
  review_sheet.csv
  review_sheet.md
  run_summary.json
  run_summary.md
```

普通用户主要看：

- `review_sheet.csv`：人工审核表
- `review_sheet.md`：快速预览
- `run_summary.md`：本轮统计和提醒
- `rejected.jsonl`：被 4K、时长、日期、负面词规则剔除的 URL

## 高级 CLI

```bash
python3 -m src.main collect \
  --search-url "https://www.youtube.com/results?search_query=Dior+commercial+4K" \
  --max-entries 80

python3 -m src.main collect \
  --search-url-file examples/search_pages.example.txt
```

更多说明见：

- `docs/quick_start.md`
- `docs/workflow.md`
- `docs/manual_review.md`
- `docs/feedback_loop.md`
- `docs/advanced_cli.md`
