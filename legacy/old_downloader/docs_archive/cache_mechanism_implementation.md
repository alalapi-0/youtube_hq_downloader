# 一键下载缓存机制实现说明

## 问题背景

在原始设计中，虽然 `refresh_context.py` 会将环境信息保存到 `state/env_state.json`，但 `probe_best_plan.py` 和 `download_by_plan.py` 每次运行时都会重新探测部分环境信息（如 js_runtime、cookies_browser），导致：

1. 不必要的系统调用和命令执行
2. 增加了启动时间
3. 违背了"一键下载"的设计初衷（第一次探测后应该直接复用）

## 修复方案

### 修改的文件

1. `scripts/probe_best_plan.py` - `load_runtime_context()` 函数
2. `scripts/download_by_plan.py` - `load_runtime_context()` 函数

### 核心改动

**修改前：**
```python
# probe_best_plan.py 和 download_by_plan.py 中
js_runtime = detect_js_runtime()  # 每次都重新探测
cookies_browser = detect_cookies_browser()  # 每次都重新探测
```

**修改后：**
```python
# 优先使用缓存的 js_runtime
js_runtime = ""
js = env_state.get("js_runtime") if isinstance(env_state, dict) else None
if isinstance(js, dict) and js.get("ok"):
    js_runtime = str(js.get("name") or "").strip()

if not js_runtime or js_runtime == "auto":
    js_runtime = detect_js_runtime()  # 仅在缓存不存在或无效时才探测

# 优先使用缓存的 cookies_browser
cookies_browser = None
browser = env_state.get("browser") if isinstance(env_state, dict) else None
if isinstance(browser, dict):
    cb = str(browser.get("cookies_browser") or "").strip()
    if cb:
        cookies_browser = cb

if not cookies_browser:
    cookies_browser = detect_cookies_browser()  # 仅在缓存不存在时才探测
```

### 检查逻辑

对于每个环境信息项，都遵循以下逻辑：

1. **优先读取缓存**：从 `env_state.json` 中读取
2. **检查有效性**：确保缓存数据存在且 `ok: true`
3. **回退机制**：仅当缓存不存在或无效时，才调用 `detect_*()` 函数重新探测

### 缓存的环境信息

| 信息项 | 缓存键 | 检查条件 |
|--------|--------|----------|
| yt-dlp 命令 | `ytdlp.cmd` | `ytdlp.ok == true` |
| JS 运行时 | `js_runtime.name` | `js_runtime.ok == true` 且不为 "auto" |
| Cookies 浏览器 | `browser.cookies_browser` | 字符串非空 |

## 工作流程

### 第一次运行（初始化）

```
用户执行: python3 run.py
  ↓
1. refresh_context.py 运行
   - 探测 yt-dlp, ffmpeg, ffprobe
   - 探测 js_runtime (node/deno/bun)
   - 探测 cookies_browser (chrome/firefox/...)
   - 保存到 state/env_state.json
  ↓
2. probe_best_plan.py 运行
   - 从 env_state.json 读取缓存 ✅
   - 使用缓存的 yt-dlp 命令 ✅
   - 使用缓存的 js_runtime ✅
   - 使用缓存的 cookies_browser ✅
   - 探测视频格式并保存到 plan_cache.json
  ↓
3. download_by_plan.py 运行
   - 从 env_state.json 读取缓存 ✅
   - 使用缓存的 yt-dlp 命令 ✅
   - 使用缓存的 js_runtime ✅
   - 从 plan_cache.json 读取下载计划 ✅
   - 直接下载
```

### 后续运行（完全依赖缓存）

```
用户执行: python3 run.py
  ↓
1. refresh_context.py 运行
   - 读取并验证现有缓存
   - 如无变化则跳过探测
  ↓
2. probe_best_plan.py 运行
   - 从 env_state.json 读取缓存 ✅（无需重新探测）
   - 仅对新链接执行 probe
  ↓
3. download_by_plan.py 运行
   - 从 env_state.json 读取缓存 ✅（无需重新探测）
   - 从 plan_cache.json 读取计划 ✅
   - 直接下载
```

## 性能优化

**修复前：**
- 每次运行 `probe_best_plan.py` 都会调用 `detect_js_runtime()` 和 `detect_cookies_browser()`
- 每次运行 `download_by_plan.py` 都会调用 `detect_js_runtime()`
- 涉及多次 `shutil.which()` 和文件系统检查

**修复后：**
- 第一次运行后，所有环境信息都已缓存
- 后续运行只需读取 JSON 文件
- 减少了不必要的系统调用
- 启动速度更快

## 缓存失效场景

用户需要手动刷新缓存的场景：

1. **升级了 yt-dlp**：运行 `python3 scripts/refresh_context.py`
2. **安装了新的 JS 运行时**：运行 `python3 scripts/refresh_context.py`
3. **换了浏览器**：运行 `python3 scripts/refresh_context.py`
4. **工具路径变化**：运行 `python3 scripts/refresh_context.py`

系统不会自动检测这些变化，因为：
- 减少系统调用和探测开销
- 避免每次运行都进行版本检查
- 用户可以根据需要主动刷新

## 测试验证

使用提供的 `test_cache_mechanism.py` 脚本可以验证：

```bash
python3 test_cache_mechanism.py
```

该脚本会检查：
1. `env_state.json` 是否存在及内容
2. `tokens.json` 是否存在及内容
3. `plan_cache.json` 是否存在及内容
4. 缓存完整性和可用性

## 向后兼容性

- 如果 `env_state.json` 不存在，会自动回退到重新探测
- 如果缓存中的某个字段无效，只会重新探测该字段
- 不影响现有的使用方式和工作流程
- 完全向后兼容

## README 更新

README.md 已更新，包含：

1. **核心思想**部分：补充了缓存机制的说明
2. **新增第六章**：详细介绍一键下载的缓存机制
3. **脚本职责**部分：说明了每个脚本如何使用缓存
4. **推荐使用策略**部分：补充了缓存相关的最佳实践
5. **最后建议**部分：更新了核心原则

## 总结

通过这次修复，实现了真正的"一键下载"缓存机制：

✅ 第一次运行时探测并缓存所有环境信息  
✅ 后续运行优先使用缓存，避免重复探测  
✅ 只在必要时才重新探测（缓存不存在或用户主动刷新）  
✅ 减少系统调用和启动时间  
✅ 完全向后兼容  
✅ 保持代码简洁和可维护性  

这样就完全符合用户的期望：第一次配置后，后续下载直接使用缓存的信息，无需每次都重复探测。
