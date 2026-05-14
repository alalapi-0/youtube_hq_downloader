## 归档与迁移计划（A / B / C）

在执行任何 **删除/大规模搬迁** 前，先按下面分级处理；**不确定是否仍需要的文件 → 一律挪到 `legacy/`** 而不是直接删除。

| 等级 | 含义 | 动作 |
|------|------|------|
| **A** | 与当前「LLM 增强的候选 URL sourcing 管线」直接相关 | 保留在仓库根目录与 `src/`、`config/`、`docs/`、`skills/` |
| **B** | 明确属于旧「多平台 HQ 下载」或其它已废弃目标 | 保留在 `legacy/old_downloader/`（只读参考） |
| **C** | 用途不明 / 可能仍有个别引用 / 需人工二次确认 | **移动到 `legacy/` 子目录**（附 README 说明来源日期），不在主路径引用 |

### A — 保留（当前产品路径）

- `src/`：CLI、`youtube_search`、`metadata_enrich`、`format_probe`、`filters`、`scorer`、`exporters`、LLM 模块与缓存。
- `config/*.yaml`：`search_tasks`、`filter_rules`、`negative_keywords`（含 `high_risk`）、`brand_whitelist`、`channel_whitelist`、`llm_config`、`llm_prompts`。
- `docs/`、`skills/`、`examples/`、`data/**/.gitkeep`、`cache/.gitkeep`。
- `README.md`、`CHANGELOG.md`、`.env.example`、`requirements.txt`。

### B — 已归档（旧下载链路）

| 路径 | 原因 |
|------|------|
| `legacy/old_downloader/run.py` | 旧的一键 yt-dlp 探测+下载编排；本仓库 **不下载视频** |
| `legacy/old_downloader/scripts/` | 多平台下载与 plan-cache |
| `legacy/old_downloader/urls.txt` | 手工队列 |
| `legacy/old_downloader/requirements-browser.txt` | 浏览器抓取依赖 |
| `legacy/old_downloader/docs_archive/*` | 下载链路文档 |

### C — 不确定时的默认策略

- 任何无法确认是否仍被外部脚本引用的根目录杂项、一次性 notebook、旧配置副本：**先复制或移动到 `legacy/misc_<date>/`**，并在该目录放简短 `README.md` 说明由来。
- **本迭代未再发现需 C 级搬迁的根目录文件**；若后续出现，按上表执行。

---

## 历史：计划迁移到 `legacy/old_downloader/`（已完成）

| 路径 | 原因 |
|------|------|
| `run.py` | 旧入口 |
| `scripts/` | 原多平台下载套件 |
| `urls.txt` | 旧输入 |
| `requirements-browser.txt` | 附加依赖 |
| `docs/cache_mechanism_implementation.md` | Plan cache 文档 |
| `docs/download_by_plan_guide.md` | 下载指南 |

### 执行状态（2026-05-14）

已整体搬迁至 `legacy/old_downloader/`。新工作流见 `docs/workflow.md` 与 `README.md`。
