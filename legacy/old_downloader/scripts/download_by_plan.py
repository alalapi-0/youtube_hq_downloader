#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
download_by_plan.py — 视频下载执行模块

【这个脚本做什么？】
  读取 state/plan_cache.json 中已保存的下载计划，
  按计划执行视频下载，支持断点续传。

  这个脚本是「纯执行器」：它不会自行探测视频格式，
  只使用 probe_best_plan.py 已经探测好并保存的计划。
  如果某个 URL 没有对应的计划，会跳过并记录失败。

【分辨率严格保障】
  下载完成后会用 ffprobe 验证文件的实际分辨率，
  确保下载到的确实是 4K（或要求的分辨率），
  防止「标称4K实为1080p」的情况。

【自动重试机制】
  遇到以下问题时会自动处理：
  - 浏览器 cookie 编码错误：自动改用无 cookies 重试
  - 遇到 YouTube bot 检验错误（「Sign in to confirm you're not a bot」）：
    自动使用浏览器 cookies 重新探测并下载
  - Token 失效（切换 VPN 后常见）：自动刷新 token 后重试
  - 确认视频无 4K：标记为 invalid 并跳过，不浪费时间

【断点续传】
  下载过程中断后（如网络问题、手动停止），会保留 .part 文件，
  下次运行时自动从断点继续，不会重新下载已有部分。

【使用方式】
  下载全部计划：       python3 scripts/download_by_plan.py
  下载单个链接：       python3 scripts/download_by_plan.py --url "https://..."
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from common import (
    PLAN_STATUS_INVALID,
    PLAN_STATUS_SUSPECTED_EXPIRED,
    PLAN_STATUS_USABLE,
    build_output_template,
    clip_err,
    default_failed_jobs,
    default_tokens_data,
    detect_cookies_browser,
    detect_js_runtime,
    effective_tokens_data,
    ensure_standard_state_files,
    ensure_ytdlp_installed,
    get_ytdlp_cmd_display,
    get_ytdlp_version,
    load_json_dict,
    log_event,
    mark_plan_status,
    now_ts,
    plan_is_fresh,
    plan_status,
    project_paths,
    read_urls,
    run_stream,
    save_json,
    token_runtime_summary,
    to_int,
    touch_plan_verified,
    validate_downloaded_file,
)
from router import (
    cache_key_for_url,
    classify_url,
    get_adapter,
    get_adapter_for_url,
)

# 项目路径配置
PATHS = project_paths(__file__)
PROJECT_ROOT = PATHS["project_root"]
DOWNLOADS_DIR = PATHS["downloads_dir"]

# ===========================================================================
# 下载行为配置
# ===========================================================================
# 网络连接相关
USE_IPV4 = True              # 强制使用 IPv4（避免某些网络环境下 IPv6 不通）
SOCKET_TIMEOUT = 60          # 单个 TCP 连接超时时间（秒）

# 重试策略（针对网络不稳定情况的保障机制）
RETRIES = 50                 # 整体下载失败的最大重试次数
FRAGMENT_RETRIES = 50        # 单个分片下载失败的最大重试次数
RETRY_SLEEP_COUNT = 10       # 重试前等待的次数（与下面的 sleep 配合）
HTTP_RETRY_SLEEP = "10"      # HTTP 请求重试间隔（秒）
FRAGMENT_RETRY_SLEEP = "5"   # 分片重试间隔（秒）

# 下载速度与并发控制
CONCURRENT_FRAGMENTS = 1     # 同时下载的分片数。设为 1 最稳定，设为更高值更快但可能触发限流
SLEEP_REQUESTS_SECONDS = 1.0 # 请求之间的等待时间（秒），减少请求频率降低被限流概率

# 同一计划的最大尝试次数（每次尝试都是完整的下载流程）
DOWNLOAD_ATTEMPTS_PER_PLAN = 2
# 两次尝试之间的等待时间（秒）
RETRY_WAIT_SECONDS = 20

# 计划有效期（秒）
PLAN_TTL_SECONDS_DEFAULT = 86400

# 认定为最终完整视频文件的扩展名集合
FINAL_VIDEO_EXTS = {".mkv", ".webm", ".mp4"}

# 进程长时间无输出时的判定阈值（秒）
STALL_SECONDS = 90


# ===========================================================================
# 文件类型判断
# ===========================================================================

def is_partial_file(path: Path) -> bool:
    """
    判断文件是否为「未完成的断点续传文件」。
    
    yt-dlp 在下载过程中会先创建以下格式的临时文件：
      - .part 后缀：主要的临时下载文件
      - .ytdl 后缀：yt-dlp 的元数据文件
      - .temp 后缀：临时文件
      - .part-Frag 中间名：分片下载的中间文件
    这些文件不算「下载完成」，不应被当作成功的结果。
    """
    name = path.name.lower()
    return (
        name.endswith(".part")
        or name.endswith(".ytdl")
        or name.endswith(".temp")
        or ".part-" in name
    )


