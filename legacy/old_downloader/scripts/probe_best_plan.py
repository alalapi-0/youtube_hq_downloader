#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_best_plan.py — 视频格式探测模块

【这个脚本做什么？】
  在不下载视频的情况下，探测指定 URL 能下载到的最佳画质格式，
  并将结果（「下载计划」）保存到 state/plan_cache.json 中供后续下载使用。

【探测过程】
  1. 读取 urls.txt（或指定的单个 URL）
  2. 对每个 URL，按平台构建多种探测策略（不同客户端类型 × 是否使用 cookies）
  3. 逐个策略调用 yt-dlp --dump-single-json，获取视频的格式列表
  4. 从格式列表中筛选出满足分辨率要求的最佳视频流 + 最佳音频流
  5. 将选定的格式信息保存为「下载计划」

【分辨率要求（严卡 4K 模式）】
  默认严格要求 2160p（4K）。
  低于此分辨率的视频不会生成下载计划，会记录为探测失败并跳过。
  如需修改分辨率要求，请修改下方的 MIN_HEIGHT_DEFAULT 常量，
  或在运行时添加 --min-height 参数（如 --min-height 1080 放宽到 1080p）。

  注意：抖音、TikTok、小红书等平台本身不提供 4K 内容，
        这些平台的适配器会自动将分辨率阈值降级到平台实际最高值。

【使用方式】
  探测 urls.txt 中所有链接：  python3 scripts/probe_best_plan.py
  探测单个链接：               python3 scripts/probe_best_plan.py --url "https://..."
  强制重新探测所有链接：       python3 scripts/probe_best_plan.py --refresh
  只补缺失的计划：             python3 scripts/probe_best_plan.py --only-missing
  修改分辨率要求：             python3 scripts/probe_best_plan.py --min-height 1080
