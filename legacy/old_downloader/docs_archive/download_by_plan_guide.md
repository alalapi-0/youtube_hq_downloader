# download_by_plan.py 使用指南

## 快速开始

### 1. 准备 plan_cache.json
```bash
# 确保 state/plan_cache.json 包含要下载的 URL 的 plan
cat state/plan_cache.json
```

示例 plan：
```json
{
  "youtube:BhNImM1N6vM": {
    "url": "https://www.youtube.com/watch?v=BhNImM1N6vM",
    "format_expr": "313+251",
    "height": 2160,
    "mode": "adaptive"
  }
}
```

### 2. 准备 URL 列表
```bash
# 方法 A：使用 urls.txt
cat urls.txt
https://www.youtube.com/watch?v=BhNImM1N6vM

# 方法 B：使用 --url 参数（单个 URL）
```

### 3. 运行下载
```bash
# 批量下载（读取 urls.txt）
python3 scripts/download_by_plan.py

# 单个 URL
python3 scripts/download_by_plan.py --url "https://www.youtube.com/watch?v=BhNImM1N6vM"
```

## 运行场景

### 场景 1：首次下载
```bash
python3 scripts/download_by_plan.py --url "https://www.youtube.com/watch?v=xxx"
```
输出：
```
=== download_by_plan ===
[Info] yt-dlp cmd: python3 -m yt_dlp
[Info] Using cached plan: 313+251
[Info] Download command: ...
[download] Downloading...
[Info] 下载校验通过: video.mkv | 实际分辨率 2160p (3840x2160) 达标
```

### 场景 2：断点续传
```bash
# 如果上次下载中断，再次运行会自动续传
python3 scripts/download_by_plan.py --url "https://www.youtube.com/watch?v=xxx"
```
输出：
```
[Info] 检测到已有断点续传文件，将优先续传
[Info] Partial: video.part (163.8 MB)
[download] Resuming download at byte 171010048
```

### 场景 3：复用已有文件
```bash
# 如果已有完整且达标的文件，直接跳过
python3 scripts/download_by_plan.py --url "https://www.youtube.com/watch?v=xxx"
```
输出：
```
[Info] 发现已存在且达标的完整文件，直接复用: video.mkv
[Info] 实际分辨率 2160p (3840x2160) 达标
```

### 场景 4：没有 plan
```bash
python3 scripts/download_by_plan.py --url "https://www.youtube.com/watch?v=xxx"
```
输出：
```
[Error] 本地没有可用 plan，跳过
```
同时写入 `state/failed_jobs.json`

## 输出文件

### 下载文件
```
downloads/
  ├── Video Title [ID] [client-auto] [2160p] [adaptive-313_plus_251].mkv
  └── Video Title [ID] [client-auto] [2160p] [adaptive-313_plus_251].f313.webm.part
```

### 状态文件
```
state/
  ├── plan_cache.json      # plan 缓存（输入）
  ├── failed_jobs.json     # 失败记录（输出）
  └── run_log.jsonl        # 运行日志（追加）
```

## 失败处理

### 查看失败记录
```bash
cat state/failed_jobs.json | python3 -m json.tool
```

示例输出：
```json
{
  "youtube:xxx": {
    "url": "https://www.youtube.com/watch?v=xxx",
    "last_failed_at": 1773395685,
    "stage": "download",
    "reason": "HTTP Error 403: Forbidden",
    "used_plan": "313+251",
    "has_partial": true,
    "suggestion": "refresh_context_or_probe_again"
  }
}
```

### 查看运行日志
```bash
tail -f state/run_log.jsonl
```

日志事件类型：
- `download_start` - 开始下载
- `download_success` - 下载成功
- `download_failed` - 下载失败
- `missing_plan` - 缺少 plan
- `reuse_existing_final` - 复用已有文件
- `download_retryable_error` - 可重试错误
- `download_interrupted` - 用户中断

## 重要提醒

### ⚠️ 这是一个"纯执行器"
- ❌ **不会**自己 probe
- ❌ **不会**刷新 token
- ❌ **不会**更新 yt-dlp
- ❌ **不会**修复 plan

### ✅ 它只负责
- ✅ 读取本地 plan_cache.json
- ✅ 执行下载
- ✅ 断点续传
- ✅ 记录失败

### 如果下载失败
1. 检查 `state/failed_jobs.json` 查看失败原因
2. 如果是 token 问题，运行 `refresh_context.py`
3. 如果是 plan 问题，运行 `probe_best_plan.py`（Round 4）
4. 修复后重新运行 `download_by_plan.py`

## 下载参数

当前使用保守策略（稳定性优先）：

| 参数 | 值 | 说明 |
|------|-----|------|
| USE_IPV4 | True | 强制 IPv4 |
| SOCKET_TIMEOUT | 60 | 套接字超时 60 秒 |
| RETRIES | 50 | HTTP 重试 50 次 |
| FRAGMENT_RETRIES | 50 | 分片重试 50 次 |
| CONCURRENT_FRAGMENTS | 1 | 串行下载（稳定） |
| SLEEP_REQUESTS_SECONDS | 1.0 | 请求间隔 1 秒 |
| DOWNLOAD_ATTEMPTS_PER_PLAN | 2 | 每个 plan 尝试 2 次 |
| RETRY_WAIT_SECONDS | 20 | 重试前等待 20 秒 |

如需调整，修改 `scripts/download_by_plan.py` 开头的常量。

## 故障排查

### 问题：下载一直失败
```bash
# 1. 检查 yt-dlp 版本
python3 -m yt_dlp --version

# 2. 刷新上下文
python3 scripts/refresh_context.py

# 3. 查看失败原因
cat state/failed_jobs.json | python3 -m json.tool

# 4. 手动测试 plan
python3 -m yt_dlp -f "313+251" "https://www.youtube.com/watch?v=xxx"
```

### 问题：断点续传不工作
```bash
# 检查 .part 文件
ls -lh downloads/*.part

# 手动续传测试
python3 -m yt_dlp -c -f "313+251" "URL"
```

### 问题：找不到 plan
```bash
# 检查 plan_cache.json
cat state/plan_cache.json | python3 -m json.tool

# 查看 URL 对应的 cache_key
python3 -c "
import sys
sys.path.insert(0, 'scripts')
from common import cache_key_for_url
print(cache_key_for_url('YOUR_URL'))
"
```

## 性能优化（后续 Round）

当前版本使用保守策略，后续可优化：
- 增加 CONCURRENT_FRAGMENTS（并行下载分片）
- 减少 SLEEP_REQUESTS_SECONDS（加快请求）
- 动态调整重试策略
- 实现智能带宽检测

Round 3 聚焦稳定性，性能优化留给后续版本。
