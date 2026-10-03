# YouTube 项目当前状态

当前产品为 **Ad URL Scout**，采用既有仓库 `alalapi-0/youtube_hq_downloader` 的 main。Linux迁移基线为 `16fb38c6c8413b7634e919b0125d364e78d40140`。该版本通过 YouTube 搜索页、yt-dlp 元数据/格式、本地硬约束和去重生成审核表；无须 OpenRouter 或 YouTube API Key。

旧本地下载器为同一项目的早期能力，独有代码、原测试与 Linux 适配保留于 `legacy/old_downloader`。该目录原 `PROJECT_STATUS.md`、README 与 Round 报告继续留在本机；历史40/40仅属旧下载器。它没有原本 Git 祖先，接入不会伪造历史。

当前维护仅验证隔离 Linux 离线能力：当前应用原11项 unittest、帮助/导入；旧下载器原4个测试入口、6组probe断言、3项Hub unittest与11项Linux测试，加合成720p ffprobe/计划/缓存检查。命令见 README。实际成功证据和交付事实沿工作站 State；这里不是业务Goal执行记录。

真实 YouTube 搜索、授权、cookie、元数据获取、下载、实际素材质量、业务验收与原生侧栏关联尚未验证。当前业务目标、阶段、轮次、完成率、阻塞和审核结果没有可用的结构化事实，不能据离线技术检查推断为完成。

Hub读取本文件作为当前项目说明，业务字段保持 unknown。仓库身份由 Git 提供；当前受保护数据、原 URL 文件和历史资料忽略且不提交。