"""

from __future__ import annotations

import argparse
from typing import Any, Dict, List, Optional, Tuple

from common import (
    PLAN_STATUS_SUSPECTED_EXPIRED,
    clip_err,
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
    plan_is_usable,
    project_paths,
    read_urls,
    run_capture_raw,
    safe_json_load,
    save_json,
    to_float,
    to_int,
    token_runtime_summary,
    touch_plan_verified,
    youtube_video_id_from_url,
)
from router import (
    cache_key_for_url,
    classify_url,
    get_adapter,
)

# 项目路径配置
PATHS = project_paths(__file__)
PROJECT_ROOT = PATHS["project_root"]

# ===========================================================================
# 配置参数
# ===========================================================================
# 【重要】修改这里可以改变分辨率要求：
#   2160 = 严格要求 4K（默认，只下载真正的 4K 内容）
#   1440 = 接受 2K 及以上
#   1080 = 接受 1080p 及以上（包括 4K 和 1080p）
#   720  = 接受 720p 及以上
# 注意：降低此值后，部分低画质视频也会被下载，不再严卡 4K
MIN_HEIGHT_DEFAULT = 2160

# 下载计划缓存有效期（秒）。超过此时间的计划会被标记为需要重新探测。
# 86400 = 24 小时
PLAN_TTL_SECONDS_DEFAULT = 86400


# ===========================================================================
# 状态文件读写
# ===========================================================================

def load_plan_cache() -> Dict[str, Any]:
    """读取下载计划缓存文件（state/plan_cache.json）。"""
    return load_json_dict(PATHS["plan_cache_file"], {})


def save_plan_cache(data: Dict[str, Any]) -> None:
    """将下载计划缓存写入文件（state/plan_cache.json）。"""
    save_json(PATHS["plan_cache_file"], data)


def load_tokens_file() -> Dict[str, Any]:
    """读取 YouTube Token 文件（state/tokens.json）。"""
    return load_json_dict(PATHS["tokens_file"], default_tokens_data())


def load_env_state() -> Dict[str, Any]:
    """读取本机环境信息缓存文件（state/env_state.json）。"""
    return load_json_dict(PATHS["env_state_file"], {})


def update_failed_jobs(
    cache_key: str,
    url: str,
    stage: str,
    reason: str,
    used_plan: str = "",
    has_partial: bool = False,
) -> None:
    """
    将探测失败的记录写入 state/failed_jobs.json。
    
    参数：
        cache_key: 缓存键（如 "youtube:LJkIVzy7DSc"）
        url: 原始视频 URL
        stage: 失败阶段（"probe" 表示探测阶段失败）
        reason: 失败原因（来自 yt-dlp 错误输出）
        used_plan: 尝试的格式表达式（探测阶段为空）
        has_partial: 是否有断点续传文件（探测阶段通常为 False）
    """
    failed = load_json_dict(PATHS["failed_jobs_file"], {})
    failed[cache_key] = {
        "url": url,
        "last_failed_at": now_ts(),
        "stage": stage,
        "reason": reason,
        "used_plan": used_plan,
        "has_partial": has_partial,
        "suggestion": "refresh_context_or_probe_again",
    }
    save_json(PATHS["failed_jobs_file"], failed)


# ===========================================================================
# 运行时上下文加载
# ===========================================================================

def load_runtime_context() -> Tuple[Optional[List[str]], Dict[str, Any], Dict[str, Any], str, Optional[str]]:
    """
    加载探测所需的运行时上下文（yt-dlp 路径、Token、浏览器等）。
    
    优先使用 env_state.json 缓存，避免每次都重新检测系统环境。
    
    返回：
        (ytdlp_cmd, env_state, tokens_data, js_runtime, cookies_browser)
    """
    env_state = load_env_state()
    file_tokens = load_tokens_file()
    tokens = effective_tokens_data(file_tokens)

    # yt-dlp 命令：优先用缓存
    ytdlp_cmd = None
    y = env_state.get("ytdlp") if isinstance(env_state, dict) else None
    if isinstance(y, dict) and y.get("ok"):
        cmd = y.get("cmd")
        if isinstance(cmd, list) and cmd:
            ytdlp_cmd = cmd
    if not ytdlp_cmd:
        ytdlp_cmd = ensure_ytdlp_installed(auto_install=False)

    # JS 运行时：优先用缓存
    js_runtime = ""
    js = env_state.get("js_runtime") if isinstance(env_state, dict) else None
    if isinstance(js, dict) and js.get("ok"):
        js_runtime = str(js.get("name") or "").strip()
    if not js_runtime or js_runtime == "auto":
        js_runtime = detect_js_runtime()

    # 浏览器：优先用缓存
    cookies_browser = None
    browser = env_state.get("browser") if isinstance(env_state, dict) else None
    if isinstance(browser, dict):
        cb = str(browser.get("cookies_browser") or "").strip()
        if cb:
            cookies_browser = cb
    if not cookies_browser:
        cookies_browser = detect_cookies_browser()

    return ytdlp_cmd, env_state, tokens, js_runtime, cookies_browser


# ===========================================================================
# 探测命令执行
# ===========================================================================

def fetch_info_for_strategy(cmd: List[str]) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    执行探测命令，解析 yt-dlp 返回的 JSON 格式信息。
    
    参数：
        cmd: 完整的探测命令（由适配器的 build_probe_cmd 构建）
    返回：
        成功时：(视频信息字典, "")
        失败时：(None, 错误信息字符串)
    """
    rc, stdout, stderr = run_capture_raw(cmd)
    if rc != 0:
        return None, clip_err(stderr or stdout)

    obj = safe_json_load(stdout)
    if isinstance(obj, dict):
        return obj, ""

    return None, clip_err(stderr or stdout or "json parse failed")


# ===========================================================================
# 格式筛选与质量评分
# ===========================================================================

def is_valid_media_format(fmt: Dict[str, Any]) -> bool:
    """排除 storyboard（预览缩略图）和 mhtml 等非媒体格式。"""
    format_note = str(fmt.get("format_note") or "").lower()
    ext = str(fmt.get("ext") or "").lower()
    if "storyboard" in format_note:
        return False
    if ext in {"mhtml"}:
        return False
    return True


def is_video_only_format(fmt: Dict[str, Any]) -> bool:
    """判断是否为纯视频流（无音频）。"""
    return str(fmt.get("vcodec") or "none") != "none" and str(fmt.get("acodec") or "none") == "none"


def is_audio_only_format(fmt: Dict[str, Any]) -> bool:
    """判断是否为纯音频流（无视频）。"""
    return str(fmt.get("vcodec") or "none") == "none" and str(fmt.get("acodec") or "none") != "none"


def is_combined_av_format(fmt: Dict[str, Any]) -> bool:
    """判断是否为音视频合并流（视频和音频都有，可直接播放）。"""
    return str(fmt.get("vcodec") or "none") != "none" and str(fmt.get("acodec") or "none") != "none"