def is_final_video_file(path: Path) -> bool:
    """
    判断文件是否为「完整的最终视频文件」。
    必须满足：不是临时文件 AND 扩展名在 FINAL_VIDEO_EXTS 中。
    """
    return (not is_partial_file(path)) and path.suffix.lower() in FINAL_VIDEO_EXTS


def get_required_height(plan: Dict[str, Any]) -> int:
    """从下载计划中获取要求的分辨率高度。"""
    return to_int(plan.get("height"), 0)


def get_plan_fragment(plan: Dict[str, Any]) -> str:
    """
    从下载计划提取文件名的固定后缀片段（不含标题部分和扩展名）。
    
    示例：" [LJkIVzy7DSc] [client-auto] [2160p] [adaptive-313_plus_251]"
    
    这个片段用于在 downloads/ 目录中搜索与此计划相关的文件
    （无论视频标题是什么，只要有相同的 ID 和格式，就属于同一计划）。
    """
    template = build_output_template(plan)
    parts = template.split("%(title)s", 1)
    frag = parts[1] if len(parts) == 2 else template
    frag = frag.replace(".%(ext)s", "").strip()
    return frag


def find_plan_related_files(plan: Dict[str, Any]) -> List[Path]:
    """
    在 downloads/ 目录中找出所有与此计划相关的文件（包括完整文件和临时文件）。
    
    匹配规则：文件名中包含计划的固定后缀片段（ID + 格式信息）。
    结果按修改时间从新到旧排序（最近修改的文件排在最前面）。
    """
    frag = get_plan_fragment(plan)
    results: List[Path] = []

    if not DOWNLOADS_DIR.exists():
        return results

    for p in DOWNLOADS_DIR.iterdir():
        if p.is_file() and frag in p.name:
            results.append(p)

    results.sort(key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)
    return results


def find_existing_final_files(plan: Dict[str, Any]) -> List[Path]:
    """找出与此计划相关的所有完整视频文件（排除临时文件）。"""
    return [p for p in find_plan_related_files(plan) if is_final_video_file(p)]


def find_existing_partial_files(plan: Dict[str, Any]) -> List[Path]:
    """找出与此计划相关的所有未完成临时文件（断点续传文件）。"""
    return [p for p in find_plan_related_files(plan) if is_partial_file(p)]


# ===========================================================================
# 文件验证与复用
# ===========================================================================

def handle_existing_final_files(plan: Dict[str, Any]) -> Tuple[bool, Optional[Path]]:
    """
    检查是否已存在符合要求的完整视频文件，如果存在则直接复用（跳过下载）。
    
    这个函数在每次下载开始前调用，防止重复下载已有的文件。
    验证通过的标准：文件完整 + 实际分辨率 >= 计划要求的分辨率。
    
    返回：
        (True, 文件路径): 找到可复用的文件
        (False, None): 没有找到，需要重新下载
    """
    required_height = get_required_height(plan)
    files = find_existing_final_files(plan)

    if not files:
        return False, None

    for f in files:
        ok, msg, info = validate_downloaded_file(f, required_height)
        if ok:
            print(f"[Info] 已存在达标的完整文件，直接复用: {f.name}")
            print(f"[Info] {msg}")
            log_event(
                PATHS["run_log_file"], "download_by_plan", "info", "reuse_existing_final",
                cache_key=cache_key_for_url(str(plan["url"])),
                path=str(f), height=required_height,
            )
            return True, f

    return False, None


def validate_plan_result(plan: Dict[str, Any]) -> Tuple[bool, str, Optional[Path]]:
    """
    在 yt-dlp 返回后，验证下载结果是否真的成功了。
    
    验证流程：
      1. 查找与计划匹配的完整文件
      2. 如果找到，用 ffprobe 检测实际分辨率是否达标
      3. 如果没有完整文件但有 .part 文件，说明下载未完成
    
    返回：
        (成功, 描述信息, 文件路径或None)
    """
    required_height = get_required_height(plan)
    files = find_existing_final_files(plan)

    if not files:
        partials = find_existing_partial_files(plan)
        if partials:
            return False, "下载未完成，仍有断点续传文件", None
        return False, "未找到与此计划匹配的完整输出文件", None

    for f in files:
        ok, msg, info = validate_downloaded_file(f, required_height)
        if ok:
            return True, f"{f.name} | {msg}", f

    return False, "找到完整文件，但实际分辨率不达标", files[0]


# ===========================================================================
# 错误分类
# ===========================================================================

