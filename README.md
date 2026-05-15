## YouTube 候选 URL sourcing + LLM 辅助管线（无下载）

本仓库实现 **广告投放 / 品牌营销研究**场景下的端到端链路：Data API → 元数据 →（可选）`yt-dlp` 分辨率签名 → YAML 规则过滤 →（可选）LLM 语义闸 → Markdown/CSV/JSONL 导出。**刻意不落盘音视频**。

仓库同时提供离线 fixture（`data/fixtures`、`examples/`）与单测：`python -m unittest tests.test_offline_smoke -v`。

### 交互式控制台使用方法

中文菜单驱动的薄封装，入口与主 CLI 并存：

```bash
python -m src.console
# 或
python run_console.py
```

- 功能覆盖环境检查、`.env` 合写（`getpass`、尾 4 位提示）、检索任务向导 → `output/search_plan.yaml`、LLM plan、全链路/分步执行、过滤结果与拒收统计、`strategy-optimize`、打开本机目录、文档路径提示。
- `rich` 已写入 `requirements.txt`；若未安装则自动回退纯文本界面。
- 操作摘要写入 `logs/console_runs.log`（不含密钥）。
- **测试建议**：优先在菜单 5 选择「测试模式」或设置环境变量 `DEMO_MAX`/`SKIP_FORMAT_PROBE`；自动化测试请勿批量打 YouTube API，可继续用 `python -m unittest tests.test_offline_smoke tests.test_console_checks -v`（离线 fixture + 最小导入测）。

完整说明见 `docs/console_guide.md`。


### 能力与边界

| 能力 | 说明 |
|------|------|
| `plan` | `search_tasks*.yaml` 或自然语言 `.txt` → 嵌套 `search_plan.yaml`（LLM 可选） |
| `search` | 读取 `search_plan.yaml`，合并 `brands` 扩展关键词，尊重 `global_rules.max_results_per_keyword` |
| `enrich` | `videos.list`；无 Key → 直通 |
| `probe-format` | `yt-dlp` 可选；状态 `skipped` / `unavailable` / `ok`，写出 `available_format_heights` |
| `filter` | 规则 + scorer + 高风险视觉打标 + 频道配额 `rule_*` 输出 |
| `llm-filter` | OpenAI-compatible 批处理；`--use-llm false` 复制并写 `llm_status=skipped` |
| `strategy-optimize` | 聚合 `rule`/`llm` 拒收 → Markdown + 变异 `search_plan` |
| `export` | 统计头 + 直方 + `brand`/`llm_*`/`visual_quality_risk` 列 |

**不支持**：Grok/xAI HTTP（见下文）、多平台下载（旧代码在 `legacy/`）。


### 环境与依赖

```bash
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env   # 写入 YOUTUBE_API_KEY；LLM 相关填 OPENROUTER 或 OPENAI
```

- `yt-dlp` / `requests`：可选增强项；无 `requests` 时 LLM 客户端会自动退回 `urllib`。
- 完全跳过格式探测：`export SKIP_FORMAT_PROBE=1`。


### CLI（在项目根）

```bash
# 1) 生成 search_plan（演示：2 关键字 × quota=3）
python -m src.main plan --input config/search_tasks.demo.yaml --output output/search_plan.yaml --use-llm false

# 2) 检索（需要 YOUTUBE_API_KEY）
python -m src.main search --task output/search_plan.yaml --output data/raw/candidates.jsonl

# 3) enrich → probe-format
python -m src.main enrich --input data/raw/candidates.jsonl --output data/enriched/enriched.jsonl
python -m src.main probe-format --input data/enriched/enriched.jsonl --output data/enriched/probed.jsonl

# 4) 规则过滤
python -m src.main filter \
  --input data/enriched/probed.jsonl \
  --rules config/filter_rules.yaml \
  --output data/filtered/rule_filtered.jsonl \
  --rejected data/rejected/rule_rejected.jsonl

# 5) LLM 语义闸（无 Key → --use-llm false 复制）
python -m src.main llm-filter \
  --input data/filtered/rule_filtered.jsonl \
  --output data/filtered/llm_filtered.jsonl \
  --rejected data/rejected/llm_rejected.jsonl \
  --use-llm false

# 6) （可选）策略优化
python -m src.main strategy-optimize \
  --rule-rejected data/rejected/rule_rejected.jsonl \
  --llm-rejected data/rejected/llm_rejected.jsonl \
  --current-plan output/search_plan.yaml \
  --output-md docs/strategy_notes.md \
  --output-yaml output/search_plan.next.yaml \
  --use-llm false

# 7) 导出
python -m src.main export \
  --input data/filtered/llm_filtered.jsonl \
  --format all \
  --output-dir output/ \
  --rejected-rule data/rejected/rule_rejected.jsonl \
  --rejected-llm data/rejected/llm_rejected.jsonl
```


### Grok / xAI

`config/llm_config.yaml` **不要**设为 `provider: grok`。模块会在访问前抛出可读错误并要求切换到 `openrouter` 或 `openai`。

### 离线样例产物

参阅 `examples/output_sample/export/`、`examples/search_plan.example.yaml`。

### LLM / 过滤器细节

| 文档 | 内容 |
|------|------|
| `docs/workflow.md` | 端到端步骤 |
| `docs/filtering_rules.md` | 规则编号与 scorer |
| `docs/llm_layer.md` | 缓存、providers、失败策略 |
| `docs/manual_review_guide.md` | 导出列与工单提示 |
| `docs/cleanup_report.md` | 归档分级（A/B/C） |

旧版多平台下载器位于 `legacy/old_downloader/`。