def hdr_rank(fmt: Dict[str, Any]) -> int:
    """
    HDR 优先级评分：Dolby Vision/HDR(2) > SDR(1) > 未知(0)
    HDR 视频在支持的显示设备上效果更好。
    """
    dr = str(fmt.get("dynamic_range") or "").upper()
    if any(x in dr for x in ["DV", "DOLBY", "HDR", "PQ", "HLG"]):
        return 2
    if dr == "SDR":
        return 1
    return 0


def video_codec_rank(vcodec: str) -> int:
    """
    视频编码优先级评分（越高越好）：
    AV1(6) > VP9.2(5) > VP9(4) > HEVC(3) > H.264(2) > 其他(1) > 未知(0)
    编码越新，相同画质所需的文件大小越小。
    """
    s = (vcodec or "").lower()
    if "av01" in s: return 6
    if "vp9.2" in s: return 5
    if "vp9" in s: return 4
    if "hev1" in s or "hvc1" in s or "hevc" in s: return 3
    if "avc1" in s or "h264" in s: return 2
    if s and s != "none": return 1
    return 0


def audio_codec_rank(acodec: str) -> int:
    """
    音频编码优先级评分：
    Opus(5) > AAC(4) > Vorbis(3) > 其他(1) > 未知(0)
    """
    s = (acodec or "").lower()
    if "opus" in s: return 5
    if "aac" in s or "mp4a" in s: return 4
    if "vorbis" in s: return 3
    if s and s != "none": return 1
    return 0


def video_rank_tuple(fmt: Dict[str, Any]) -> Tuple:
    """
    生成视频格式的综合评分元组（用于比较选出最佳格式）。
    
    优先级顺序：分辨率 > 宽度 > 帧率 > HDR > 码率 > 文件大小 > 编码
    Python 的 max() 会自动按元组从左到右比较。
    """
    return (
        to_int(fmt.get("height")),
        to_int(fmt.get("width")),
        to_float(fmt.get("fps")),
        hdr_rank(fmt),
        to_float(fmt.get("tbr")) or to_float(fmt.get("vbr")),
        to_int(fmt.get("filesize")) or to_int(fmt.get("filesize_approx")),
        video_codec_rank(str(fmt.get("vcodec") or "")),
    )


def audio_rank_tuple(fmt: Dict[str, Any]) -> Tuple:
    """
    生成音频格式的综合评分元组（用于比较选出最佳音频流）。
    
    优先级顺序：声道数 > 采样率 > 比特率 > 文件大小 > 编码
    """
    return (
        to_int(fmt.get("audio_channels")),
        to_int(fmt.get("asr")),
        to_float(fmt.get("abr")) or to_float(fmt.get("tbr")),
        to_int(fmt.get("filesize")) or to_int(fmt.get("filesize_approx")),
        audio_codec_rank(str(fmt.get("acodec") or "")),
    )


