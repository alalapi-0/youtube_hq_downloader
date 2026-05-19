# 高级 CLI

普通用户推荐使用：

```bash
python3 run.py
```

直接采集一个 YouTube 搜索结果页：

```bash
python3 -m src.main collect \
  --search-url "https://www.youtube.com/results?search_query=Dior+commercial+4K" \
  --max-entries 80
```

批量导入多个搜索结果页：

```bash
python3 -m src.main collect \
  --search-url-file examples/search_pages.example.txt \
  --max-entries 80
```

导入人工反馈：

```bash
python3 -m src.main import-task-feedback \
  --task-dir output/tasks/task_xxx \
  --review-csv output/tasks/task_xxx/review_sheet.csv
```

重新导出审核表：

```bash
python3 -m src.main export-review \
  --analysis output/tasks/task_xxx/url_analysis.jsonl \
  --output-csv output/tasks/task_xxx/review_sheet.csv \
  --output-md output/tasks/task_xxx/review_sheet.md
```
