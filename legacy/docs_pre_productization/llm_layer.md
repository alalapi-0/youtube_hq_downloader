# LLM 层与设计约束

## 目的
在非破坏的前提下，引入 **语义批闸（candidate filter）**、**检索计划 Planner** 与 **策略优化器**。所有 LLM I/O：

- **走缓存**：哈希键 = `(provider, model, skill_name, prompt_version, input_text)`，`cache/` 下写 `{sha}.meta.json|raw.txt|parsed.json`（已通过 `.gitignore` 阻断提交）。
- **OpenAI-compatible HTTP**：首选 `requests`；若环境中缺少该包 → 退化到标准库 `urllib`。
- **Grok**：`llm_client` **直接拒绝**：一旦 `provider` 设为 `grok/xai`，会抛出可读错误并要求切换 `openrouter`/`openai`；CLI（`plan`/`llm-filter`/`strategy-optimize`）捕获后告警并继续机械链路。

## 技能文件
Markdown 契约位于：

- `skills/query_planner_skill.md`
- `skills/channel_resolver_skill.md`
- `skills/candidate_filter_skill.md`
- `skills/strategy_optimizer_skill.md`

## 解析与重试

- `candidate_filter`：对每个 batch **JSON 只允许失败一次**：首次解析失败后用更硬的 system 后缀再调用一次。
- **`parse_failed` 行**：不会中断整条 JSONL——保留在 `llm_filtered` 中供导出与人工复检。
