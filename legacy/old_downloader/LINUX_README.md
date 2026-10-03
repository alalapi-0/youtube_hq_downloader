# 早期下载器的 Linux 维护

该目录保存迁移前本地下载器的独有源码与 Linux 适配。当前产品在仓库根的 Ad URL Scout，业务权威入口为根 PROJECT_STATUS.md。此目录旧 PROJECT_STATUS、README 与 Round 报告只代表旧版本，原样保留在本机；不上传原 URL 输入或历史原始报告。

从仓库根使用 `python3 -I -B legacy/old_downloader/scripts/linux_verify.py check` 或 `test`。固定 runtime `/home/alalapi/Runtimes/youtube-hq-downloader/venv`，源码复制白名单与原测试覆盖保持不变，网络关闭，使用合成720p媒体。旧 run.py、认证、浏览器、真实下载不由维护入口调用。
