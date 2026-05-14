## YouTube 候选 URL sourcing + 元数据管线

本仓库聚焦于 **广告投放 / 品牌 / 产品类视频的前期发现链路**：在海量搜索结果中抓取 **YouTube watch URL**，补全公开的元数据并根据 YAML 配置的规则完成过滤与加权排序，再通过 CSV / JSON Lines / Markdown 输出给人工再审或接入下游工单系统。**当前版本刻意不包含任何音视频文件下载**，以符合批量合规审计与成本控制需求。

---

### 能力与边界

| 能力 | 说明 |
|------|------|
| 关键词批量搜索 | Data API `search.list`，任务定义于 `config/search_tasks.yaml`。 |
| 元数据回填 | Data API `videos.list` → 时长 / 清晰度标签 / Live 信号 / Tags 等。 |
| （可选）4K 实锤 | 若系统安装了 `yt-dlp`，可对 URL 做一次 `--skip-download` JSON probe；否则写入 `skipped` 并保持流程可继续。 |
| 规则筛选 & 加权 | YAML 粒度控制时长 / Shorts / 直播 / AI 词 / 低价值词 / 分辨率策略 / channel 配额 + 白名单。 |
| 多格式导出 | `output/markdown`、`output/csv`、`output/jsonl`。 |

不存在的能力（本迭代）：音视频落盘、tiktok/B 站爬虫、字幕翻译、播放量预测等——旧实现见 `legacy/old_downloader/scripts/`。

---

### Python 环境与依赖

```bash
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt

cp .env.example .env      # 然后写入 YOUTUBE_API_KEY=<你的 Data API Key>
```

如遇 `.venv/bin/pip` Shebang 指向其他目录的旧工程，请务必使用 **`python -m pip`** 以保持与 `.venv/bin/python` 对齐。

`requirements.txt` 已包含：`google-api-python-client`, `python-dotenv`, `PyYAML`, `pandas`, `tqdm`, `isodate`。**`yt-dlp` 为可选**：`probe-format` 若找不到可执行文件会写入 `format_probe_status=skipped`。**如需显式离线跳过 yt-dlp 网络调用**（保持 schema 恒定），在执行 `probe-format` 前设置：`export SKIP_FORMAT_PROBE=1`。

---

### 管道步骤 CLI

在项目根目录执行（确保已 `pip install`）：

```bash
# 1) 检索
python -m src.main search --task config/search_tasks.yaml --output data/raw/candidates.jsonl

# 2) enrich（无 Key → stderr 告警 + passthrough）
python -m src.main enrich --input data/raw/candidates.jsonl --output data/enriched/enriched.jsonl

# 3) 可选：分辨率探测（无 yt-dlp → format_probe_status=skipped）
python -m src.main probe-format --input data/enriched/enriched.jsonl --output data/enriched/probed.jsonl

# 4) 过滤（产生保留与拒绝两段 JSONL）
python -m src.main filter \
  --input data/enriched/probed.jsonl \
  --rules config/filter_rules.yaml \
  --output data/filtered/filtered.jsonl \
  --rejected data/rejected/rejected.jsonl

# 5) 导出 Markdown + CSV + jsonl（--format all）
python -m src.main export --input data/filtered/filtered.jsonl --format all --output-dir output/
```

也可用 `config/search_tasks.demo.yaml`（仅 2 个关键词，`max_results_per_keyword: 3`）做冒烟测试——依旧需要可用的 API Key。

---

### 离线（无 Key）最小演示

> **注意**：若你已使用 `data/**/*.jsonl` 存过正式数据，请先备份；以下命令会覆盖同名文件。

本地未放置 `YOUTUBE_API_KEY` 时，`enrich` stderr 打印告警并 **直通写入** 输入内容，依旧可验证 `filter/export`：

```bash
export SKIP_FORMAT_PROBE=1    # 可选：完全跳过 yt-dlp，快速演示 filter/export

python -m src.main enrich --input data/fixtures/sample_raw.jsonl --output data/enriched/enriched.jsonl
python -m src.main probe-format --input data/enriched/enriched.jsonl --output data/enriched/probed.jsonl

python -m src.main filter \
  --input data/enriched/probed.jsonl \
  --rules config/filter_rules.yaml \
  --output data/filtered/filtered.jsonl \
  --rejected data/rejected/rejected.jsonl

python -m src.main export --input data/filtered/filtered.jsonl --format all --output-dir output/
```

`export` 会尝试加载与 `data/filtered/` 并列的 `data/rejected/rejected.jsonl`（即上一步 `filter` 的默认输出），用于 Markdown 统计头部的 **rejected** 计数。

---

### 配置文件速览

| 文件 | 作用 |
|------|------|
| `config/search_tasks.yaml` | tasks ↔ 类目、关键词配额、地域与语言偏好。 |
| `config/filter_rules.yaml` | 时长阈值、分辨率策略、短片/直播/AI/噪声词策略、配额与 whitelist 豁免。 |
| `config/negative_keywords.yaml` | `ai_content` / `low_value_content` 子串词典。 |
| `config/brand_whitelist.yaml` | 正向品牌名词与关键词加权。 |
| `config/channel_whitelist.yaml` | 频道上限扩展（文案子串匹配 + ID 精确匹配）。 |

细节请阅读：`docs/filtering_rules.md`。

---

### 合规 & 风险提示

1. **不下载音视频**：我们只访问公开 API metadata 或对 URL 做一次非落地格式探测列表；请确保符合 YouTube API ToS（尤其是自动化检索频率与存储条款）。  
2. **令牌安全**：不要将 `.env` 提交入库；密钥泄露会导致配额耗尽或封号。  
3. **误判调参**：被拒样本集中在 `data/rejected/`；请参考 `docs/manual_review_guide.md` 逐项收紧或放宽阈值。  

---

### 开发与归档

新实现位于 `src/`。旧的多平台 HQ 下载器位于 `legacy/old_downloader/`。清理依据见 [`docs/cleanup_report.md`](docs/cleanup_report.md)。
