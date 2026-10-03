#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from typing import Any, Dict, List, Optional, Tuple

from common import (
    PLAN_STATUS_SUSPECTED_EXPIRED,
    build_youtube_extractor_args,
    cache_key_for_url,
    clip_err,
    default_tokens_data,
    detect_cookies_browser,
    detect_js_runtime,
    effective_tokens_data,
    ensure_standard_state_files,
    ensure_ytdlp_installed,
    get_ytdlp_cmd_display,
    get_ytdlp_version,
    is_youtube_url,
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

PATHS = project_paths(__file__)
PROJECT_ROOT = PATHS["project_root"]

MIN_HEIGHT_DEFAULT = 2160
PLAN_TTL_SECONDS_DEFAULT = 86400
USE_IPV4 = True
YOUTUBE_CLIENTS: List[Optional[str]] = [None, "web", "mweb", "ios", "tv"]


def load_plan_cache() -> Dict[str, Any]:
    return load_json_dict(PATHS["plan_cache_file"], {})


def save_plan_cache(data: Dict[str, Any]) -> None:
    save_json(PATHS["plan_cache_file"], data)


def load_tokens_file() -> Dict[str, Any]:
    return load_json_dict(PATHS["tokens_file"], default_tokens_data())


def load_env_state() -> Dict[str, Any]:
    return load_json_dict(PATHS["env_state_file"], {})


def update_failed_jobs(
    cache_key: str,
    url: str,
    stage: str,
    reason: str,
    used_plan: str = "",
    has_partial: bool = False,
) -> None:
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


def load_runtime_context() -> Tuple[Optional[List[str]], Dict[str, Any], Dict[str, Any], str, Optional[str]]:
    env_state = load_env_state()
    file_tokens = load_tokens_file()
    tokens = effective_tokens_data(file_tokens)

    ytdlp_cmd = None
    y = env_state.get("ytdlp") if isinstance(env_state, dict) else None
    if isinstance(y, dict):
        cmd = y.get("cmd")
        if isinstance(cmd, list) and cmd:
            ytdlp_cmd = cmd

    if not ytdlp_cmd:
        ytdlp_cmd = ensure_ytdlp_installed(auto_install=False)

    js_runtime = ""
    js = env_state.get("js_runtime") if isinstance(env_state, dict) else None
    if isinstance(js, dict):
        js_runtime = str(js.get("name") or "").strip()

    if not js_runtime:
        js_runtime = detect_js_runtime()

    cookies_browser = None
    browser = env_state.get("browser") if isinstance(env_state, dict) else None
    if isinstance(browser, dict):
        cb = str(browser.get("cookies_browser") or "").strip()
        cookies_browser = cb or None

    if not cookies_browser:
        cookies_browser = detect_cookies_browser()

    return ytdlp_cmd, env_state, tokens, js_runtime, cookies_browser


def build_youtube_probe_strategies(cookies_browser: Optional[str], tokens_data: Dict[str, Any]) -> List[Dict[str, Optional[str]]]:
    strategies: List[Dict[str, Optional[str]]] = []

    summary = token_runtime_summary(tokens_data)
    po_token = summary["po_token_set"]
    token_client = summary["token_client"]

    if po_token and token_client in YOUTUBE_CLIENTS:
        ordered = [token_client] + [c for c in YOUTUBE_CLIENTS if c != token_client]
    else:
        ordered = list(YOUTUBE_CLIENTS)

    for client in ordered:
        strategies.append({"client": client, "cookies": None})
        if cookies_browser:
            strategies.append({"client": client, "cookies": cookies_browser})

    return strategies


def build_generic_probe_strategies(cookies_browser: Optional[str]) -> List[Dict[str, Optional[str]]]:
    strategies = [{"client": None, "cookies": None}]
    if cookies_browser:
        strategies.append({"client": None, "cookies": cookies_browser})
    return strategies


def build_probe_cmd(
    ytdlp_cmd: List[str],
    url: str,
    cookies_browser: Optional[str],
    js_runtime: str,
    yt_client: Optional[str],
    tokens_data: Dict[str, Any],
) -> List[str]:
    cmd: List[str] = [*ytdlp_cmd, "--ignore-config"]

    cmd += [
        "--skip-download",
        "--dump-single-json",
        "--no-warnings",
        "--no-playlist",
    ]

    if USE_IPV4:
        cmd += ["--force-ipv4"]

    if cookies_browser:
        cmd += ["--cookies-from-browser", cookies_browser]

    if js_runtime and js_runtime != "auto":
        cmd += ["--js-runtimes", js_runtime]

    ex_args = build_youtube_extractor_args(yt_client, tokens_data=tokens_data, extra_args=None)
    if ex_args and is_youtube_url(url):
        cmd += ["--extractor-args", ex_args]

    cmd += [url]
    return cmd


def fetch_info_for_strategy(
    ytdlp_cmd: List[str],
    url: str,
    cookies_browser: Optional[str],
    js_runtime: str,
    yt_client: Optional[str],
    tokens_data: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], str]:
    cmd = build_probe_cmd(
        ytdlp_cmd=ytdlp_cmd,
        url=url,
        cookies_browser=cookies_browser,
        js_runtime=js_runtime,
        yt_client=yt_client,
        tokens_data=tokens_data,
    )

    rc, stdout, stderr = run_capture_raw(cmd)
    if rc != 0:
        return None, clip_err(stderr or stdout)

    obj = safe_json_load(stdout)
    if isinstance(obj, dict):
        return obj, ""

    return None, clip_err(stderr or stdout or "json parse failed")


