# OpenRouter 设置

Ad URL Scout 默认只使用 OpenRouter。

1. 到 OpenRouter 创建 API Key。
2. 复制 `.env.example`：

```bash
cp .env.example .env
```

3. 填写：

```bash
OPENROUTER_API_KEY=your_openrouter_api_key_here
```

默认模型在 `config/app.yaml`：

```yaml
llm:
  model: google/gemini-2.5-flash
```

如果没有配置 Key，程序不会崩溃，但不会执行在线 URL 寻源任务。当前版本的 URL 搜索只依赖 OpenRouter Web Search。
