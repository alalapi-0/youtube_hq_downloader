# YouTube 项目 Linux Agent 入口

当前应用为 Ad URL Scout，沿现有 `alalapi-0/youtube_hq_downloader` 的 main 演变。真实 cwd 必须为 `/home/alalapi/Projects/youtube-hq-downloader`。先读本文件与 `PROJECT_STATUS.md`；继承宿主实际全局规则和 Skills，只恢复当前任务。

当前源码在 `src/`；本机旧下载器源码与独有资料保留于 `legacy/old_downloader/`。其中历史 PROJECT_STATUS、README、Round 报告仅为旧版本事实，历史40/40不代表当前应用验收。不要把旧下载器迁回主应用目录或用远端历史版本覆盖本地独有代码。

迁移维护只能运行离线检查：`python3 -I -B scripts/linux_verify.py check` / `test`。旧下载器检查为 `python3 -I -B legacy/old_downloader/scripts/linux_verify.py check` / `test`。两者使用独立外部 Python runtime、network namespace、合成数据与只读源码，拒绝自动安装或读取真实业务资料。

未经当前任务明确授权，不运行 run.py、实际 YouTube 搜索/元数据/下载、browser/cookie/token脚本或业务 Goal。旧 URLs、state、历史报告和账号资料留在本地忽略区域；不展示、上传或以普通明文备份复制。凭据仅使用安全存储/当前授权环境注入。

只写当前项目及已登记独立运行/Temp根，保留其他任务修改。APFS、分区、全局配置、原生侧栏和其他项目不属于项目维护。Hub业务来源沿 `hub.connection.yaml`；未知保持未知，不用离线测试替代实际业务成功。Git按当前所有者授权正常交付已有远端，禁新建仓库、强推、重写历史或绕过保护。
