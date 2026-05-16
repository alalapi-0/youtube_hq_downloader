# Query Planner Skill

## Goal
Compile a **structured `search_plan.yaml`**（`project`、`global_rules`、`duration`、`resolution`、`positive_negative_keywords`、`tasks[]`），使后续 `search` 能在**不手写嵌套 YAML**的前提下稳定消费。

## Hard constraints
1. **只输出合法 YAML**：禁止 Markdown 代码围栏；顶层键名固定，勿发明未约定字段 unless nested under `notes`（可选）。
2. **任务粒度**：每条 `tasks[]` 必须含 `keywords`、`brands`、`preferred_channels`、`max_results_per_keyword`、`region_code`、`relevance_language`。
3. **配额保守**：在无显式商务理由时，`max_results_per_keyword` ≤ 用户模板或上层 `global_rules.max_results_per_keyword`。
4. **离线回退**：当未配置 LLM Key 或非 `plan --use-llm true`，本 skill 不参与；CLI 仅从 `search_tasks*.yaml` 机械合并生成计划。

## Optional LLM behaviors
- 若用户提供自然语言 `examples/user_request.example.txt`，LLM planner 应将意图映射到 **可检索关键词短语**（非整句）。
- **避免**编造具体 `channel_id`；`preferred_channels` 仅填充显式给定或高置信别名。
