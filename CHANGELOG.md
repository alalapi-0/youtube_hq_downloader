## [2.0.0] - 2026-05-14

### 重大变更（Breaking）

- 项目目标从「多平台 HQ 视频下载工具」重写为「YouTube **候选链接批量采集 → 元数据增强 → （可选）格式探测 → 规则过滤 → 多格式导出**」链路；**本迭代不包含任何二进制视频下载**。旧代码整体移至 `legacy/old_downloader/`（详见 `docs/cleanup_report.md`）。

### Added

- `src/` 下的 CLI：`search` / `enrich` / `probe-format` / `filter` / `export`。  
- YAML 配置文件：`search_tasks`、`filter_rules`、`negative_keywords`、`brand_whitelist`、`channel_whitelist`。  
- 标准化的 jsonl Candidate schema 与 Markdown/CSV/jsonl exporter（含 QA 计数头）。  

### Operational

- 通过 `.env` + `python-dotenv` 提供 `YOUTUBE_API_KEY`；无 Key 时 `enrich` 将直通告警而不中断后续演示。
