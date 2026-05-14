# 工作流总览（无下载）

1. **`search`**：读取 `config/search_tasks.yaml`，用 YouTube Data API `search.list` 按关键词抓取候选条目，写入 `data/raw/candidates.jsonl`。
2. **`enrich`**：对每条记录批量调用 `videos.list` 回填时长、清晰度、是否为直播等信息，补齐标题/描述的 4K 文本口径信号并输出 `data/enriched/enriched.jsonl`。若 `.env` 中缺少 API Key，会 **告警并直通复制** JSONL。
3. **`probe-format`**（可选）：对每个 `canonical_url` 调用系统中的 `yt-dlp --skip-download` + JSON dump，尽最大努力识别是否具备 **2160p/4K**；若无 `yt-dlp`、或导出 `SKIP_FORMAT_PROBE=1`，则写入 `skipped` 且流程不阻断。
4. **`filter`**：结合 `filter_rules.yaml`、正向品牌词、`negative_keywords.yaml` AI/低价值词表与 `channel_whitelist.yaml`（频道条目上限豁免）等进行硬过滤，输出 `filtered` / `rejected` 两段 JSONL。
5. **`export`**：读取通过过滤的记录，导出 `filtered_urls.csv` / `.jsonl` / `.md`，Markdown 中包含统计信息与评审列。
