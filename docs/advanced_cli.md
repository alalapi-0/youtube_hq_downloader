# 高级 CLI

普通用户推荐使用：

```bash
python3 run.py
```

高级用户可单独运行步骤：

```bash
python3 -m src.main run-task --request "我要找高端奢侈品官方广告，要求 4K"
python3 -m src.main plan --input examples/user_request.example.txt --output output/search_plan.yaml --use-llm true
python3 -m src.main search --task output/search_plan.yaml --output data/raw/candidates.jsonl
python3 -m src.main analyze-url --input examples/sample_candidates.jsonl --output data/url_analysis/url_analysis.jsonl --offline true
python3 -m src.main filter --input data/enriched/probed.jsonl --output data/filtered/rule_filtered.jsonl --rejected data/rejected/rule_rejected.jsonl
python3 -m src.main export --input data/filtered/llm_filtered.jsonl --format all --output-dir output/
```

高级 Cookie 选项仍保留在 `analyze-url`：

```bash
python3 -m src.main analyze-url --input urls.txt --output output/tasks/manual/url_analysis.jsonl --cookie-file private/cookies.txt
python3 -m src.main analyze-url --input urls.txt --output output/tasks/manual/url_analysis.jsonl --cookies-from-browser chrome
```

Cookie 默认关闭，不会自动读取浏览器数据。
