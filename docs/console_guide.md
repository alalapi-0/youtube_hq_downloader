# 交互式控制台指南

本文档介绍仓库根目录下 **YouTube URL 寻源控制台** 的设计、菜单与推荐工作流。对应主 CLI 仍为 `python -m src.main`（本控制台为其薄封装）。

## 1. 设计原则

- **薄封装**：优先直接调用 `src/main.py` 中的 `cmd_*` 与项目内模块，避免多余子进程。
- **安全**：不在日志或屏幕上打印完整 API Key；输入使用 `getpass`；写入后仅展示尾 4 位提示。
- **可审计**：操作写入 `logs/console_runs.log`（不含密钥），记录命令意图、路径与成败摘要。
- **依赖**：安装 `rich` 可获彩色面板；未安装时自动回退纯文本菜单（`ImportError` / 缺失兼容）。

## 2. 启动方式

```bash
cd /path/to/youtube_hq_downloader
python -m pip install -r requirements.txt
python -m src.console
# 或
python run_console.py
```

## 3. 主菜单（0–11）

| 编号 | 功能 |
|------|------|
| 0 | 退出 |
| 1 | 环境检查 |
| 2 | API 密钥向导 |
| 3 | 检索任务向导 → `output/search_plan.yaml` |
| 4 | LLM 检索计划（自然语言 / 示例 / 自定义路径） |
| 5 | 一键流水线（测试/生产双确认） |
| 6 | 分步运行（可先行编辑 YAML 配置） |
| 7 | 查看 `rule_filtered` / `llm_filtered` |
| 8 | 拒收统计 + 可选导出 `output/markdown/rejected_summary.md` |
| 9 | `strategy-optimize`（会话 `llm_enabled` 影响默认） |
| 10 | 打开 `output/`、`data/` 等目录（macOS `open`/Windows `explorer`/Linux `xdg-open`） |
| 11 | 打印文档绝对路径 |

## 4. 关键路径（与 CLI 对齐）

| 阶段 | 路径 |
|------|------|
| 检索计划 | `output/search_plan.yaml` |
| 原始候选 | `data/raw/candidates.jsonl` |
|  enrich | `data/enriched/enriched.jsonl` |
|  probe | `data/enriched/probed.jsonl` |
| 规则过滤通过 | `data/filtered/rule_filtered.jsonl` |
| LLM 过滤通过 | `data/filtered/llm_filtered.jsonl` |
| 规则拒收 | `data/rejected/rule_rejected.jsonl` |
| LLM 拒收 | `data/rejected/llm_rejected.jsonl` |
| 导出 | `output/csv/`, `output/jsonl/`, `output/markdown/` |
| 策略产物 | `docs/strategy_notes.md`, `output/search_plan.next.yaml` |

## 5. 环境检查（菜单 1）

检查项包括：Python 版本、`googleapiclient`/PyYAML/可选依赖、`yt-dlp` 是否在 `PATH`、`.env` 是否存在（各键masked）、YAML 与目录是否存在、`.gitignore` 是否包含 `.env`。

## 6. API 密钥向导（菜单 2）

子菜单：

1. `YOUTUBE_API_KEY`
2. `OPENROUTER_API_KEY`
3. `OPENAI_API_KEY`
4. 自 `.env.example` **补齐缺失键**（不覆盖已有值）
5. 返回

`.env` 缺失时会从 `.env.example` 复制骨架，再按行合并/追加键。

## 7. 检索任务向导（菜单 3）

1. `config/search_tasks.demo.yaml`（小流量演示）
2. `config/search_tasks.yaml`
3. 交互式单任务：可选 `brand_whitelist.yaml` 品类 → 注入品牌 → 关键词 → 区划/语言 → `max_results_per_keyword`（默认 3）
4. 自定义 `search_tasks*.yaml` 相对路径
5. 返回

输出统一写入 `output/search_plan.yaml` 并给出粗估检索上限。

## 8. LLM 计划（菜单 4）

- 可选 LLM 增强（二次确认后调用 API）。
- 输入来源：多行文本（`END` 结束）、`examples/user_request.example.txt` 或自定义路径。
- 内部写入 `output/_console_user_request.txt` 再调用 `cmd_plan`。
- 可预览生成 YAML 前 40 行。

## 9. 一键流水线（菜单 5）

顺序：`search → enrich → probe-format → filter → llm-filter → export`。

