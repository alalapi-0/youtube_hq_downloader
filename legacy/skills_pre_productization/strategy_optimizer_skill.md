# Strategy Optimizer Skill

## Goal
汇总 `rule` / `llm` 两阶段拒收样本，输出 **人类可读摘要** + **变异后的 `search_plan.yaml`**，用于下一轮关键词/品牌/配额迭代。

## Hard constraints
1. **输入契约**：必须可读 JSONL；允许附当前 `search_plan.yaml` 作为对照。
2. **双模式**：
   - `use-llm false`：**启发式**统计 top `rejection_codes`、频道集中度、关键词命中比例，并生成确定性 YAML 变异（浅层：调 `max_results_per_keyword`、复制/删除明显噪声 keyword）。
   - `use-llm true`：在同上统计基础上附加自然语言 rationale；**仍需可解析 YAML**。
3. **缓存**：LLM 调用应走 `llm_cache`（hash 含 skill 名、prompt 版本、聚合指纹）。

## Outputs
- `*.md`：执行摘要 + 建议（非强依赖 LLM）。
- `*.yaml`：完整 `search_plan` 文档树，可直接被 `search` 消费。
