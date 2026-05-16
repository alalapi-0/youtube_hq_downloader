# URL 分析模块

本模块把一批 YouTube URL 转成结构化审核记录，用于后续人工标注和搜索策略优化。它面向“先收集候选 URL，再让人审，再总结规律”的工作流。

## 它读取哪些信息

- URL、video_id、标题、频道、频道 ID、频道 URL
- description、tags、hashtags、发布时间、时长、播放/点赞/评论数
- 缩略图 URL
- 可选格式探测结果：可用高度、最大高度、是否有 2160p
- 公开网页 metadata：`og:title`、`og:description`、`meta keywords`、canonical URL、JSON-LD VideoObject
- 来源上下文：query、category、subcategory、brand、source stage
- 自动过滤上下文：规则过滤、LLM 判断、质量分
- 人工审核占位字段

## 它不做什么

- 默认不下载视频文件。
- 不替代人工审核。
- 不申请或依赖 Chrome API Key。
- 不使用 Chrome extension API。
- 不用 Cookie 绕过权限或下载受限内容。

## 为什么默认不下载视频

当前目标是提高 URL 命中率，而不是建立视频内容处理系统。标题、频道、描述、公开 metadata、格式签名和人工标签已经足够支撑第一轮策略优化。保持“无下载”也能降低存储、版权和敏感数据风险。

## 运行 analyze-url

离线测试，只使用输入中已有字段：

```bash
.venv/bin/python -m src.main analyze-url \
  --input examples/candidates.example.jsonl \
  --output data/url_analysis/url_analysis.jsonl \
  --offline true
```

正常模式会按需补全：已有字段优先，其次 YouTube Data API，其次 yt-dlp metadata，最后公开网页 metadata。

```bash
python -m src.main analyze-url \
  --input data/filtered/llm_filtered.jsonl \
  --output data/url_analysis/url_analysis.jsonl
```

## 导出人工审核表

`analyze-url` 默认会写：

- `output/review/review_sheet.csv`
- `output/review/review_sheet.md`

也可以单独导出：

```bash
python -m src.main export-review \
  --analysis data/url_analysis/url_analysis.jsonl \
  --output-csv output/review/review_sheet.csv \
  --output-md output/review/review_sheet.md
```

## 如何填写人工审核表

在 CSV 中填写这些列：

- `manual_status`: `pending` / `pass` / `reject` / `uncertain`
- `manual_passed`: `true` / `false`
- `manual_reject_reasons`: 多个标签用 `;` 分隔
- `manual_pass_features`: 多个标签用 `;` 分隔
- `manual_notes`: 自由备注
- `reviewer`、`reviewed_at`: 可选

合法标签见 `config/review_labels.yaml`。非法标签不会丢失，会进入 `manual_review.unrecognized_labels`。

## 导入人工审核结果

```bash
python -m src.main import-review \
  --analysis data/url_analysis/url_analysis.jsonl \
  --review-csv output/review/review_sheet_filled.example.csv \
  --output data/manual_reviews/manual_reviewed.jsonl
```

导入时会按 `video_id` 或 `video_url` 合并回原始结构化记录。

## 分析反馈

```bash
python -m src.main analyze-feedback \
  --input data/manual_reviews/manual_reviewed.jsonl \
  --output-md output/strategy/feedback_analysis.md \
  --output-json data/feedback_analysis/feedback_analysis.json
```

输出会包含总体通过率、按品牌/频道/query 的通过率、常见拒绝原因、常见通过特征、高/低通过率关键词和下一轮方向。

## 生成下一轮搜索策略

不开 LLM 的规则策略：

```bash
python -m src.main strategy-from-feedback \
  --feedback-json data/feedback_analysis/feedback_analysis.json \
  --reviewed-jsonl data/manual_reviews/manual_reviewed.jsonl \
  --output-md output/strategy/rule_based_next_search_strategy.md \
  --output-yaml output/strategy/rule_based_next_search_plan.yaml
```

可选 LLM 策略：

```bash
python -m src.main llm-analyze-feedback \
  --input data/manual_reviews/manual_reviewed.jsonl \
  --stats data/feedback_analysis/feedback_analysis.json \
  --output-md output/strategy/llm_feedback_strategy.md \
  --output-yaml output/strategy/llm_next_search_plan.yaml \
  --use-llm true
```

LLM 只会看到人工审核统计和截断后的样本摘要，不会收到完整长描述。