- **测试模式**：对现有 `output/search_plan.yaml` 生成临时 capped 计划（默认每关键词 `max(DEMO_MAX,3)`，`DEMO_MAX` 环境变量可覆盖）。
- **生产模式**：双重确认后使用原始配额。
- `search` / LLM 相关步骤前单独确认，避免误触配额。

## 10. 分步运行（菜单 6）

可选先进入 **YAML 配置编辑器**（`filter_rules.yaml` / `llm_config.yaml`）：自动 `.bak` 备份 + roundtrip 校验。

支持从任意中间步骤开始（`search` 起始默认），自定义输入路径回退交互。

## 11. 查看过滤结果（菜单 7）

打印 `rule_filtered.jsonl` / `llm_filtered.jsonl` 绝对路径，预览前若干 JSON 行；若 `pandas` 可用则附表格 `head()`。

## 12. 拒收统计（菜单 8）

聚合 `rule_rejected.jsonl` 与 `llm_rejected.jsonl` 行数及 `rejection_codes` 分布 Top 25。

可选导出：`output/markdown/rejected_summary.md`（若目录中已有同名 markdown 仍遵循 `.gitignore` 策略；该文件通常被忽略但便于本地复盘）。

## 13. 策略优化（菜单 9）

调用 `strategy-optimize`：

- `--rule-rejected data/rejected/rule_rejected.jsonl`
- `--llm-rejected data/rejected/llm_rejected.jsonl`
- `--current-plan output/search_plan.yaml`（存在时）
- `--output-md docs/strategy_notes.md`
- `--output-yaml output/search_plan.next.yaml`
- `--use-llm` 由会话偏好与即时确认共同决定。

## 14. 打开目录（菜单 10）

快捷打开 `output/`、`data/`、`config/`、`docs/`、`logs/` 或自定义相对路径；失败时打印绝对路径供手动粘贴。

## 15. 帮助（菜单 11）

列出 `docs/console_guide.md`、`docs/workflow.md`、`docs/filtering_rules.md`、`docs/llm_layer.md`、`docs/manual_review_guide.md` 与 `README.md` 的路径。

## 16. YAML 配置编辑器

由分步菜单首问触发；或阅读本节的模块 `src/console_config_editor.py`：备份 → 外部编辑 → 回车校验 YAML roundtrip。

## 17. 日志

- 路径：`logs/console_runs.log`
- 内容：UTC 时间戳 + 单行摘要（裁剪长度，无密钥）。

## 18. 会话状态

`ConsoleSession`（内存）保存：

- `llm_enabled` 偏好
- 最近一次 `search_plan` / 过滤产物路径引用（可选）

## 19. 测试与 CI 注意

- **勿在自动化测试中批量调用 YouTube Data API**：离线烟测请继续用 `python -m unittest tests.test_offline_smoke -v`（fixture 链路）。
- 控制台最小导入测：`tests/test_console_checks.py`（`import src.console_checks`）。

## 20. 故障排除

- **缺少检索计划**：先用菜单 3/4 生成 `output/search_plan.yaml`。
- **`rich` 不可用**：功能等价，仍为中文菜单循环。
- **`strategy-optimize` 失败**：检查拒收 JSONL 是否存在；或改用 `--use-llm false`。

## 21. 与主 CLI 的对照表

| 控制台意图 | 等价 CLI |
|------------|----------|
| 机械 plan | `python -m src.main plan --input config/search_tasks.demo.yaml --output output/search_plan.yaml --use-llm false` |
| search | `python -m src.main search --task output/search_plan.yaml --output data/raw/candidates.jsonl` |
| enrich | `python -m src.main enrich --input ... --output ...` |
| probe | `python -m src.main probe-format --input ... --output ...` |
| filter | `python -m src.main filter --input ... --rules config/filter_rules.yaml --output ... --rejected ...` |
| llm-filter | `python -m src.main llm-filter --input ... --output ... --rejected ... --use-llm true|false` |
| export | `python -m src.main export --input ... --format all --output-dir output/ --rejected-rule ... --rejected-llm ...` |
| strategy | `python -m src.main strategy-optimize --rule-rejected ... --llm-rejected ... --current-plan ... --output-md ... --output-yaml ...` |

以上命令均 **不涉及视频下载**；流水线设计即为 URL/元数据/规则/LLM/导出。
