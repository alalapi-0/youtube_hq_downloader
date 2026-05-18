# 快速开始

Ad URL Scout 当前主线只做一件事：用 OpenRouter Web Search 根据你的自然语言需求寻找公开视频 URL，然后做本地查重并导出人工审核表。

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
python3 run.py
```

打开 `.env`，填写：

```bash
OPENROUTER_API_KEY=your_openrouter_api_key_here
```

然后在控制台选择「开始新的寻源任务」，输入需求，例如：

```text
我要找高端奢侈品官方广告，任意奢侈品牌都可以，优先展示商品，排除 AI、review、unboxing、vlog，时长 10 到 180 秒，画质要求 4K。
```

任务完成后打开：

```text
output/tasks/task_xxx/review_sheet.csv
```

填写人工审核字段后，回到控制台选择「导入人工审核反馈」。
