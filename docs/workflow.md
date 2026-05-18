# 工作流

当前版本的主线：

```text
自然语言需求
  -> OpenRouter Web Search 查找真实视频 URL
  -> 只保留 Vimeo / YouTube 视频页 URL
  -> 本地查重
  -> 生成结构化 URL 记录
  -> 导出人工审核表
  -> 人工标注
  -> 分析反馈
  -> 生成下一轮搜索建议
```

系统不下载视频文件，也不再使用本地脚本或 yt-dlp 作为搜索兜底。搜索 URL 的唯一在线能力来自 OpenRouter Web Search。

## 任务目录

所有产物按任务归档到 `output/tasks/task_YYYYMMDD_NNN/`。用户优先查看：

- `review_sheet.csv`
- `review_sheet.md`
- `run_summary.md`
- `duplicates.jsonl`

`llm_found_urls.jsonl` 是大模型搜索返回的原始 URL 列表，`candidates_raw.jsonl` 是本地查重后的候选，`final_candidates.jsonl` 是导出审核表时使用的结构化记录。

## 没有 OpenRouter Key

没有 `OPENROUTER_API_KEY` 时，控制台会提示你配置。当前版本没有规则搜索或本地搜索兜底，因此不会继续创建在线寻源任务。
