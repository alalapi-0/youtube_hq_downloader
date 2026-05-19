# 工作流

当前版本主线：

```text
你手动搜索 YouTube 并设置过滤器
  -> 复制搜索结果页 URL
  -> yt-dlp --flat-playlist 提取视频 URL
  -> yt-dlp --dump-single-json 读取 metadata/formats
  -> 本地硬过滤
  -> 本地查重
  -> 导出 review_sheet.csv
```

## 为什么不用 API Key / 大模型

这个项目现在不再调用 OpenRouter，也不要求 YouTube Data API Key。搜索动作由你在 YouTube 页面完成，程序负责批量收集和筛选，避免你一条一条复制视频链接。

## 硬性条件

候选进入审核表前会经过本地硬过滤：

- 必须探测到 `2160p` 或更高格式
- 必须能确认时长不超过 `60` 秒
- 必须能确认发布时间在最近 `730` 天内
- 标题/描述/频道不能包含配置中的负面词，例如 review、unboxing、vlog、behind the scenes、compilation

不符合条件的记录会写入 `rejected.jsonl`。

## 如果 YouTube 要求验证

有时 `yt-dlp` 读取单条视频 metadata 时会遇到 `Sign in to confirm you’re not a bot`。这时可以在控制台选择「设置 Cookie」，启用 `cookies-from-browser chrome` 或手动提供 `cookies.txt`。

Cookie 只用于读取你本机浏览器已经可访问的公开视频页面信息，不用于绕过权限，也不会下载视频。

## 任务目录

所有产物按任务归档到 `output/tasks/task_YYYYMMDD_NNN/`。用户优先查看：

- `review_sheet.csv`
- `review_sheet.md`
- `run_summary.md`
- `rejected.jsonl`