def is_valid_media_format(fmt: Dict[str, Any]) -> bool:
    format_note = str(fmt.get("format_note") or "").lower()
    ext = str(fmt.get("ext") or "").lower()
    if "storyboard" in format_note:
        return False
    if ext in {"mhtml"}:
        return False
    return True


def is_video_only_format(fmt: Dict[str, Any]) -> bool:
    return str(fmt.get("vcodec") or "none") != "none" and str(fmt.get("acodec") or "none") == "none"


def is_audio_only_format(fmt: Dict[str, Any]) -> bool:
    return str(fmt.get("vcodec") or "none") == "none" and str(fmt.get("acodec") or "none") != "none"


def is_combined_av_format(fmt: Dict[str, Any]) -> bool:
    return str(fmt.get("vcodec") or "none") != "none" and str(fmt.get("acodec") or "none") != "none"


def hdr_rank(fmt: Dict[str, Any]) -> int:
    dr = str(fmt.get("dynamic_range") or "").upper()
    if any(x in dr for x in ["DV", "DOLBY", "HDR", "PQ", "HLG"]):
        return 2
    if dr == "SDR":
        return 1
    return 0


def video_codec_rank(vcodec: str) -> int:
    s = (vcodec or "").lower()
    if "av01" in s:
        return 6
    if "vp9.2" in s:
        return 5
    if "vp9" in s:
        return 4
    if "hev1" in s or "hvc1" in s or "hevc" in s:
        return 3
    if "avc1" in s or "h264" in s:
        return 2
    if s and s != "none":
        return 1
    return 0


def audio_codec_rank(acodec: str) -> int:
    s = (acodec or "").lower()
    if "opus" in s:
        return 5
    if "aac" in s or "mp4a" in s:
        return 4
    if "vorbis" in s:
        return 3
    if s and s != "none":
        return 1
    return 0


def video_rank_tuple(fmt: Dict[str, Any]) -> Tuple:
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
    return (
        to_int(fmt.get("audio_channels")),
        to_int(fmt.get("asr")),
        to_float(fmt.get("abr")) or to_float(fmt.get("tbr")),
        to_int(fmt.get("filesize")) or to_int(fmt.get("filesize_approx")),
        audio_codec_rank(str(fmt.get("acodec") or "")),
    )


def choose_candidate_from_info(info: Dict[str, Any], min_height: int) -> Optional[Dict[str, Any]]:
    formats = info.get("formats") or []
    if not isinstance(formats, list) or not formats:
        return None

    valid_formats = [f for f in formats if isinstance(f, dict) and is_valid_media_format(f)]

    video_only = [f for f in valid_formats if is_video_only_format(f) and to_int(f.get("height")) >= min_height]
    audio_only = [f for f in valid_formats if is_audio_only_format(f)]
    combined_av = [f for f in valid_formats if is_combined_av_format(f) and to_int(f.get("height")) >= min_height]

    best_video = max(video_only, key=video_rank_tuple) if video_only else None
    best_audio = max(audio_only, key=audio_rank_tuple) if audio_only else None
    best_combined = max(combined_av, key=video_rank_tuple) if combined_av else None

    if best_video and best_audio:
        video_id = str(best_video.get("format_id"))
        audio_id = str(best_audio.get("format_id"))
        return {
            "mode": "adaptive",
            "format_expr": f"{video_id}+{audio_id}",
            "video": best_video,
            "audio": best_audio,
            "height": to_int(best_video.get("height")),
            "width": to_int(best_video.get("width")),
            "fps": to_float(best_video.get("fps")),
            "video_id": video_id,
            "audio_id": audio_id,
        }

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

    return None


