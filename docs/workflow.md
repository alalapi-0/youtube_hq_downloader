# 工作流

当前版本的主线：

```text
自然语言需求
  -> OpenRouter Web Search 查找真实视频 URL
  -> 只保留 Vimeo 视频页 URL
  -> Vimeo oEmbed 补全公开标题/描述/时长/上传日期
  -> 硬性条件过滤
  -> 本地查重
  -> 生成结构化 URL 记录
  -> 导出人工审核表
  -> 人工标注
  -> 分析反馈
  -> 生成下一轮搜索建议
```

系统不下载视频文件，也不再使用本地脚本或 yt-dlp 作为搜索兜底。搜索 URL 的唯一在线能力来自 OpenRouter Web Search，且当前只允许 `vimeo.com` 视频页进入结果。搜索完成后会尝试读取 Vimeo 公开 oEmbed 元数据，这一步不需要 Cookie 或 API Key，也不消耗 OpenRouter token。

## 硬性条件

候选 URL 进入人工审核表前会经过硬闸门：

- 必须是 `vimeo.com` 视频页
- 必须有 4K / 2160p / UHD 证据
- 必须能确认时长不超过 60 秒
- 必须能确认发布时间在最近两年内
- 必须能看到广告/商业片特征，例如 `advertisement`、`commercial`、`campaign`、`product film`、`Agency:`、`Creative Director`、`Art Director`、`Director:`、`Production Company:`、`DOP`、`Editor:`、`Colorist`、`Post:`、`VFX`

缺少任一证据时会被丢弃，原因会写入任务目录的 `rejected.jsonl` 和 `run_summary.md`。

## 任务目录

所有产物按任务归档到 `output/tasks/task_YYYYMMDD_NNN/`。用户优先查看：

- `review_sheet.csv`
- `review_sheet.md`
- `run_summary.md`
- `duplicates.jsonl`

`llm_found_urls.jsonl` 是大模型搜索返回的原始 URL 列表，`candidates_raw.jsonl` 是本地查重后的候选，`final_candidates.jsonl` 是导出审核表时使用的结构化记录。

## 没有 OpenRouter Key

没有 `OPENROUTER_API_KEY` 时，控制台会提示你配置。当前版本没有规则搜索或本地搜索兜底，因此不会继续创建在线寻源任务。
