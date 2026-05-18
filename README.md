# Ad URL Scout

**Ad URL Scout 是一个通过 OpenRouter Web Search 寻找广告/商品/品牌视频 URL 的轻量寻源工具。**

它的目标很简单：用户输入自然语言需求，系统让大模型上网搜索 Vimeo / YouTube 等公开视频页面，提取真实 URL，做本地查重，然后导出人工审核表。它不是视频下载器，也不批量下载视频文件。

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
```

当前版本只需要 OpenRouter。没有 `OPENROUTER_API_KEY` 时，程序会启动，但不会执行 URL 寻源任务。

## 推荐用法

1. 运行 `python3 run.py`
2. 选择「开始新的寻源任务」
3. 输入你想找的视频类型
4. 设置本轮最多保留多少个去重 URL
5. 等待生成 `review_sheet.csv`
6. 人工填写 `manual_status`、`manual_reject_reasons`、`manual_notes`
7. 回到控制台导入人工反馈

示例需求：

```text
我要找高端奢侈品官方广告，任意奢侈品牌都可以，优先展示商品，画质要求 4K，排除 AI、review、unboxing、vlog，时长 10 到 180 秒。
```

## 输出在哪里

每次任务都会写入独立目录：

```text
output/tasks/task_YYYYMMDD_NNN/
  user_request.txt
  search_plan.yaml
  llm_found_urls.jsonl
  candidates_raw.jsonl
  duplicates.jsonl
  dedupe_report.json
  url_analysis.jsonl
  final_candidates.jsonl
  review_sheet.csv
  review_sheet.md
  run_summary.json
  run_summary.md
```

普通用户主要看：

- `review_sheet.csv`：人工审核表
- `review_sheet.md`：快速预览
- `run_summary.md`：本轮统计和提醒
- `duplicates.jsonl`：本地查重剔除的 URL

## 高级 CLI

普通用户推荐使用 `python3 run.py`。高级用户可以直接跑：

```bash
python3 -m src.main run-task --request "我要找高端奢侈品官方广告，要求 4K" --max-results 40
python3 -m src.main import-task-feedback --task-dir output/tasks/task_xxx --review-csv output/tasks/task_xxx/review_sheet.csv
```

更多说明见：

- `docs/quick_start.md`
- `docs/workflow.md`
- `docs/openrouter_setup.md`
- `docs/manual_review.md`
- `docs/feedback_loop.md`
- `docs/advanced_cli.md`
- `docs/cleanup_report.md`
