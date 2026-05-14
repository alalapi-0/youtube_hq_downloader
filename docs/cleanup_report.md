## 归档与迁移计划（在执行移动前复核）

以下为与「批量候选 URL sourcing + 元数据 + 规则过滤」新目标不符或已冗余内容的处理方案。**执行移动前请先审阅**，避免误以为文件被凭空删除。

### 计划迁移到 `legacy/old_downloader/`

| 路径 | 原因 |
|------|------|
| `run.py` | 旧的一键 yt-dlp 探测+下载编排入口；本迭代明确 **不下载视频** |
| `scripts/` | 原多平台下载与 plan-cache 套件，已由 `src/` 中的 Data API / 过滤器替代 |
| `urls.txt` | 旧的手工队列输入；新项目由 `search_tasks.yaml`→jsonl 驱动 |
| `requirements-browser.txt` | Playwright/浏览器抓取 token 的附加依赖清单，不再需要 |
| `docs/cache_mechanism_implementation.md` | Plan cache（下载链路）文档，已由新工作流废弃 |
| `docs/download_by_plan_guide.md` | 下载链路操作指南，已由 `docs/workflow.md` 取代 |

### 执行状态（2026-05-14）

已按表格将条目整体搬迁至：

- `legacy/old_downloader/`（内含 `scripts/` 与 `docs_archive/` 中的历史文档）

如需恢复旧的下载链路，请以该目录作为只读归档参考，而不是与新 `src/` 混用同一入口。
