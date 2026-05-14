# 端到端工作流（无下载）

1. **`plan`**：把 `search_tasks*.yaml`（或自然语言 `.txt`）编译为嵌套 `search_plan.yaml`。`--use-llm false` → 机械拼装；`--use-llm true` 且配置了 OpenAI/OpenRouter Key → LLM 结构化输出。`provider=grok` 时会直接告警并降级为机械路径（HTTP 客户端未实现）。
2. **`search`**：读取 `search_plan.yaml` 的 `tasks[]` + `global_rules`，关键字在 `keywords` 与 `brands` 间做保守扩展，并尊重 `max_results_per_keyword` 配额，输出 `data/raw/candidates.jsonl`（需 `YOUTUBE_API_KEY`）。
3. **`enrich`**：`videos.list` 回填时长、`definition`、直播信号、`tags`、品牌弱匹配等；无 Key → stderr 告警 + 直通。
4. **`probe-format`**：`yt-dlp` 生成 `available_format_heights`（升序去重）以及 `probe_confirmed_4k`。状态：**`skipped`/`unavailable`/`ok`**——即使 `unavailable` 也会继续链路。
5. **`filter`**：硬阈值（时长/短片/直播/AI/低价/分辨率）+ 频道配额（含 whitelist 加权）+ 高风险视觉打标 → `rule_filtered.jsonl`、`rule_rejected.jsonl`。拒条目带 `rejection_stage=rule`。
6. **`llm-filter`**：批量语义闸（单次 ≤20 条，文本截断）；`parse_failed` 仅标记单行；`llm_relevant=false` → `llm_rejected.jsonl`。
7. **`strategy-optimize`**：聚合 `rule`/`llm` 拒收发 Markdown + YAML 变异计划；`use-llm false` → 启发式。
8. **`export`**：`Markdown` 内含 **生成时间 UTC、阶段计数、被拒统计、4K 统计、类目×优先级直方**，表头含 `brand` / `llm_*` / `visual_quality_risk`。

## Fixture / 冒烟

最小离线验证：

```bash
python -m unittest tests.test_offline_smoke -v
```
