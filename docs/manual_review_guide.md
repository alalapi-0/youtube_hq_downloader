# 手工复核指南

导出 Markdown 中包含以下关注点列：

| 字段 | 操作提示 |
|------|---------|
| `needs_resolution_check` | `true` 表示尚未由 `yt-dlp` 实测确认 2160p，仅依赖标题文案或放行策略；需在播放器或抓取工具复核。 |
| `probe_confirmed_4k` | `yt-dlp` 成功抓到 ≥2160 高度，`format_probe_status=ok`。 |
| `resolution_text_evidence_4k` | 文案层出现诸如 `4k / 2160p / UHD`；若与实际格式不符需在规则或人工层面驳回。 |
| `manual_review_status` | workflow 默认为 `pending`；人工确认后建议在 JSONL/csv 中改为 `approved` / `blocked`（后续可再接数据库）。 |

## 驳回调参建议

若在 `data/rejected/rejected.jsonl` 中看到大量误杀：

1. 缩小 `duration` / 更新 `exclude_shorts`。  
2. 调整 `negative_keywords` 短语（避免过长泛化词）。  
3. `max_per_channel` 与 whitelist 条目配合：品牌官方频道往往需要更高配额。  