def candidate_rank(plan: Dict[str, Any]) -> Tuple:
    v = plan["video"]
    a = plan.get("audio")
    mode_rank = 1 if plan.get("mode") == "adaptive" else 0
    vr = video_rank_tuple(v)
    ar = audio_rank_tuple(a) if isinstance(a, dict) else (0, 0, 0, 0, 0)
    return vr + (mode_rank,) + ar


def describe_candidate(plan: Dict[str, Any]) -> str:
    h = to_int(plan.get("height"))
    fps = to_float(plan.get("fps"))
    mode = str(plan.get("mode"))
    vid = str(plan.get("video_id"))
    aid = str(plan.get("audio_id") or "-")
    client = "auto" if plan.get("yt_client") is None else str(plan.get("yt_client"))
    return f"{h}p {fps:g}fps | mode={mode} | client={client} | v={vid} | a={aid}"


def run_probe_round(
    ytdlp_cmd: List[str],
    url: str,
    cookies_browser: Optional[str],
    js_runtime: str,
    tokens_data: Dict[str, Any],
    min_height: int,
    verbose: bool = True,
) -> Tuple[Optional[Dict[str, Any]], int]:
    strategies = (
        build_youtube_probe_strategies(cookies_browser, tokens_data)
        if is_youtube_url(url)
        else build_generic_probe_strategies(cookies_browser)
    )

    local_best: Optional[Dict[str, Any]] = None
    best_seen_height = 0

    cookie_encoding_warned = False

    for idx, st in enumerate(strategies, start=1):
        client = st.get("client")
        cookies = st.get("cookies")

        info, err = fetch_info_for_strategy(
            ytdlp_cmd=ytdlp_cmd,
            url=url,
            cookies_browser=cookies,
            js_runtime=js_runtime,
            yt_client=client,
            tokens_data=tokens_data,
        )

        # Chrome 等浏览器的 cookie 可能含非 ASCII，yt-dlp/requests 按 latin-1 编码会报错，自动用 cookies=none 重试
        if not info and cookies and "UnicodeEncodeError" in err and "latin-1" in err:
            if verbose and not cookie_encoding_warned:
                print("[Info] 检测到从浏览器读取 cookie 时编码错误，将改用 cookies=none 重试该策略")
                cookie_encoding_warned = True
            info, err = fetch_info_for_strategy(
                ytdlp_cmd=ytdlp_cmd,
                url=url,
                cookies_browser=None,
                js_runtime=js_runtime,
                yt_client=client,
                tokens_data=tokens_data,
            )
            if info:
                cookies = None  # 实际未使用浏览器 cookie，避免下载阶段再次报错

        client_label = "auto" if client is None else str(client)
        label = f"client={client_label} cookies={cookies or 'none'}"

        if not info:
            if verbose:
                print(f"[Probe {idx}/{len(strategies)}] {label} -> failed: {err}")
            continue

        candidate_any = choose_candidate_from_info(info, 0)
        if candidate_any:
            best_seen_height = max(best_seen_height, to_int(candidate_any.get("height")))

        candidate = choose_candidate_from_info(info, min_height)
        if not candidate:
            if candidate_any:
                line = (
                    f"[Probe {idx}/{len(strategies)}] {label} -> best seen "
                    f"{to_int(candidate_any.get('height'))}p but below threshold {min_height}p"
                )
            else:
                line = f"[Probe {idx}/{len(strategies)}] {label} -> no usable formats"
            if verbose:
                print(line)
            continue

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

        if local_best is None or candidate_rank(plan) > candidate_rank(local_best):
            local_best = plan

    return local_best, best_seen_height


def should_skip_existing_plan(
    plan_cache: Dict[str, Any],
    url: str,
    refresh: bool,
    only_missing: bool,
    min_height: int,
    ttl_seconds: int,
) -> bool:
    if refresh:
        return False

    cache_key = cache_key_for_url(url)
    existing = plan_cache.get(cache_key)

    if not isinstance(existing, dict):
        return False

    if only_missing:
        return True

    return plan_is_usable(existing, min_height=min_height, ttl_seconds=ttl_seconds)


def save_plan(plan_cache: Dict[str, Any], plan: Dict[str, Any]) -> None:
    key = cache_key_for_url(str(plan["url"]))
    plan_cache[key] = touch_plan_verified(plan)
    save_plan_cache(plan_cache)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Probe best downloadable plan and save it to local plan_cache.json"
    )
    ap.add_argument("--url", help="Probe only this single URL")
    ap.add_argument("--min-height", type=int, default=MIN_HEIGHT_DEFAULT, help="Minimum acceptable height")
    ap.add_argument("--refresh", action="store_true", help="Force re-probe even if local plan exists")
    ap.add_argument("--only-missing", action="store_true", help="Only probe URLs that do not have a local usable plan")
    ap.add_argument("--plan-ttl-seconds", type=int, default=PLAN_TTL_SECONDS_DEFAULT, help="Skip re-probe when usable plan is still fresh")
    return ap


