## 过滤器编号与含义

1. **时长（duration）**：`min_seconds`、`max_seconds` 闭区间外向淘汰；缺省字段一般不触发下限（无法在 enrich 中获取时长时）。
2. **短视频（shorts）**：`/shorts/` URL、短时长度与描述中的 `#shorts` 等启发式任一成立且 `exclude: true` 时淘汰。
3. **直播（live）**：`liveBroadcastContent` 或 presence of `liveStreamingDetails`。
4. **AI 口吻 / 生成迹象（AI）**：`negative_keywords.ai_content` 中任一 **子串命中** Title+Description 即淘汰（可调 `reject_on_keyword_hit`）。
5. **低价值内容（Low value）**：`low_value_content` 词表同上。
6. **4K / 分辨率门槛（Resolution）**：  
   - `require_4k: true` → 等价于至少 **2160p**（亦可通过显式 `min_height`）。  
   - `allow_format_probe: true` 且 probe 结果为 `ok`：以 `probe_max_height` 与阈值比较。  
   - Probe 不可用 / 失败：`allow_text_evidence_when_format_unknown` 为真时可用标题描述的 **正则文本证据** 放行但标记 `needs_resolution_check`。  
   - 关闭 probe 仅靠文本时请谨慎：`allow_format_probe: false` 时仍可在文本置信度足够时放行，但强烈推荐人工再审。
7. **去重 / 配额（Dedupe）**：  
   - `by_video_id`：全局先到先得。  
   - `max_per_channel`：在 `category_scope_field`（默认类目+子类）分组下，每频道至多保留若干条高分优先（由 `filter_score` 排序）。  
   - `whitelist_max_per_channel`：列入 `channel_whitelist.yaml` 的频道可把上限提升到该值。

## scorer 正负向词（高层）

正向词来自 `config/brand_whitelist.yaml`，负向分拆为 AI / 低价两类；命中即调整 `filter_score` 并在导出中保留命中列表以供 audit。
