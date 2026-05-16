# 反馈闭环

人工审核反馈用于改进下一轮搜索。

控制台流程：

```text
导入人工审核反馈
  -> 合并人工标签
  -> 统计通过率
  -> OpenRouter 总结通过/不通过规律
  -> 生成 next_search_plan.yaml
```

样本少于 `config/app.yaml` 中的 `min_sample_size_for_strategy` 时，系统会标记 `sample_size_too_small`，并生成保守策略。

高频拒绝原因会转成排除词建议；高通过率 query、品牌、频道会转成下一轮搜索建议。
