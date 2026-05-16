# Review feedback analysis

## 总体
- 总审核数：4
- 通过：2
- 不通过：2
- 不确定：0
- 通过率：50.0%
- sample_size_too_small：True

## 按 query_used 通过率
| key | total | pass | reject | pass_rate |
| --- | --- | --- | --- | --- |
| 4k | 1 | 1 | 0 | 1.0 |
| product film; perfume commercial | 1 | 1 | 0 | 1.0 |
| bad | 1 | 0 | 1 | 0.0 |
| flagship | 1 | 0 | 1 | 0.0 |

## 按品牌通过率
| key | total | pass | reject | pass_rate |
| --- | --- | --- | --- | --- |
| unknown | 4 | 2 | 2 | 0.5 |

## 高通过率频道
| key | total | pass | reject | pass_rate |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

## 常见拒绝原因
| label | count |
| --- | --- |
| not_4k | 2 |
| review_or_unboxing | 2 |
| compression_blocks | 1 |

## 常见通过特征
| label | count |
| --- | --- |
| high_resolution_confirmed | 2 |
| strong_commercial_style | 1 |
| official_brand_channel | 1 |
| product_focused | 1 |
| clean_studio_visual | 1 |

## 高通过率关键词
| keyword | total | pass | pass_rate |
| --- | --- | --- | --- |
| commercial | 3 | 2 | 0.6667 |

## 低通过率关键词
| keyword | total | pass | pass_rate |
| --- | --- | --- | --- |
|  |  |  |  |

## 高风险 metadata 特征
| label | count |
| --- | --- |
| max_format_height unknown | 2 |

## 推荐下一轮搜索方向
- sample_size_too_small: keep the next strategy conservative until more reviewed examples are available.
- Increase keyword family: commercial (pass_rate=0.6667, n=3).
- Strengthen filter for reject reason: not_4k (count=2).
- Strengthen filter for reject reason: review_or_unboxing (count=2).
- Strengthen filter for reject reason: compression_blocks (count=1).