def choose_candidate_from_info(info: Dict[str, Any], min_height: int) -> Optional[Dict[str, Any]]:
    """
    从 yt-dlp 返回的视频信息中，选出满足分辨率要求的最佳下载方案。
    
    选择逻辑（优先级从高到低）：
      1. adaptive 模式（首选）：从纯视频流中选最佳视频 + 从纯音频流中选最佳音频
         优点：可以分别获取最高质量的视频和音频，合并后质量最好
         缺点：需要 ffmpeg 合并，输出为 mkv 格式
      2. combined 模式（备选）：直接使用音视频合并的流
         优点：无需合并，下载后直接可以播放
         缺点：通常分辨率有限（高分辨率一般没有合并流）
    
    参数：
        info: yt-dlp --dump-single-json 返回的视频信息字典
        min_height: 最低要求的分辨率高度（严格要求，低于此值返回 None）
    返回：
        满足要求的下载方案字典，或 None（没有满足要求的格式）
    """
    formats = info.get("formats") or []
    if not isinstance(formats, list) or not formats:
        return None

    # 过滤掉非媒体格式（storyboard 等）
    valid_formats = [f for f in formats if isinstance(f, dict) and is_valid_media_format(f)]

    # 按类型分组，并过滤分辨率
    video_only = [f for f in valid_formats if is_video_only_format(f) and to_int(f.get("height")) >= min_height]
    audio_only = [f for f in valid_formats if is_audio_only_format(f)]
    combined_av = [f for f in valid_formats if is_combined_av_format(f) and to_int(f.get("height")) >= min_height]

    # 从各类型中选出最佳的
    best_video = max(video_only, key=video_rank_tuple) if video_only else None
    best_audio = max(audio_only, key=audio_rank_tuple) if audio_only else None
    best_combined = max(combined_av, key=video_rank_tuple) if combined_av else None

    # 优先选 adaptive 模式（最高画质）
    if best_video and best_audio:
        video_id = str(best_video.get("format_id"))
        audio_id = str(best_audio.get("format_id"))
        return {
            "mode": "adaptive",
            "format_expr": f"{video_id}+{audio_id}",  # yt-dlp 格式：视频ID+音频ID
            "video": best_video,
            "audio": best_audio,
            "height": to_int(best_video.get("height")),
            "width": to_int(best_video.get("width")),
            "fps": to_float(best_video.get("fps")),
            "video_id": video_id,
            "audio_id": audio_id,
        }

    # 备选：combined 模式（直接可播放的合并流）
    if best_combined:
        format_id = str(best_combined.get("format_id"))
        return {
            "mode": "combined",
            "format_expr": format_id,
            "video": best_combined,
            "audio": None,
            "height": to_int(best_combined.get("height")),
            "width": to_int(best_combined.get("width")),
            "fps": to_float(best_combined.get("fps")),
            "video_id": format_id,
            "audio_id": None,
        }

    return None  # 没有满足要求的格式


def candidate_rank(plan: Dict[str, Any]) -> Tuple:
    """
    计算下载计划的综合评分（用于在多个计划中选出最佳的）。
    
    优先级：视频质量 > 是否 adaptive 模式（adaptive 优于 combined）> 音频质量
    """
    v = plan["video"]
    a = plan.get("audio")
    mode_rank = 1 if plan.get("mode") == "adaptive" else 0
    vr = video_rank_tuple(v)
    ar = audio_rank_tuple(a) if isinstance(a, dict) else (0, 0, 0, 0, 0)
    return vr + (mode_rank,) + ar


def describe_candidate(plan: Dict[str, Any]) -> str:
    """
    生成下载计划的简要描述字符串，用于日志显示。
    
    示例输出：2160p 25fps | mode=adaptive | client=auto | v=313 | a=251
    """
    h = to_int(plan.get("height"))
    fps = to_float(plan.get("fps"))
    mode = str(plan.get("mode"))
    vid = str(plan.get("video_id"))
    aid = str(plan.get("audio_id") or "-")
    client = "auto" if plan.get("yt_client") is None else str(plan.get("yt_client"))
    return f"{h}p {fps:g}fps | mode={mode} | client={client} | v={vid} | a={aid}"


# ===========================================================================
# 核心探测逻辑
# ===========================================================================

