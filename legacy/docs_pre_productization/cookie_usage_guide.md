# Cookie 使用指南

## 默认不需要 Cookie

URL 分析模块默认不读取 Cookie。没有 Cookie 时，项目仍可运行，并会优先使用输入已有字段、YouTube Data API、yt-dlp metadata 和公开网页 metadata。

## 什么时候可能需要 Cookie

少数页面的公开 metadata 可能只有在你自己的浏览器会话中才能看到更多信息。此时可以显式指定 Cookie。Cookie 只用于访问你已经能访问的页面信息，不用于绕过权限、不用于破解、不用于下载受限内容。

## 使用 cookie.txt

浏览器导出的 Netscape `cookie.txt` 可以这样传入：

```bash
python -m src.main analyze-url \
  --input data/filtered/llm_filtered.jsonl \
  --output data/url_analysis/url_analysis.jsonl \
  --cookie-file ./private/cookies.txt
```

建议把 Cookie 文件放在 `private/` 下。该目录已加入 `.gitignore`。

## 使用 cookies-from-browser

如果环境允许，也可以显式让 yt-dlp 使用本机浏览器 Cookie：

```bash
python -m src.main analyze-url \
  --input data/filtered/llm_filtered.jsonl \
  --output data/url_analysis/url_analysis.jsonl \
  --cookies-from-browser chrome
```

运行时会在控制台提示风险和用途。此功能不会默认启用，也不会在没有用户选择时访问浏览器数据。

## Cookie 安全注意事项

- 不要提交 Cookie 文件。
- 不要把 Cookie 内容粘贴到日志、Issue、PR 或聊天里。
- 本项目不会打印完整 Cookie 内容。
- 如果 Cookie 读取失败，会自动降级为无 Cookie 模式。
- `cookie_config.local.yaml`、`cookies.txt`、`*.cookie`、`private/` 都已加入 `.gitignore`。

## 失败降级

Cookie 文件不存在、格式错误、浏览器 Cookie 读取失败时，模块会记录状态或警告，然后继续无 Cookie 分析。单条 URL 失败不会中断整批任务。
