# Rule-based next search strategy

## 样本量
- reviewed: 4
- pass_rate: 50.0%
- sample_size_too_small: True

## 增加优先级
- `4k`
- `product film`
- `perfume commercial`
- `commercial`
- `studio`
- `packshot`

## 保留品牌
- 暂无高置信品牌；继续积累样本。

## 频道白名单建议
- 暂无。

## 降低优先级 query
- `bad`
- `flagship`

## 新增 negative_keywords 建议
- `hd`
- `1080p only`
- `review`
- `unboxing`
- `hands on`
- `first impression`

## 规则建议
- require_4k: `True`
- max_results_per_keyword: `3`

## 依据来自哪些统计结果
- `by_query_used` high/low pass rate
- `by_brand` pass rate
- `by_channel_title` pass rate
- `common_reject_reasons`
- `common_pass_features`
- `metadata_risk_features`