def run_probe_round(
    ytdlp_cmd: List[str],
    url: str,
    cookies_browser: Optional[str],
    js_runtime: str,
    tokens_data: Dict[str, Any],
    min_height: int,
    verbose: bool = True,
) -> Tuple[Optional[Dict[str, Any]], int]:
    """
    对单个 URL 进行完整的探测，逐个尝试所有策略，返回最佳下载计划。
    
    探测过程：
      1. 通过 router 获取该平台的适配器
      2. 获取该平台的探测策略列表
      3. 逐个策略调用 yt-dlp 获取视频格式信息
      4. 从每个成功策略中选出最佳格式，再在所有策略间选出全局最佳
    
    参数：
        ytdlp_cmd: yt-dlp 命令
        url: 目标视频 URL
        cookies_browser: 浏览器名称（None 表示无浏览器）
        js_runtime: JavaScript 运行时名称
        tokens_data: 当前生效的 Token 数据
        min_height: 最低分辨率要求（严格执行，低于此值不生成计划）
        verbose: 是否打印探测过程信息
    返回：
        (最佳下载计划字典, 所有策略中能看到的最高分辨率)
        如果没有找到满足要求的格式，返回 (None, 最高分辨率)
    """
    platform = classify_url(url)
    adapter = get_adapter(platform)

    strategies = adapter.build_probe_strategies(cookies_browser, tokens_data)

    local_best: Optional[Dict[str, Any]] = None
    best_seen_height = 0           # 记录所有策略中能看到的最高分辨率（不考虑阈值）
    cookie_encoding_warned = False  # 避免重复打印 cookie 编码警告

    for idx, st in enumerate(strategies, start=1):
        client = st.get("client")
        cookies = st.get("cookies")

        cmd = adapter.build_probe_cmd(
            ytdlp_cmd=ytdlp_cmd,
            url=url,
            strategy=st,
            js_runtime=js_runtime,
            tokens_data=tokens_data,
        )
        info, err = fetch_info_for_strategy(cmd)

        # 特殊处理：Chrome 等浏览器的 cookie 可能包含非 ASCII 字符，
        # yt-dlp 按 latin-1 编码时会报错。遇到这种情况，自动改用无 cookies 重试。
        if not info and cookies and "UnicodeEncodeError" in err and "latin-1" in err:
            if verbose and not cookie_encoding_warned:
                print("[Info] 检测到浏览器 cookie 编码错误（非 ASCII 字符），改用 cookies=none 重试此策略")
                cookie_encoding_warned = True
            fallback_strategy = dict(st)
            fallback_strategy["cookies"] = None
            fallback_cmd = adapter.build_probe_cmd(
                ytdlp_cmd=ytdlp_cmd,
                url=url,
                strategy=fallback_strategy,
                js_runtime=js_runtime,
                tokens_data=tokens_data,
            )
            info, err = fetch_info_for_strategy(fallback_cmd)
            if info:
                cookies = None  # 记录实际未使用浏览器 cookie，避免下载阶段再次出错

        client_label = "auto" if client is None else str(client)
        label = f"client={client_label} cookies={cookies or 'none'}"

        if not info:
            if verbose:
                print(f"[Probe {idx}/{len(strategies)}] {label} -> 失败: {err}")
            continue

        # 不考虑阈值，记录此策略能看到的最高分辨率（用于诊断）
        candidate_any = choose_candidate_from_info(info, 0)
        if candidate_any:
            best_seen_height = max(best_seen_height, to_int(candidate_any.get("height")))

        # 按照最低分辨率阈值筛选
        candidate = choose_candidate_from_info(info, min_height)
        if not candidate:
            if candidate_any:
                line = (
                    f"[Probe {idx}/{len(strategies)}] {label} -> "
                    f"最高只有 {to_int(candidate_any.get('height'))}p，"
                    f"低于要求 {min_height}p，跳过"
                )
            else:
                line = f"[Probe {idx}/{len(strategies)}] {label} -> 没有可用格式"
            if verbose:
                print(line)
            continue

        # 构建完整的下载计划字典
        plan = {
            "url": url,
            "id": str(info.get("id") or youtube_video_id_from_url(url) or ""),
            "title": str(info.get("title") or ""),
            "mode": candidate["mode"],
            "format_expr": candidate["format_expr"],
            "video_id": candidate["video_id"],
            "audio_id": candidate["audio_id"],
            "height": candidate["height"],
            "width": candidate["width"],
            "fps": candidate["fps"],
            "yt_client": client,
            "cookies_browser": cookies,
            "token_client": token_runtime_summary(tokens_data)["token_client"],
            "cached_at": now_ts(),
            "last_verified_at": now_ts(),
            "status": "usable",
            "last_error": "",
            "video": candidate["video"],
            "audio": candidate["audio"],
        }

        if verbose:
            print(f"[Probe {idx}/{len(strategies)}] {label} -> {describe_candidate(plan)}")

        # 在所有策略中保留质量最高的计划
        if local_best is None or candidate_rank(plan) > candidate_rank(local_best):
            local_best = plan

    return local_best, best_seen_height


# ===========================================================================
# 跳过判断
# ===========================================================================