def select_urls(args_url: Optional[str]) -> List[str]:
    if args_url:
        return [args_url]
    return read_urls(PATHS["urls_file"])


def main() -> None:
    ap = build_arg_parser()
    args = ap.parse_args()

    ensure_standard_state_files(PATHS, need_downloads_dir=False)

    print("=== probe_best_plan ===")
    print(f"project root: {PROJECT_ROOT}")
    print(f"plan cache: {PATHS['plan_cache_file']}")
    print(f"plan ttl seconds: {args.plan_ttl_seconds}")

    urls = select_urls(args.url)
    if not urls:
        print("[Info] 没有可处理的 URL")
        return

    ytdlp_cmd, env_state, tokens_data, js_runtime, cookies_browser = load_runtime_context()
    if not ytdlp_cmd:
        print("[Error] 未找到可用 yt-dlp")
        log_event(PATHS["run_log_file"], "probe_best_plan", "error", "missing_ytdlp")
        return

    summary = token_runtime_summary(tokens_data)

    print(f"[Info] yt-dlp cmd: {get_ytdlp_cmd_display(ytdlp_cmd)}")
    print(f"[Info] yt-dlp version: {get_ytdlp_version(ytdlp_cmd)}")
    print(f"[Info] js runtime: {js_runtime}")
    print(f"[Info] cookies browser: {cookies_browser or 'none'}")
    print(f"[Info] visitor_data set: {'yes' if summary['visitor_data_set'] else 'no'}")
    print(f"[Info] po_token set: {'yes' if summary['po_token_set'] else 'no'}")
    print(f"[Info] token_client: {summary['token_client']}")
    print(f"[Info] token_source: {summary['token_source']}")

    plan_cache = load_plan_cache()
    failures: List[str] = []

    for idx, url in enumerate(urls, start=1):
        cache_key = cache_key_for_url(url)
        print(f"\n[{idx}/{len(urls)}] {url}")

        if should_skip_existing_plan(
            plan_cache=plan_cache,
            url=url,
            refresh=args.refresh,
            only_missing=args.only_missing,
            min_height=args.min_height,
            ttl_seconds=args.plan_ttl_seconds,
        ):
            print("[Info] 本地已存在可用且新鲜的 plan，跳过")
            log_event(PATHS["run_log_file"], "probe_best_plan", "info", "skip_existing_plan", cache_key=cache_key, url=url)
            continue

        log_event(
            PATHS["run_log_file"],
            "probe_best_plan",
            "info",
            "probe_start",
            cache_key=cache_key,
            url=url,
            token_source=summary["token_source"],
            token_client=summary["token_client"],
            visitor_data_set=summary["visitor_data_set"],
            po_token_set=summary["po_token_set"],
        )

        plan, best_seen_height = run_probe_round(
            ytdlp_cmd=ytdlp_cmd,
            url=url,
            cookies_browser=cookies_browser,
            js_runtime=js_runtime,
            tokens_data=tokens_data,
            min_height=args.min_height,
            verbose=True,
        )

        if not plan:
            print(f"[Diag] 本轮探测能看到的最高高度大约是: {best_seen_height}p")
            if is_youtube_url(url):
                print("[Diag] 如果浏览器里能看 4K，但这里始终只能看到 360p/1080p，通常需要补 visitor_data / po_token")

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
                cache_key=cache_key,
                url=url,
                stage="probe",
                reason=reason,
                used_plan="",
                has_partial=False,
            )
            log_event(PATHS["run_log_file"], "probe_best_plan", "error", "probe_failed", cache_key=cache_key, url=url, reason=reason)
            failures.append(url)
            continue

        save_plan(plan_cache, plan)
        print(f"[Info] 已保存 plan: {describe_candidate(plan)}")
        log_event(
            PATHS["run_log_file"],
            "probe_best_plan",
            "info",
            "plan_saved",
            cache_key=cache_key,
            url=url,
            format_expr=str(plan.get("format_expr") or ""),
            height=to_int(plan.get("height")),
            client=("auto" if plan.get("yt_client") is None else str(plan.get("yt_client"))),
            token_source=summary["token_source"],
        )

    print("\n=== Done ===")
    print(f"plan cache: {PATHS['plan_cache_file']}")

    if failures:
        print(f"[Result] Failed: {len(failures)}")
        for u in failures:
            print(u)
    else:
        print("[Result] All probe jobs finished successfully.")


if __name__ == "__main__":
    main()
