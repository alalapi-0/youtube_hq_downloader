# Candidate Filter Skill（语义批处理）

## Goal
对已通过**规则闸门**的记录做 **batch 语义过滤**，输出可归因字段（relevant / brand fit / 风险）以支撑导出与工单。

## Hard constraints
1. **批量上限**：单次请求最多 **20** 条；重复调用直至耗尽输入。
2. **描述裁剪**：拼装 prompt 时每条描述截断 **800–1000** Unicode 字符，保留原标题与频道名全文。
3. **解析失败策略**：对同一 batch **最多重试 1 次** JSON 解析；仍失败则该批逐条标记 `llm_status=parse_failed`，**不得抛异常中断管道**。
4. **输出契约**：JSON 对象顶层必须含 `results` 数组；元素必须能根据 `video_id` 对齐。
5. **Provider**：仅支持 OpenAI 兼容端点；**禁止选择 `grok`**（仓库未实现；应在上游报错并降级）。

## Default fields（与 `utils.blank_candidate` 对齐）
写回：`llm_status`、`llm_relevant`、`llm_brand_fit`、`likely_*`、`visual_quality_risk`、`manual_review_priority`、`llm_notes`。
