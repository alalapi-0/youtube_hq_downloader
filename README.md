# Ad URL Scout

**Ad URL Scout 是一个 AI 增强的广告/商品/品牌视频 URL 寻源工具。**

它默认不下载视频，只收集公开视频 URL 和页面/元数据，用于帮助用户快速筛选高质量候选视频。它不是视频下载器，不是通用爬虫，也不是批量下载工具。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
python3 run.py
```

在 `.env` 中填写：

```bash
OPENROUTER_API_KEY=your_openrouter_api_key_here
YOUTUBE_API_KEY=optional_youtube_api_key_here
```

OpenRouter 用于 AI 搜索计划、语义复筛和反馈分析。YouTube API 是可选项；未配置时，系统会自动尝试 `yt-dlp` 搜索降级模式，不会下载视频。

## 推荐用法

1. 运行 `python3 run.py`
2. 选择「开始新的寻源任务」
3. 输入自然语言需求
4. 等待生成 `review_sheet.csv`
5. 人工填写 `manual_status`、`manual_reject_reasons`、`manual_notes`
6. 回到控制台导入人工反馈
7. 生成下一轮搜索策略

示例需求：

```text
我要找高端奢侈品官方广告，优先 Dior、Prada、Chanel、Gucci，排除 AI、review、unboxing、vlog，时长 20-180 秒，要求 4K。
```

## 输出在哪里

每次任务都会写入独立目录：

```text
output/tasks/task_YYYYMMDD_NNN/
  user_request.txt
  search_plan.yaml
  candidates_raw.jsonl
  url_analysis.jsonl
  rule_filtered.jsonl
  llm_filtered.jsonl
  final_candidates.jsonl
  rejected.jsonl
  review_sheet.csv
  review_sheet.md
  run_summary.json
  run_summary.md
```

普通用户主要看：

- `review_sheet.csv`
- `review_sheet.md`
- `run_summary.md`

## 没有 Key 会怎样

- 没有 `OPENROUTER_API_KEY`：AI 搜索计划和语义筛选不可用，系统会提示配置，也允许规则模式继续。
- 没有 `YOUTUBE_API_KEY`：自动改用 `yt-dlp` 搜索降级模式；可在设置中显式启用 Chrome Cookie 辅助读取你本机已可访问的页面信息。
- 没有 `yt-dlp`：跳过 4K 格式探测，只使用已有 metadata 和文本证据。

## 人工反馈

填完审核表后，在控制台选择「导入人工审核反馈」。系统会：

1. 合并人工标签
2. 统计通过率和拒绝原因
3. 分析高价值关键词/频道/品牌
4. 生成 `next_search_plan.yaml`

## 高级 CLI

普通用户不需要使用这些命令。高级用户仍可运行：

```bash
python3 -m src.main plan
python3 -m src.main search
python3 -m src.main analyze-url
python3 -m src.main filter
python3 -m src.main export
python3 -m src.main run-task
```

详见 `docs/advanced_cli.md`。

## 文档

- `docs/quick_start.md`
- `docs/openrouter_setup.md`
- `docs/workflow.md`
- `docs/manual_review.md`
- `docs/feedback_loop.md`
- `docs/advanced_cli.md`
- `docs/cleanup_report.md`