def looks_like_retryable_download_error(text: str) -> bool:
    """
    判断错误输出是否属于「可重试」的临时性错误。
    
    这类错误通常是网络波动或临时限流导致，稍等后重试有可能成功：
      - HTTP 403（临时访问被拒）
      - 连接超时（网络不稳定）
      - 无法下载视频数据（临时服务器问题）
      - 格式不可用（可能是临时限制）
    """
    t = (text or "").lower()
    return any(x in t for x in [
        "http error 403",
        "forbidden",
        "read timed out",
        "timed out",
        "unable to download video data",
        "requested format is not available",
        "missing a url",
        "sabr-only",
    ])


def looks_like_bot_check_error(text: str) -> bool:
    """
    判断错误输出是否为 YouTube 的机器人验证错误。
    
    YouTube 有时会要求用户登录验证自己不是机器人，
    这种情况下需要使用浏览器 cookies 来绕过验证。
    
    注意：YouTube 错误信息使用了 Unicode 右单引号（U+2019），
    而非普通 ASCII 单引号，这里使用更宽松的匹配方式来兼容。
    """
    t = (text or "").lower()
    if "not a bot" in t:
        if "sign in to confirm you" in t or "confirm you" in t:
            return True
    return False


# ===========================================================================
# 自动重试：使用浏览器 cookies 重新探测
# ===========================================================================

