# 清理报告

本次重构把项目主线进一步收敛为：

> 通过 OpenRouter Web Search 批量寻找广告/商品/品牌视频 URL，并在本地查重后导出人工审核表。

## 当前产品入口

- `python3 run.py`
- `python3 -m src.main run-task`
- 人工反馈导入与分析命令

## 已从当前入口移除

- YouTube Data API 搜索入口
- yt-dlp 搜索兜底
- 本地脚本拼搜索词再搜索的备用流程
- 拆分式 `plan/search/enrich/probe/filter/export` 操作链
- 多 LLM provider 选择

## 已归档到 legacy

- `legacy/source_pre_web_search/`：旧 YouTube API 搜索、元数据补全、格式探测、规则过滤、导出器和旧策略优化脚本。
- `legacy/llm_web_search_replaced/`：旧搜索计划生成和语义复筛模块。
- `legacy/config_pre_web_search/`：旧品牌表和规则过滤配置。
- `legacy/examples_pre_web_search/`：旧拆分流程示例和旧导出样例。

## 保留为内部支撑的能力

- OpenRouter 客户端和缓存
- URL 结构化记录与人工审核表导出
- 人工审核标签导入
- 反馈统计和下一轮策略生成
- 本地历史任务 URL 查重

## 明确边界

Ad URL Scout 不下载视频文件，不要求 YouTube API Key，不需要浏览器 Cookie。当前搜索 URL 的唯一在线入口是 OpenRouter Web Search。
