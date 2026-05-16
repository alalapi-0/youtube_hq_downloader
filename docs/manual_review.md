# 人工审核

任务完成后查看：

```text
output/tasks/task_xxx/review_sheet.csv
```

需要填写的字段：

- `manual_status`: `pass` / `reject` / `uncertain`
- `manual_passed`: `true` / `false`
- `manual_reject_reasons`: 多个标签用 `;` 分隔
- `manual_pass_features`: 多个标签用 `;` 分隔
- `manual_notes`: 自由备注

合法标签见 `config/labels.yaml`。非法标签不会丢失，会写入 `manual_review.unrecognized_labels`。
