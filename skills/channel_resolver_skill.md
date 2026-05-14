# Channel Resolver Skill

## Goal
把模糊渠道线索（别名、不完整标题、中英文混写）映射到 **`channel_id` 或可追溯的 `channel_title`**，供离线人工校验或下游 API 复查。

## Hard constraints
1. **不调用 YouTube Browse/非官方接口**进行自动确认；resolver 只允许 LLM JSON 结构化猜测 + `confidence` 分数。
2. **输出必须为 JSON**：`{"matches":[{"hint","channel_id","channel_title","confidence"}]}`；缺字段时用空字符串/nullable 明确标注。
3. **默认不接 CLI**：实现为可导入函数；只有当上层编排显式调用时才运行。

## Quality bar
- `confidence < 0.35` → 视作不可信；要求人工校对或跳过写入 `preferred_channels`（仅记录于 sidecar）。