def should_skip_existing_plan(
    plan_cache: Dict[str, Any],
    failed_jobs: Dict[str, Any],
    url: str,
    refresh: bool,
    only_missing: bool,
    min_height: int,
    ttl_seconds: int,
) -> Tuple[bool, str]:
    """
    判断是否可以跳过对该 URL 的重新探测。

    跳过条件（满足任一）：
      - --refresh 参数：强制重探，永不跳过
      - 本地没有该 URL 的计划：不能跳过，必须探测
      - failed_jobs 中存在 probe 阶段失败记录：跳过（避免反复重试必失败的链接）
      - --only-missing 参数：只要有任意计划（不管是否过期）就跳过
      - 计划可用（状态正常 + 分辨率达标 + 未过期）：跳过

    返回：
        (True, 原因描述) 表示可以跳过，(False, "") 表示需要重新探测
    """
    if refresh:
        return False, ""  # --refresh 强制重探

    cache_key = cache_key_for_url(url)

    # 检查是否有 probe 失败记录（之前探测就失败的，不重复探测）
    failed = failed_jobs.get(cache_key)
    if isinstance(failed, dict) and failed.get("stage") == "probe":
        return True, f"之前探测失败（{failed.get('reason', '')[:60]}），跳过"

    existing = plan_cache.get(cache_key)

    if not isinstance(existing, dict):
        return False, ""  # 没有计划，必须探测

    if only_missing:
        return True, "已有计划（--only-missing 模式）"

    # 综合判断：状态 + 分辨率 + 时效性
    if plan_is_usable(existing, min_height=min_height, ttl_seconds=ttl_seconds):
        return True, "本地已有可用且未过期的计划"
    return False, ""


def save_plan(plan_cache: Dict[str, Any], plan: Dict[str, Any]) -> None:
    """
    将探测到的下载计划保存到缓存。
    同时更新「最后验证时间」，重置状态为可用。
    """
    key = cache_key_for_url(str(plan["url"]))
    plan_cache[key] = touch_plan_verified(plan)
    save_plan_cache(plan_cache)


# ===========================================================================
# 命令行参数解析
# ===========================================================================

def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(
            "探测视频最佳下载格式并保存计划到 state/plan_cache.json。\n"
            "默认要求 4K (2160p) 分辨率，低于此分辨率的视频会跳过。\n"
            "可用 --min-height 修改分辨率要求。"
        )
    )
    ap.add_argument(
        "--url",
        help="只探测这一个 URL（不使用 urls.txt）"
    )
    ap.add_argument(
        "--min-height",
        type=int,
        default=MIN_HEIGHT_DEFAULT,
        help=f"最低分辨率要求（像素高度，默认 {MIN_HEIGHT_DEFAULT}，即 4K）。"
             f"设为 1080 则接受 1080p 及以上。"
    )
    ap.add_argument(
        "--refresh",
        action="store_true",
        help="强制重新探测所有 URL，忽略已有的本地计划"
    )
    ap.add_argument(
        "--only-missing",
        action="store_true",
        help="只探测本地没有计划的 URL，跳过已有计划的（无论是否过期）"
    )
    ap.add_argument(
        "--plan-ttl-seconds",
        type=int,
        default=PLAN_TTL_SECONDS_DEFAULT,
        help=f"计划有效期（秒，默认 {PLAN_TTL_SECONDS_DEFAULT} = 24 小时）。"
             f"超过此时间的计划会被重新探测。"
    )
    return ap


def select_urls(args_url: Optional[str]) -> List[str]:
    """根据命令行参数选择要处理的 URL 列表。"""
    if args_url:
        return [args_url]
    return read_urls(PATHS["urls_file"])


# ===========================================================================
# 主函数
# ===========================================================================

