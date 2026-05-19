# 清理报告

本次重构把项目主线收敛为：

> 从 YouTube 搜索结果页批量采集 URL，用 yt-dlp 读取公开视频元数据和格式信息，再在本地筛选 4K、时长、发布时间和负面词。

## 已移除

- OpenRouter 客户端、提示词、缓存代码
- Vimeo Web Search / oEmbed 代码
- 历史 legacy 代码目录
- 旧下载器和旧多平台脚本
- 旧多 provider / 大模型配置文档

## 当前产品入口

- `python3 run.py`
- `python3 -m src.main collect`
- 人工反馈导入与统计命令

## 明确边界

Ad URL Scout 不下载视频文件，不要求 YouTube API Key，不调用 OpenRouter。程序只读取公开视频页面可获得的 metadata 和 format 列表。
