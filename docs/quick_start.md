# 快速开始

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
YOUTUBE_API_KEY=optional_youtube_api_key_here
```

`YOUTUBE_API_KEY` 可以留空。留空时系统会尝试使用 `yt-dlp` 搜索和读取公开元数据；如果你需要使用本机 Chrome 已登录状态，可在控制台「设置」里显式启用 Chrome Cookie。

然后在控制台选择「开始新的寻源任务」，输入自然语言需求。

任务完成后打开：

```text
output/tasks/task_xxx/review_sheet.csv
```

填写人工审核字段后，回到控制台选择「导入人工审核反馈」。
