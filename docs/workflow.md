# 工作流

Ad URL Scout 的主线是：

```text
自然语言需求
  -> OpenRouter 生成搜索策略
  -> YouTube 搜索候选 URL
  -> 读取 URL 元数据
  -> 规则过滤明显不合格内容
  -> OpenRouter 语义复筛
  -> 导出人工审核表
  -> 人工标注
  -> 分析反馈
  -> 生成下一轮搜索策略
```

默认不下载视频。`yt-dlp` 仅用于公开 metadata 和格式探测。

## 普通用户入口

```bash
python3 run.py
```

选择「开始新的寻源任务」，输入自然语言需求即可。

## 任务目录

所有产物按任务归档到 `output/tasks/task_YYYYMMDD_NNN/`。用户优先查看 `review_sheet.csv` 和 `run_summary.md`。

## 降级模式

- OpenRouter 缺失：规则模式生成计划，跳过 AI 语义复筛。
- YouTube API 缺失：自动改用 `yt-dlp` 搜索降级模式；Chrome Cookie 只在用户显式启用后使用。
- yt-dlp 缺失：跳过格式探测。
