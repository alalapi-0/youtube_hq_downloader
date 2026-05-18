# 高级 CLI

普通用户推荐使用：

```bash
python3 run.py
```

当前 CLI 只保留主流程和人工反馈相关命令：

```bash
python3 -m src.main run-task \
  --request "我要找 Vimeo 上的高端奢侈品官方广告，要求 4K，60 秒以内，发布时间两年内，排除 review 和 unboxing" \
  --max-results 40

python3 -m src.main import-task-feedback \
  --task-dir output/tasks/task_xxx \
  --review-csv output/tasks/task_xxx/review_sheet.csv

python3 -m src.main export-review \
  --analysis output/tasks/task_xxx/url_analysis.jsonl \
  --output-csv output/tasks/task_xxx/review_sheet.csv \
  --output-md output/tasks/task_xxx/review_sheet.md
```

也可以单独导入和分析人工审核结果：

```bash
python3 -m src.main import-review \
  --analysis output/tasks/task_xxx/url_analysis.jsonl \
  --review-csv output/tasks/task_xxx/review_sheet.csv \
  --output output/tasks/task_xxx/manual_reviewed.jsonl

python3 -m src.main analyze-feedback \
  --input output/tasks/task_xxx/manual_reviewed.jsonl \
  --output-md output/tasks/task_xxx/feedback_analysis.md \
  --output-json output/tasks/task_xxx/feedback_analysis.json
```

旧的 YouTube API 搜索、yt-dlp 搜索兜底、格式探测、规则过滤拆分命令已不再作为当前产品入口提供。
