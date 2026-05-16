# 手工复核指南

导出 Markdown 中包含以下关注点列：

| 字段 | 操作提示 |
|------|---------|
| `needs_resolution_check` | `true` 表示尚未由 `yt-dlp` 实测确认 2160p，仅依赖标题文案或放行策略；需在播放器或抓取工具复核。 |
| `probe_confirmed_4k` | `yt-dlp` 成功抓到 ≥2160 高度，`format_probe_status=ok`。 |
| `resolution_text_evidence_4k` | 文案层出现诸如 `4k / 2160p / UHD`；若与实际格式不符需在规则或人工层面驳回。 |
| `manual_review_status` | workflow 默认为 `pending`；人工确认后建议在 JSONL/csv 中改为 `approved` / `blocked`（后续可再接数据库）。 |
| `manual_review_priority` | `low` / `medium` / `high`，由规则层（分辨率待核、高风险视觉）与 LLM 语义闸共同影响。 |
| `brand` | 通过 `brand_whitelist` 在标题/描述中的弱匹配回填，用于筛选与导出审计。 |
| `llm_status` / `llm_relevant` / `llm_brand_fit` | 语义批闸输出；`skipped` 表示 `--use-llm false`；`parse_failed` 表示 JSON 解析失败但仍保留记录。 |
| `visual_quality_risk` | `low` / `medium` / `high`，结合高风险词表与运动/静物软特征。 |
| `available_format_heights` | `probe-format=ok` 时由 `yt-dlp` 给出的高度列表；与 `probe_confirmed_4k` 交叉验证。 |

## 驳回调参建议

若在 `data/rejected/rule_rejected.jsonl` 或 `data/rejected/llm_rejected.jsonl` 中看到大量误杀：

1. 缩小 `duration` / 更新 `exclude_shorts`。  
2. 调整 `negative_keywords` 短语（避免过长泛化词）。  
3. `max_per_channel` 与 whitelist 条目配合：品牌官方频道往往需要更高配额。  