def main() -> None:
    ap = build_arg_parser()
    args = ap.parse_args()

    # 确保所有状态文件和目录存在
    ensure_standard_state_files(PATHS, need_downloads_dir=False)

    print("=== probe_best_plan ===")
    print(f"项目根目录: {PROJECT_ROOT}")
    print(f"计划缓存文件: {PATHS['plan_cache_file']}")
    print(f"计划有效期: {args.plan_ttl_seconds} 秒")
    print(f"最低分辨率要求: {args.min_height}p（低于此分辨率的视频将被跳过）")

    urls = select_urls(args.url)
    if not urls:
        print("[Info] urls.txt 中没有可处理的 URL，请先填写链接")
        return

    ytdlp_cmd, env_state, tokens_data, js_runtime, cookies_browser = load_runtime_context()
    if not ytdlp_cmd:
        print("[Error] 未找到可用的 yt-dlp，请先运行 python3 scripts/refresh_context.py 安装")
        log_event(PATHS["run_log_file"], "probe_best_plan", "error", "missing_ytdlp")
        return

    summary = token_runtime_summary(tokens_data)

    print(f"[Info] yt-dlp 命令: {get_ytdlp_cmd_display(ytdlp_cmd)}")
    print(f"[Info] yt-dlp 版本: {get_ytdlp_version(ytdlp_cmd)}")
    print(f"[Info] JS 运行时: {js_runtime}")
    print(f"[Info] 浏览器 cookies: {cookies_browser or '未检测到浏览器'}")
    print(f"[Info] visitor_data 已设置: {'是' if summary['visitor_data_set'] else '否'}")
    print(f"[Info] po_token 已设置: {'是' if summary['po_token_set'] else '否'}")
    print(f"[Info] token_client: {summary['token_client']}")
    print(f"[Info] token 来源: {summary['token_source']}")

    plan_cache = load_plan_cache()
    failed_jobs = load_json_dict(PATHS["failed_jobs_file"], {})
    failures: List[str] = []

    for idx, url in enumerate(urls, start=1):
        cache_key = cache_key_for_url(url)
        print(f"\n[{idx}/{len(urls)}] {url}")

        # 检查是否可以跳过
        skip, skip_reason = should_skip_existing_plan(
            plan_cache=plan_cache,
            failed_jobs=failed_jobs,
            url=url,
            refresh=args.refresh,
            only_missing=args.only_missing,
            min_height=args.min_height,
            ttl_seconds=args.plan_ttl_seconds,
        )
        if skip:
            print(f"[Info] 跳过: {skip_reason}")
            log_event(PATHS["run_log_file"], "probe_best_plan", "info", "skip_existing_plan",
                      cache_key=cache_key, url=url, reason=skip_reason)
            continue

        log_event(
            PATHS["run_log_file"], "probe_best_plan", "info", "probe_start",
            cache_key=cache_key, url=url,
            token_source=summary["token_source"],
            token_client=summary["token_client"],
            visitor_data_set=summary["visitor_data_set"],
            po_token_set=summary["po_token_set"],
        )

        # 获取该平台的有效分辨率阈值
        # 注意：抖音/TikTok/小红书等平台会自动降低阈值（因为这些平台本身不提供 4K）
        platform = classify_url(url)
        adapter = get_adapter(platform)
        effective_min_height = adapter.suggested_min_height(url, args.min_height)
        if effective_min_height != args.min_height:
            print(f"[Info] 平台={platform}，分辨率阈值自动降级: {args.min_height}p → {effective_min_height}p")

        # 执行探测
        plan, best_seen_height = run_probe_round(
            ytdlp_cmd=ytdlp_cmd,
            url=url,
            cookies_browser=cookies_browser,
            js_runtime=js_runtime,
            tokens_data=tokens_data,
            min_height=effective_min_height,
            verbose=True,
        )

        if not plan:
            # 探测失败：没有找到满足要求的格式
            diag = adapter.diag_message(best_seen_height)
            if diag:
                for line in diag.splitlines():
                    print(f"[Diag] {line}" if not line.startswith("[Diag]") else line)

            # 如果本地有旧计划，将其标记为疑似过期
            existing = plan_cache.get(cache_key)
            if isinstance(existing, dict):
                plan_cache[cache_key] = mark_plan_status(
                    existing,
                    PLAN_STATUS_SUSPECTED_EXPIRED,
                    reason=f"probe failed, best_seen_height={best_seen_height}",
                )
                save_plan_cache(plan_cache)

            reason = f"probe failed, best_seen_height={best_seen_height}"
            update_failed_jobs(
                cache_key=cache_key, url=url, stage="probe",
                reason=reason, used_plan="", has_partial=False,
            )
            log_event(PATHS["run_log_file"], "probe_best_plan", "error", "probe_failed",
                      cache_key=cache_key, url=url, reason=reason)
            failures.append(url)
            continue

        # 探测成功：保存计划
        save_plan(plan_cache, plan)
        print(f"[Info] 计划已保存: {describe_candidate(plan)}")
        log_event(
            PATHS["run_log_file"], "probe_best_plan", "info", "plan_saved",
            cache_key=cache_key, url=url,
            format_expr=str(plan.get("format_expr") or ""),
            height=to_int(plan.get("height")),
            client=("auto" if plan.get("yt_client") is None else str(plan.get("yt_client"))),
            token_source=summary["token_source"],
        )

    print("\n=== 探测完成 ===")
    print(f"计划缓存文件: {PATHS['plan_cache_file']}")

    if failures:
        print(f"[结果] 失败: {len(failures)} 个")
        for u in failures:
            print(f"  {u}")
    else:
        print("[结果] 所有 URL 探测成功")


if __name__ == "__main__":
    main()