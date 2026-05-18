## [4.0.0] - 2026-05-18

### Changed

- 主流程收敛为 OpenRouter Web Search URL 寻源 + 本地查重 + 人工审核表。
- 当前入口不再提供拆分式旧搜索链路。
- 配置进一步精简为 `config/app.yaml` 和 `config/labels.yaml`。
- 旧搜索、补全、过滤、导出和示例迁移到 `legacy/`。

## [3.0.0] - 2026-05-16

### Changed

- 项目重命名并产品化为 **Ad URL Scout / ad-url-scout**。
- 普通用户入口改为 `python run.py`，默认走 OpenRouter-first 主流程。
- 输出按 `output/tasks/task_*/` 组织。
- 配置精简为 `config/app.yaml`、`config/filters.yaml`、`config/brands.yaml`、`config/labels.yaml`。
- 旧配置、旧文档、旧控制台和旧技能说明移动到 `legacy/`。
- README 重写，明确本项目不是视频下载器。

### Added

- `src/core/pipeline.py` 统一主流程。
- `src/llm/openrouter_client.py` OpenRouter-only 客户端。
- 新产品控制台 `src/console/`。

## [2.1.0] - 2026-05-14

### Added

- `plan`/`llm-filter`/`strategy-optimize` 子命令与完整 `skills/`、`config/llm_*.yaml`。
- LLM 客户端 + `cache/` 指纹缓存（不入库）。
- `search_plan` 嵌套结构、`brands` 扩展检索词、候选 schema 扩展（`brand`、`description_snippet`、`live_broadcast_content`、`available_format_heights`、`llm_*`、`likely_*`、`visual_quality_risk`、`manual_review_priority`、`error` 等）。
- `examples/` 与 `unittest` 离线冒烟。

### Changed

- `filter`/`export`/`probe-format` 升级：高风险视觉打标、`unavailable` 探测状态、导出统计头与直方刷新。

## [2.0.0] - 2026-05-14

### Breaking

- 项目目标重写为候选链接管线；不包含视频下载。

### Added

- 基础 CLI、`config/*.yaml`、`src/` exporters、legacy 归档。
