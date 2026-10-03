# Linux 接入与项目演变

已有远端最早可达提交 `6fe4b73f507b63734981dc125cdb85a0f43edc92` 已包含 URL 采集管线与 legacy/old_downloader。后续经历 LLM/OpenRouter 采集，当前 `16fb38c6c8413b7634e919b0125d364e78d40140` 转为 YouTube 搜索页加 yt-dlp。当前可达main共15提交；这不覆盖已删除或未发布历史。

本地旧下载器与历史版本共享代码结构，但核心文件不完全相同，因此将其作为本地独有 legacy 能力保留，并从既有远端正常追加迁移提交。原Git历史不改写，也不伪造本地祖先。

迁移前28文件已用可信加密流式保全并逐文件解密校验，包含本地私有输入。恢复路径为 `/home/alalapi/Archive/youtube-hq-downloader-pre-adoption/current-local-tree.tar.gpg`，密钥复用本机 Secret Service 中既有归档凭据，不写入本仓库。不要普通解压私有资料到临时目录；由授权恢复任务按加密manifest验证并保护敏感文件。

当前应用原11项离线测试与旧下载器原覆盖分别验证，不运行真实网站、浏览器、cookie/token或旧业务Goal。历史40/40只属旧下载器；业务未知仍保留。原生项目侧栏登记由所有者后续完成，原项目聊天ID与cwd不变。
