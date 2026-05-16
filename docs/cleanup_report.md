# 清理报告

本次产品化重构将项目定位为：

> 面向广告/商品/品牌视频数据寻源的 AI 增强 URL 搜索与筛选工具。

## 已归档

- `legacy/old_downloader/`：旧多平台下载器、旧下载脚本、旧下载文档。保留为历史参考，不属于当前产品主线。
- `legacy/config_pre_productization/`：旧分散配置，包括多 provider LLM 配置、旧 filter/search/review/cookie 配置。
- `legacy/docs_pre_productization/`：旧文档，包含旧控制台、多 provider、URL 分析模块等拆散说明。
- `legacy/skills_pre_productization/`：旧技能提示文档。
- `legacy/console_pre_productization/`：旧功能列表式控制台。

## 已删除主路径引用

- 普通用户入口从 `run_console.py` 改为 `run.py`。
- README 不再推荐下载功能。
- README 不再暴露 OpenAI/Grok provider 选择。
- 主配置精简为 `config/app.yaml`、`config/filters.yaml`、`config/brands.yaml`、`config/labels.yaml`。

## 保留能力

- YouTube URL 搜索
- YouTube 元数据补全
- yt-dlp 仅 metadata / format probe
- 规则过滤
- OpenRouter AI 搜索计划与语义复筛
- 人工审核表导出/导入
- 反馈分析与下一轮策略生成

## 明确边界

Ad URL Scout 默认不下载视频，不绕过权限，不使用 Cookie 做权限规避。Cookie 仅保留为高级可选项。