def auto_reprobe_with_cookies(
    ytdlp_cmd: List[str],
    url: str,
    tokens_data: Dict[str, Any],
    js_runtime: str,
    env_state: Dict[str, Any],
    original_plan: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    【自动重试第一级】使用浏览器 cookies 重新探测。
    
    当检测到 bot check 错误时，说明当前 IP 或会话被 YouTube 标记为可疑，
    使用已登录浏览器的 cookies 可以让 YouTube 确认是正常用户，从而继续下载。
    
    重要原则：保持原始分辨率要求（不降低标准），
    如果带 cookies 也无法获得 4K，返回 None 让上层决定是否进一步处理。
    
    参数：
        ytdlp_cmd: yt-dlp 命令
        url: 视频 URL
        tokens_data: 当前 Token 数据
        js_runtime: JS 运行时名称
        env_state: 环境状态字典
        original_plan: 原始下载计划（用于获取原始分辨率要求）
    返回：
        新的下载计划字典（成功时），或 None（失败时）
    """
    print("[Auto-Reprobe] 检测到机器人验证错误，尝试使用浏览器 cookies 重新探测...")

    # 获取浏览器配置
    cookies_browser = None
    browser = env_state.get("browser") if isinstance(env_state, dict) else None
    if isinstance(browser, dict):
        cb = str(browser.get("cookies_browser") or "").strip()
        if cb:
            cookies_browser = cb

    if not cookies_browser:
        cookies_browser = detect_cookies_browser()

    if not cookies_browser:
        print("[Auto-Reprobe] 错误：未检测到已安装的浏览器，无法使用 cookies")
        return None

    print(f"[Auto-Reprobe] 使用浏览器: {cookies_browser}")

    import sys
    scripts_dir = Path(__file__).parent
    sys.path.insert(0, str(scripts_dir))

    try:
        from probe_best_plan import run_probe_round

        # 保持原始的分辨率要求（严格模式：不因为重试就降低标准）
        min_height = 2160  # 默认要求 4K
        if original_plan:
            original_height = to_int(original_plan.get("height"), 0)
            if original_height > 0:
                min_height = original_height

        print(f"[Auto-Reprobe] 最低分辨率要求: {min_height}p（严格保持，不降低标准）")

        plan, best_seen_height = run_probe_round(
            ytdlp_cmd=ytdlp_cmd, url=url,
            cookies_browser=cookies_browser, js_runtime=js_runtime,
            tokens_data=tokens_data, min_height=min_height, verbose=True,
        )

        if plan:
            actual_height = to_int(plan.get("height"), 0)
            print(f"[Auto-Reprobe] 成功获得 {actual_height}p！格式: {plan.get('format_expr')} | cookies={cookies_browser}")
            return plan
        else:
            print(f"[Auto-Reprobe] 失败：视频最高只有 {best_seen_height}p，不满足 {min_height}p 要求")
            print("[Auto-Reprobe] 可能是 Token 失效（切换 VPN 后常见），将尝试刷新 Token")
            return None

    except Exception as e:
        print(f"[Auto-Reprobe] 异常: {str(e)}")
        return None


# ===========================================================================
# 自动重试：刷新 Token 后重新探测
# ===========================================================================

def auto_reprobe_with_fresh_tokens(
    ytdlp_cmd: List[str],
    url: str,
    js_runtime: str,
    env_state: Dict[str, Any],
    original_plan: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    【自动重试第二级】使用当前 tokens.json 中的最新 Token 重新探测。
    
    此函数会重新读取 state/tokens.json（用户可能在外部已更新了 Token），
    然后尝试重新探测视频格式。
    
    如果返回 None，说明即使用最新 Token 也无法获得目标分辨率，
    视频本身可能没有 4K 内容，将被标记为 invalid 并跳过。
    
    注意：自动从浏览器抓取 Token 的功能已移除（需要安装 playwright 依赖，
    配置复杂且不稳定）。如果遇到 Token 失效问题，请手动通过以下命令更新 Token：
        python3 scripts/refresh_context.py --set-visitor-data "xxx" --set-po-token "yyy"
    详见 README.md 的「Token 配置」部分。
    """
    import sys
    scripts_dir = Path(__file__).parent

    # 从磁盘重新读取最新的 tokens.json（用户可能已在外部手动更新）
    fresh_tokens = load_json_dict(PATHS["tokens_file"], default_tokens_data())
    fresh_summary = token_runtime_summary(effective_tokens_data(fresh_tokens))

    if not fresh_summary["visitor_data_set"] and not fresh_summary["po_token_set"]:
        print("[Token-Refresh] tokens.json 中没有可用 Token，无法重试")
        print("[Token-Refresh] 请手动更新 Token 后重新运行：")
        print("[Token-Refresh]   python3 scripts/refresh_context.py --set-visitor-data 'xxx' --set-po-token 'yyy'")
        return None

    cookies_browser = None
    browser = env_state.get("browser") if isinstance(env_state, dict) else None
    if isinstance(browser, dict):
        cb = str(browser.get("cookies_browser") or "").strip()
        if cb:
            cookies_browser = cb
    if not cookies_browser:
        cookies_browser = detect_cookies_browser()

    print(f"[Token-Refresh] 使用当前 tokens.json 中的 Token 重新探测...")
    print(f"[Token-Refresh] visitor_data 已设置: {'是' if fresh_summary['visitor_data_set'] else '否'}")
    print(f"[Token-Refresh] po_token 已设置: {'是' if fresh_summary['po_token_set'] else '否'}")

    try:
        sys.path.insert(0, str(scripts_dir))
        from probe_best_plan import run_probe_round

        min_height = 2160
        if original_plan:
            original_height = to_int(original_plan.get("height"), 0)
            if original_height > 0:
                min_height = original_height

        print(f"[Token-Refresh] 最低分辨率要求: {min_height}p")

        plan, best_seen_height = run_probe_round(
            ytdlp_cmd=ytdlp_cmd, url=url,
            cookies_browser=cookies_browser, js_runtime=js_runtime,
            tokens_data=effective_tokens_data(fresh_tokens),
            min_height=min_height, verbose=True,
        )

        if plan:
            actual_height = to_int(plan.get("height"), 0)
            print(f"[Token-Refresh] 成功获得 {actual_height}p！")
            return plan
        else:
            print(f"[Token-Refresh] 失败：视频最高仍只有 {best_seen_height}p，不满足 {min_height}p 要求")
            print(f"[Token-Refresh] 结论：此视频本身可能没有 {min_height}p 的内容")
            return None

    except Exception as e:
        print(f"[Token-Refresh] 异常: {str(e)}")
        return None


# ===========================================================================
# 运行时上下文加载
# ===========================================================================

def load_runtime_context() -> Tuple[Optional[List[str]], Dict[str, Any], Dict[str, Any], str]:
    """
    加载下载所需的运行时上下文（yt-dlp 路径、Token、浏览器等）。
    
    优先使用 env_state.json 缓存，避免每次都重新检测系统环境。
    
    返回：
        (ytdlp_cmd, env_state, tokens_data, js_runtime)
    """
    env_state = load_json_dict(PATHS["env_state_file"], {})
    file_tokens = load_json_dict(PATHS["tokens_file"], default_tokens_data())
    tokens = effective_tokens_data(file_tokens)

    ytdlp_cmd = None
    y = env_state.get("ytdlp") if isinstance(env_state, dict) else None
    if isinstance(y, dict) and y.get("ok"):
        cmd = y.get("cmd")
        if isinstance(cmd, list) and cmd:
            ytdlp_cmd = cmd
    if not ytdlp_cmd:
        ytdlp_cmd = ensure_ytdlp_installed(auto_install=False)

    js_runtime = ""
    js = env_state.get("js_runtime") if isinstance(env_state, dict) else None
    if isinstance(js, dict) and js.get("ok"):
        js_runtime = str(js.get("name") or "").strip()
    if not js_runtime or js_runtime == "auto":
        js_runtime = detect_js_runtime()

    return ytdlp_cmd, env_state, tokens, js_runtime


# ===========================================================================
# 状态文件操作
# ===========================================================================

def update_failed_jobs(
    cache_key: str,
    url: str,
    stage: str,
    reason: str,
    used_plan: str,
    has_partial: bool,
) -> None:
    """将下载失败记录写入 state/failed_jobs.json。"""
    failed = load_json_dict(PATHS["failed_jobs_file"], default_failed_jobs())
    failed[cache_key] = {
        "url": url,
        "last_failed_at": int(time.time()),
        "stage": stage,
        "reason": reason,
        "used_plan": used_plan,
        "has_partial": has_partial,
        "suggestion": "refresh_context_or_probe_again",
    }
    save_json(PATHS["failed_jobs_file"], failed)


def load_plan_cache() -> Dict[str, Any]:
    """读取下载计划缓存文件。"""
    return load_json_dict(PATHS["plan_cache_file"], {})


def save_plan_cache(data: Dict[str, Any]) -> None:
    """写入下载计划缓存文件。"""
    save_json(PATHS["plan_cache_file"], data)


def update_plan_cache_entry(plan_cache: Dict[str, Any], cache_key: str, plan: Dict[str, Any]) -> None:
    """更新单条计划缓存记录并立即写入文件。"""
    plan_cache[cache_key] = plan
    save_plan_cache(plan_cache)


def classify_plan_failure(plan: Dict[str, Any], output: str, has_partial: bool) -> str:
    """
    根据下载失败的输出内容，判断应将计划标记为哪种失败状态。
    
    返回的状态：
      - suspected_expired: 计划可能过期了（通用情况），建议重新探测
      - usable: 有断点续传文件时，计划本身仍视为可用（下次可续传）
    
    注意：这里比较保守，大多数错误都标记为 suspected_expired 而不是 invalid，
    因为「invalid」表示确认永远不可用，应该谨慎使用。
    """
    text = (output or "").lower()

    # 如果有断点续传文件，说明只是下载中断，计划本身还是可用的
    if has_partial:
        return PLAN_STATUS_USABLE

    if "requested format is not available" in text:
        return PLAN_STATUS_SUSPECTED_EXPIRED

    if "http error 403" in text or "forbidden" in text:
        return PLAN_STATUS_SUSPECTED_EXPIRED

    return PLAN_STATUS_SUSPECTED_EXPIRED


# ===========================================================================
# 核心下载逻辑
# ===========================================================================

def attempt_download_with_plan(
    ytdlp_cmd: List[str],
    plan: Dict[str, Any],
    tokens_data: Dict[str, Any],
    js_runtime: str,
) -> Tuple[int, str, bool]:
    """
    按给定计划执行下载（可能包含多次重试）。
    
    下载流程：
      1. 检查是否已有达标的完整文件（有则直接复用）
      2. 检查是否有断点续传文件（有则续传）
      3. 通过平台适配器构建下载命令
      4. 执行下载，实时显示进度
      5. 验证下载结果（分辨率是否达标）
      6. 如遇可重试错误，等待后重试（最多 DOWNLOAD_ATTEMPTS_PER_PLAN 次）
    
    参数：
        ytdlp_cmd: yt-dlp 命令
        plan: 下载计划字典（来自 plan_cache.json）
        tokens_data: 当前 Token 数据
        js_runtime: JS 运行时名称
    返回：
        (退出码, 输出内容, 是否有断点续传文件)
        退出码为 0 表示成功
    """
    cache_key = cache_key_for_url(str(plan["url"]))

    # 检查是否已有达标的完整文件（无需重新下载）
    existing_ok, existing_file = handle_existing_final_files(plan)
    if existing_ok and existing_file:
        return 0, "", False

    # 检查断点续传文件
    partials_before = find_existing_partial_files(plan)
    if partials_before:
        print("[Info] 检测到断点续传文件，将从断点继续下载")
        for p in partials_before:
            print(f"[Info] 续传文件: {p.name}")

    last_output = ""
    had_partial = bool(partials_before)
    plan_for_cmd = dict(plan)  # 复制计划，避免修改原始数据

    # 通过 router 获取对应平台的适配器
    adapter = get_adapter_for_url(str(plan["url"]))

    for attempt in range(1, DOWNLOAD_ATTEMPTS_PER_PLAN + 1):
        if attempt > 1:
            print(f"[Info] 第 {attempt}/{DOWNLOAD_ATTEMPTS_PER_PLAN} 次尝试，等待 {RETRY_WAIT_SECONDS}s 后重试")
            time.sleep(RETRY_WAIT_SECONDS)

        # 通过适配器构建下载命令（各平台参数不同）
        cmd = adapter.build_download_cmd(
            ytdlp_cmd=ytdlp_cmd,
            plan=plan_for_cmd,
            tokens_data=tokens_data,
            js_runtime=js_runtime,
            downloads_dir=DOWNLOADS_DIR,
        )

        print("[Info] 下载命令:", " ".join(cmd))
        log_event(
            PATHS["run_log_file"], "download_by_plan", "info", "download_start",
            cache_key=cache_key, url=str(plan["url"]),
            format_expr=str(plan["format_expr"]), attempt=attempt,
        )

        try:
            rc, out, stalled = run_stream(cmd, stall_seconds=STALL_SECONDS)
        except KeyboardInterrupt:
            print("\n[Stop] 用户手动中断下载")
            log_event(PATHS["run_log_file"], "download_by_plan", "warn", "download_interrupted",
                      cache_key=cache_key, url=str(plan["url"]))
            return 130, last_output, had_partial

        last_output = out

        # 验证下载结果
        ok, result_msg, result_file = validate_plan_result(plan)
        if rc == 0 and ok:
            print(f"[Info] 下载验证通过: {result_msg}")
            log_event(
                PATHS["run_log_file"], "download_by_plan", "info", "download_success",
                cache_key=cache_key, url=str(plan["url"]),
                path=str(result_file) if result_file else "",
                format_expr=str(plan["format_expr"]),
            )
            return 0, last_output, had_partial

        # 检查是否有新的断点续传文件
        partials_after = find_existing_partial_files(plan)
        if partials_after:
            had_partial = True
            print("[Warn] 下载中断，保留断点续传文件，下次运行可继续")
            for p in partials_after:
                print(f"[Warn] 续传文件: {p.name}")

        if result_msg:
            print(f"[Warn] {result_msg}")

        # 特殊处理：浏览器 cookie 编码错误，改用无 cookies 重试
        if (rc != 0 and plan_for_cmd.get("cookies_browser")
                and "UnicodeEncodeError" in (out or "")
                and "latin-1" in (out or "")):
            print("[Info] 检测到浏览器 cookie 编码错误，改用无 cookies 方式重试")
            plan_for_cmd["cookies_browser"] = None
            continue

        # 如果是可重试的临时性错误，等待后继续
        if attempt < DOWNLOAD_ATTEMPTS_PER_PLAN and looks_like_retryable_download_error(out):
            print("[Warn] 检测到可重试的临时错误，将使用同一计划重试")
            log_event(
                PATHS["run_log_file"], "download_by_plan", "warn", "download_retryable_error",
                cache_key=cache_key, url=str(plan["url"]),
                attempt=attempt, reason=clip_err(out, 300),
            )
            continue

        break  # 非可重试错误，直接退出循环

    # 下载失败，记录失败信息
    partials = find_existing_partial_files(plan)
    if partials:
        had_partial = True

    reason = clip_err(last_output, 500) if last_output else "download failed"
    update_failed_jobs(
        cache_key=cache_key, url=str(plan["url"]),
        stage="download", reason=reason,
        used_plan=str(plan.get("format_expr") or ""),
        has_partial=bool(partials),
    )
    log_event(
        PATHS["run_log_file"], "download_by_plan", "error", "download_failed",
        cache_key=cache_key, url=str(plan["url"]),
        reason=reason, has_partial=bool(partials),
    )

    # 打印最后几行输出，帮助诊断失败原因
    tail = "\n".join((last_output or "").splitlines()[-30:])
    if tail:
        print("\n[最后输出]")
        print(tail)

    return 1, last_output, had_partial


# ===========================================================================
# URL 选择和参数解析
# ===========================================================================

def select_urls(args_url: Optional[str]) -> List[str]:
    """根据命令行参数选择要处理的 URL 列表。"""
    if args_url:
        return [args_url]
    return read_urls(PATHS["urls_file"])


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(
            "按 state/plan_cache.json 中的计划执行视频下载。\n"
            "此脚本不会自行探测视频格式，如果没有计划则跳过该 URL。\n"
            "如需探测，请先运行 probe_best_plan.py。"
        )
    )
    ap.add_argument(
        "--url",
        help="只下载这一个 URL（使用已缓存的计划）"
    )
    ap.add_argument(
        "--plan-ttl-seconds",
        type=int,
        default=PLAN_TTL_SECONDS_DEFAULT,
        help=f"计划有效期（秒，默认 {PLAN_TTL_SECONDS_DEFAULT}）。超过此时间的计划会显示过期警告。"
    )
    return ap


# ===========================================================================
# 主函数
# ===========================================================================

def main() -> None:
    ap = build_arg_parser()
    args = ap.parse_args()

    ensure_standard_state_files(PATHS, need_downloads_dir=True)

    print("=== download_by_plan ===")
    print(f"项目根目录: {PROJECT_ROOT}")
    print(f"下载目录: {DOWNLOADS_DIR}")
    print(f"计划缓存文件: {PATHS['plan_cache_file']}")

    urls = select_urls(args.url)
    if not urls:
        print("[Info] urls.txt 中没有可处理的 URL")
        return

    ytdlp_cmd, env_state, tokens_data, js_runtime = load_runtime_context()
    if not ytdlp_cmd:
        print("[Error] 未找到可用的 yt-dlp，请先运行 python3 scripts/refresh_context.py 安装")
        log_event(PATHS["run_log_file"], "download_by_plan", "error", "missing_ytdlp")
        return

    summary = token_runtime_summary(tokens_data)

    print(f"[Info] yt-dlp 命令: {get_ytdlp_cmd_display(ytdlp_cmd)}")
    print(f"[Info] yt-dlp 版本: {get_ytdlp_version(ytdlp_cmd)}")
    print(f"[Info] JS 运行时: {js_runtime}")
    print(f"[Info] visitor_data 已设置: {'是' if summary['visitor_data_set'] else '否'}")
    print(f"[Info] po_token 已设置: {'是' if summary['po_token_set'] else '否'}")
    print(f"[Info] token_client: {summary['token_client']}")
    print(f"[Info] token 来源: {summary['token_source']}")

    plan_cache = load_plan_cache()
    failed_jobs = load_json_dict(PATHS["failed_jobs_file"], default_failed_jobs())
    failures: List[str] = []

    for idx, url in enumerate(urls, start=1):
        cache_key = cache_key_for_url(url)
        print(f"\n[{idx}/{len(urls)}] {url}")
        plan = plan_cache.get(cache_key)

        # 检查是否有可用计划
        if not isinstance(plan, dict):
            # 如果之前已记录为「没有计划」失败，直接跳过，不重复记录
            prev_fail = failed_jobs.get(cache_key)
            if isinstance(prev_fail, dict) and prev_fail.get("reason") == "missing local plan":
                print("[Info] 跳过：本地无下载计划（之前已记录），请先运行 probe_best_plan.py 探测")
            else:
                print("[Error] 本地没有此 URL 的下载计划，请先运行 probe_best_plan.py 探测")
                update_failed_jobs(
                    cache_key=cache_key, url=url, stage="download",
                    reason="missing local plan", used_plan="", has_partial=False,
                )
                log_event(PATHS["run_log_file"], "download_by_plan", "error", "missing_plan",
                          cache_key=cache_key, url=url)
                failures.append(url)
            continue

        # 检查本地是否已存在完整的达标文件（跳过，无需重新下载）
        existing_ok, existing_file = handle_existing_final_files(plan)
        if existing_ok and existing_file:
            print(f"[Info] 已有完整达标文件，跳过: {existing_file.name}")
            continue

        # 检查计划状态
        status = plan_status(plan)
        if status == PLAN_STATUS_INVALID:
            print("[Info] 此计划已标记为无效（视频本身没有目标分辨率），跳过")
            # 只在 failed_jobs 中没有记录时才写入，避免重复写
            if not isinstance(failed_jobs.get(cache_key), dict):
                update_failed_jobs(
                    cache_key=cache_key, url=url, stage="download",
                    reason="plan marked invalid", used_plan=str(plan.get("format_expr") or ""),
                    has_partial=False,
                )
                log_event(PATHS["run_log_file"], "download_by_plan", "error", "invalid_plan",
                          cache_key=cache_key, url=url)
                failures.append(url)
            continue

        if not plan_is_fresh(plan, args.plan_ttl_seconds):
            print("[Warn] 计划已超过有效期，但本次仍按缓存计划尝试下载（如失败请重新探测）")
            log_event(PATHS["run_log_file"], "download_by_plan", "warn", "stale_plan_used",
                      cache_key=cache_key, url=url)

        print(f"[Info] 使用计划: {plan.get('format_expr', '')} | 状态={status}")

        log_event(
            PATHS["run_log_file"], "download_by_plan", "info", "download_plan_context",
            cache_key=cache_key, url=url,
            token_source=summary["token_source"], token_client=summary["token_client"],
            visitor_data_set=summary["visitor_data_set"], po_token_set=summary["po_token_set"],
        )

        # 执行下载
        rc, output, had_partial = attempt_download_with_plan(
            ytdlp_cmd=ytdlp_cmd, plan=plan,
            tokens_data=tokens_data, js_runtime=js_runtime,
        )

        if rc == 0:
            # 下载成功：更新计划验证时间
            plan = touch_plan_verified(plan)
            update_plan_cache_entry(plan_cache, cache_key, plan)
            continue

        # ---- 下载失败后的自动处理 ----

        # 检测是否为 bot check 错误，触发自动重试
        if looks_like_bot_check_error(output):
            print("[Warn] 检测到 YouTube 机器人验证错误，触发自动重试流程...")
            log_event(PATHS["run_log_file"], "download_by_plan", "warn", "bot_check_detected",
                      cache_key=cache_key, url=url)

            # 第一级重试：使用浏览器 cookies 重新探测
            new_plan = auto_reprobe_with_cookies(
                ytdlp_cmd=ytdlp_cmd, url=url, tokens_data=tokens_data,
                js_runtime=js_runtime, env_state=env_state, original_plan=plan,
            )

            if new_plan:
                # 成功获得新计划，保存并重试下载
                print("[Info] 已获得新计划，使用新计划重新下载...")
                plan = new_plan
                plan = touch_plan_verified(plan)
                update_plan_cache_entry(plan_cache, cache_key, plan)

                log_event(PATHS["run_log_file"], "download_by_plan", "info", "auto_reprobe_success",
                          cache_key=cache_key, url=url,
                          new_format_expr=str(new_plan.get("format_expr")),
                          cookies_browser=str(new_plan.get("cookies_browser")))

                rc2, output2, had_partial2 = attempt_download_with_plan(
                    ytdlp_cmd=ytdlp_cmd, plan=plan,
                    tokens_data=tokens_data, js_runtime=js_runtime,
                )

                if rc2 == 0:
                    plan = touch_plan_verified(plan)
                    update_plan_cache_entry(plan_cache, cache_key, plan)
                    print("[Info] 使用新计划下载成功！")
                    continue
                else:
                    output = output2
                    had_partial = had_partial2
                    print("[Warn] 使用新计划下载仍然失败")
            else:
                # 第一级重试失败，尝试第二级：刷新 Token
                print("[Warn] 带 cookies 重探失败，尝试刷新 Token...")

                new_plan_with_fresh_tokens = auto_reprobe_with_fresh_tokens(
                    ytdlp_cmd=ytdlp_cmd, url=url, js_runtime=js_runtime,
                    env_state=env_state, original_plan=plan,
                )

                if new_plan_with_fresh_tokens:
                    # 刷新 Token 成功，保存新计划并重试下载
                    print("[Info] Token 刷新成功，使用新计划重新下载...")

                    plan = new_plan_with_fresh_tokens
                    plan = touch_plan_verified(plan)
                    update_plan_cache_entry(plan_cache, cache_key, plan)

                    log_event(PATHS["run_log_file"], "download_by_plan", "info", "token_refresh_success",
                              cache_key=cache_key, url=url,
                              new_format_expr=str(new_plan_with_fresh_tokens.get("format_expr")),
                              cookies_browser=str(new_plan_with_fresh_tokens.get("cookies_browser")))

                    # 用最新的 tokens.json 进行下载
                    rc3, output3, had_partial3 = attempt_download_with_plan(
                        ytdlp_cmd=ytdlp_cmd, plan=plan,
                        tokens_data=load_json_dict(PATHS["tokens_file"], default_tokens_data()),
                        js_runtime=js_runtime,
                    )

                    if rc3 == 0:
                        plan = touch_plan_verified(plan)
                        update_plan_cache_entry(plan_cache, cache_key, plan)
                        print("[Info] 刷新 Token 后下载成功！")
                        continue
                    else:
                        output = output3
                        had_partial = had_partial3
                        print("[Warn] 刷新 Token 后下载仍然失败")
                else:
                    # 两级重试都失败：确认视频本身没有 4K
                    print("[Warn] 自动重试全部失败：即使刷新 Token 也无法获得目标分辨率")
                    print("[Info] 结论：此视频本身没有 4K 内容，标记为 invalid 并跳过")

                    # 标记计划为无效，后续运行不再尝试
                    plan = mark_plan_status(
                        plan, PLAN_STATUS_INVALID,
                        reason="视频本身没有目标分辨率（4K），即使刷新 Token 也无法获得",
                    )
                    update_plan_cache_entry(plan_cache, cache_key, plan)

                    update_failed_jobs(
                        cache_key=cache_key, url=url, stage="token_refresh",
                        reason="即使刷新 Token 也无法获得目标分辨率，视频本身没有 4K",
                        used_plan=str(plan.get("format_expr") or ""),
                        has_partial=had_partial,
                    )

                    log_event(PATHS["run_log_file"], "download_by_plan", "error", "no_4k_after_token_refresh",
                              cache_key=cache_key, url=url, reason="视频本身没有 4K 分辨率")

                    failures.append(url)
                    continue  # 跳过此视频，继续下一个

        # 普通失败：更新计划状态
        new_status = classify_plan_failure(plan, output, had_partial)
        plan = mark_plan_status(plan, new_status, reason=clip_err(output, 300))
        update_plan_cache_entry(plan_cache, cache_key, plan)

        failures.append(url)

    print("\n=== 下载完成 ===")
    print(f"下载目录: {DOWNLOADS_DIR}")

    if failures:
        print(f"[结果] 失败: {len(failures)} 个")
        for u in failures:
            print(f"  {u}")
    else:
        print("[结果] 所有视频下载成功")


if __name__ == "__main__":
    main()
