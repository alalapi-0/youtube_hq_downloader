#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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
    build_youtube_extractor_args,
    cache_key_for_url,
    clip_err,
    default_failed_jobs,
    default_tokens_data,
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

PATHS = project_paths(__file__)
PROJECT_ROOT = PATHS["project_root"]
DOWNLOADS_DIR = PATHS["downloads_dir"]

USE_IPV4 = True
SOCKET_TIMEOUT = 60
RETRIES = 50
FRAGMENT_RETRIES = 50
RETRY_SLEEP_COUNT = 10
STALL_SECONDS = 90

CONCURRENT_FRAGMENTS = 1
SLEEP_REQUESTS_SECONDS = 1.0
HTTP_RETRY_SLEEP = "10"
FRAGMENT_RETRY_SLEEP = "5"

DOWNLOAD_ATTEMPTS_PER_PLAN = 2
RETRY_WAIT_SECONDS = 20
PLAN_TTL_SECONDS_DEFAULT = 86400

FINAL_VIDEO_EXTS = {".mkv", ".webm", ".mp4"}


def is_partial_file(path: Path) -> bool:
    name = path.name.lower()
    return (
        name.endswith(".part")
        or name.endswith(".ytdl")
        or name.endswith(".temp")
        or ".part-" in name
    )


def is_final_video_file(path: Path) -> bool:
    return (not is_partial_file(path)) and path.suffix.lower() in FINAL_VIDEO_EXTS


def get_required_height(plan: Dict[str, Any]) -> int:
    return to_int(plan.get("height"), 0)


def get_plan_fragment(plan: Dict[str, Any]) -> str:
    template = build_output_template(plan)
    parts = template.split("%(title)s", 1)
    frag = parts[1] if len(parts) == 2 else template
    frag = frag.replace(".%(ext)s", "").strip()
    return frag


def find_plan_related_files(plan: Dict[str, Any]) -> List[Path]:
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
    return [p for p in find_plan_related_files(plan) if is_final_video_file(p)]


def find_existing_partial_files(plan: Dict[str, Any]) -> List[Path]:
    return [p for p in find_plan_related_files(plan) if is_partial_file(p)]


def handle_existing_final_files(plan: Dict[str, Any]) -> Tuple[bool, Optional[Path]]:
    required_height = get_required_height(plan)
    files = find_existing_final_files(plan)

    if not files:
        return False, None

    for f in files:
        ok, msg, info = validate_downloaded_file(f, required_height)
        if ok:
            print(f"[Info] 发现已存在且达标的完整文件，直接复用: {f.name}")
            print(f"[Info] {msg}")
            log_event(
                PATHS["run_log_file"],
                "download_by_plan",
                "info",
                "reuse_existing_final",
                cache_key=cache_key_for_url(str(plan["url"])),
                path=str(f),
                height=required_height,
            )
            return True, f

    return False, None


def validate_plan_result(plan: Dict[str, Any]) -> Tuple[bool, str, Optional[Path]]:
    required_height = get_required_height(plan)
    files = find_existing_final_files(plan)

    if not files:
        partials = find_existing_partial_files(plan)
        if partials:
            return False, "当前只有未完成的断点续传文件，尚无完整成品", None
        return False, "没有找到与本次计划匹配的完整输出文件", None

    for f in files:
        ok, msg, info = validate_downloaded_file(f, required_height)
        if ok:
            return True, f"{f.name} | {msg}", f

    return False, "找到完整文件，但实际分辨率不达标", files[0]


def looks_like_retryable_download_error(text: str) -> bool:
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


def load_runtime_context() -> Tuple[Optional[List[str]], Dict[str, Any], Dict[str, Any], str]:
    env_state = load_json_dict(PATHS["env_state_file"], {})
    file_tokens = load_json_dict(PATHS["tokens_file"], default_tokens_data())
    tokens = effective_tokens_data(file_tokens)
    js_runtime = detect_js_runtime()

    ytdlp_cmd = None
    y = env_state.get("ytdlp") if isinstance(env_state, dict) else None
    if isinstance(y, dict):
        cmd = y.get("cmd")
        if isinstance(cmd, list) and cmd:
            ytdlp_cmd = cmd

    if not ytdlp_cmd:
        ytdlp_cmd = ensure_ytdlp_installed(auto_install=False)

    return ytdlp_cmd, env_state, tokens, js_runtime


def build_download_cmd(
    ytdlp_cmd: List[str],
    plan: Dict[str, Any],
    tokens_data: Dict[str, Any],
    js_runtime: str,
) -> List[str]:
    output_template = str(DOWNLOADS_DIR / build_output_template(plan))

    cmd: List[str] = [*ytdlp_cmd, "--ignore-config"]

    cmd += [
        "-c",
        "--newline",
        "--progress",
        "--socket-timeout", str(SOCKET_TIMEOUT),
        "--retries", str(RETRIES),
        "--fragment-retries", str(FRAGMENT_RETRIES),
        "-R", str(RETRY_SLEEP_COUNT),
        "--retry-sleep", f"http:{HTTP_RETRY_SLEEP}",
        "--retry-sleep", f"fragment:{FRAGMENT_RETRY_SLEEP}",
        "--sleep-requests", str(SLEEP_REQUESTS_SECONDS),
        "--concurrent-fragments", str(CONCURRENT_FRAGMENTS),
        "--paths", str(DOWNLOADS_DIR),
        "-o", output_template,
        "-f", str(plan["format_expr"]),
    ]

    if USE_IPV4:
        cmd += ["--force-ipv4"]

    cookies_browser = plan.get("cookies_browser")
    if cookies_browser:
        cmd += ["--cookies-from-browser", str(cookies_browser)]

    if js_runtime and js_runtime != "auto":
        cmd += ["--js-runtimes", js_runtime]

    yt_client = plan.get("yt_client")
    ex_args = build_youtube_extractor_args(yt_client, tokens_data=tokens_data, extra_args=None)
    if ex_args and is_youtube_url(str(plan["url"])):
        cmd += ["--extractor-args", ex_args]

    if str(plan.get("mode")) == "adaptive":
        cmd += ["--merge-output-format", "mkv"]

    cmd += [str(plan["url"])]
    return cmd


def update_failed_jobs(
    cache_key: str,
    url: str,
    stage: str,
    reason: str,
    used_plan: str,
    has_partial: bool,
) -> None:
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
    return load_json_dict(PATHS["plan_cache_file"], {})


def save_plan_cache(data: Dict[str, Any]) -> None:
    save_json(PATHS["plan_cache_file"], data)


def update_plan_cache_entry(plan_cache: Dict[str, Any], cache_key: str, plan: Dict[str, Any]) -> None:
    plan_cache[cache_key] = plan
    save_plan_cache(plan_cache)


def classify_plan_failure(plan: Dict[str, Any], output: str, has_partial: bool) -> str:
    text = (output or "").lower()

    if has_partial:
        return PLAN_STATUS_USABLE

    if "requested format is not available" in text:
        return PLAN_STATUS_SUSPECTED_EXPIRED

    if "http error 403" in text or "forbidden" in text:
        return PLAN_STATUS_SUSPECTED_EXPIRED

    return PLAN_STATUS_SUSPECTED_EXPIRED


def attempt_download_with_plan(
    ytdlp_cmd: List[str],
    plan: Dict[str, Any],
    tokens_data: Dict[str, Any],
    js_runtime: str,
) -> Tuple[int, str, bool]:
    cache_key = cache_key_for_url(str(plan["url"]))

    existing_ok, existing_file = handle_existing_final_files(plan)
    if existing_ok and existing_file:
        return 0, "", False

    partials_before = find_existing_partial_files(plan)
    if partials_before:
        print("[Info] 检测到已有断点续传文件，将优先续传")
        for p in partials_before:
            print(f"[Info] Partial: {p.name}")

    last_output = ""
    had_partial = bool(partials_before)
    plan_for_cmd = dict(plan)  # 可改为无 cookies 以规避编码错误后重试

    for attempt in range(1, DOWNLOAD_ATTEMPTS_PER_PLAN + 1):
        if attempt > 1:
            print(f"[Info] 同一计划第 {attempt}/{DOWNLOAD_ATTEMPTS_PER_PLAN} 次尝试，等待 {RETRY_WAIT_SECONDS}s")
            time.sleep(RETRY_WAIT_SECONDS)

        cmd = build_download_cmd(
            ytdlp_cmd=ytdlp_cmd,
            plan=plan_for_cmd,
            tokens_data=tokens_data,
            js_runtime=js_runtime,
        )

        print("[Info] Download command:", " ".join(cmd))
        log_event(
            PATHS["run_log_file"],
            "download_by_plan",
            "info",
            "download_start",
            cache_key=cache_key,
            url=str(plan["url"]),
            format_expr=str(plan["format_expr"]),
            attempt=attempt,
        )

        try:
            rc, out, stalled = run_stream(cmd, stall_seconds=STALL_SECONDS)
        except KeyboardInterrupt:
            print("\n[Stop] 用户中断")
            log_event(PATHS["run_log_file"], "download_by_plan", "warn", "download_interrupted", cache_key=cache_key, url=str(plan["url"]))
            return 130, last_output, had_partial

        last_output = out

        ok, result_msg, result_file = validate_plan_result(plan)
        if rc == 0 and ok:
            print(f"[Info] 下载校验通过: {result_msg}")
            log_event(
                PATHS["run_log_file"],
                "download_by_plan",
                "info",
                "download_success",
                cache_key=cache_key,
                url=str(plan["url"]),
                path=str(result_file) if result_file else "",
                format_expr=str(plan["format_expr"]),
            )
            return 0, last_output, had_partial

        partials_after = find_existing_partial_files(plan)
        if partials_after:
            had_partial = True
            print("[Warn] 当前存在未完成的断点续传文件，本次不会删除，后续可继续续传")
            for p in partials_after:
                print(f"[Warn] Keep partial: {p.name}")

        if result_msg:
            print(f"[Warn] {result_msg}")

        # 从浏览器读取 cookie 时若出现 latin-1 编码错误，改用无 cookies 重试一次
        if rc != 0 and plan_for_cmd.get("cookies_browser") and "UnicodeEncodeError" in (out or "") and "latin-1" in (out or ""):
            print("[Info] 检测到从浏览器读取 cookie 时编码错误，改用 cookies=none 重试")
            plan_for_cmd["cookies_browser"] = None
            continue

        if attempt < DOWNLOAD_ATTEMPTS_PER_PLAN and looks_like_retryable_download_error(out):
            print("[Warn] 检测到可重试错误，将继续使用同一计划重试")
            log_event(
                PATHS["run_log_file"],
                "download_by_plan",
                "warn",
                "download_retryable_error",
                cache_key=cache_key,
                url=str(plan["url"]),
                attempt=attempt,
                reason=clip_err(out, 300),
            )
            continue

        break

    partials = find_existing_partial_files(plan)
    if partials:
        had_partial = True

    reason = clip_err(last_output, 500) if last_output else "download failed"
    update_failed_jobs(
        cache_key=cache_key,
        url=str(plan["url"]),
        stage="download",
        reason=reason,
        used_plan=str(plan.get("format_expr") or ""),
        has_partial=bool(partials),
    )
    log_event(
        PATHS["run_log_file"],
        "download_by_plan",
        "error",
        "download_failed",
        cache_key=cache_key,
        url=str(plan["url"]),
        reason=reason,
        has_partial=bool(partials),
    )

    tail = "\n".join((last_output or "").splitlines()[-30:])
    if tail:
        print("\n[Last Output]")
        print(tail)

    return 1, last_output, had_partial


def select_urls(args_url: Optional[str]) -> List[str]:
    if args_url:
        return [args_url]
    return read_urls(PATHS["urls_file"])


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Download by existing local plan cache only. No probing."
    )
    ap.add_argument("--url", help="Only download this single URL using cached plan")
    ap.add_argument("--plan-ttl-seconds", type=int, default=PLAN_TTL_SECONDS_DEFAULT, help="Warn when plan is stale")
    return ap


def main() -> None:
    ap = build_arg_parser()
    args = ap.parse_args()

    ensure_standard_state_files(PATHS, need_downloads_dir=True)

    print("=== download_by_plan ===")
    print(f"project root: {PROJECT_ROOT}")
    print(f"downloads dir: {DOWNLOADS_DIR}")
    print(f"plan cache: {PATHS['plan_cache_file']}")
    print(f"plan ttl seconds: {args.plan_ttl_seconds}")

    urls = select_urls(args.url)
    if not urls:
        print("[Info] 没有可处理的 URL")
        return

    ytdlp_cmd, env_state, tokens_data, js_runtime = load_runtime_context()
    if not ytdlp_cmd:
        print("[Error] 未找到可用 yt-dlp")
        log_event(PATHS["run_log_file"], "download_by_plan", "error", "missing_ytdlp")
        return

    summary = token_runtime_summary(tokens_data)

    print(f"[Info] yt-dlp cmd: {get_ytdlp_cmd_display(ytdlp_cmd)}")
    print(f"[Info] yt-dlp version: {get_ytdlp_version(ytdlp_cmd)}")
    print(f"[Info] js runtime: {js_runtime}")
    print(f"[Info] visitor_data set: {'yes' if summary['visitor_data_set'] else 'no'}")
    print(f"[Info] po_token set: {'yes' if summary['po_token_set'] else 'no'}")
    print(f"[Info] token_client: {summary['token_client']}")
    print(f"[Info] token_source: {summary['token_source']}")

    plan_cache = load_plan_cache()
    failures: List[str] = []

    for idx, url in enumerate(urls, start=1):
        cache_key = cache_key_for_url(url)
        print(f"\n[{idx}/{len(urls)}] {url}")
        plan = plan_cache.get(cache_key)

        if not isinstance(plan, dict):
            print("[Error] 本地没有可用 plan，跳过")
            update_failed_jobs(
                cache_key=cache_key,
                url=url,
                stage="download",
                reason="missing local plan",
                used_plan="",
                has_partial=False,
            )
            log_event(PATHS["run_log_file"], "download_by_plan", "error", "missing_plan", cache_key=cache_key, url=url)
            failures.append(url)
            continue

        status = plan_status(plan)
        if status == PLAN_STATUS_INVALID:
            print("[Error] 本地 plan 已标记为 invalid，跳过")
            update_failed_jobs(
                cache_key=cache_key,
                url=url,
                stage="download",
                reason="plan marked invalid",
                used_plan=str(plan.get("format_expr") or ""),
                has_partial=False,
            )
            log_event(PATHS["run_log_file"], "download_by_plan", "error", "invalid_plan", cache_key=cache_key, url=url)
            failures.append(url)
            continue

        if not plan_is_fresh(plan, args.plan_ttl_seconds):
            print("[Warn] 本地 plan 已过期，但本轮仍尝试按缓存计划下载")
            log_event(PATHS["run_log_file"], "download_by_plan", "warn", "stale_plan_used", cache_key=cache_key, url=url)

        print(f"[Info] Using cached plan: {plan.get('format_expr', '')} | status={status}")

        log_event(
            PATHS["run_log_file"],
            "download_by_plan",
            "info",
            "download_plan_context",
            cache_key=cache_key,
            url=url,
            token_source=summary["token_source"],
            token_client=summary["token_client"],
            visitor_data_set=summary["visitor_data_set"],
            po_token_set=summary["po_token_set"],
        )

        rc, output, had_partial = attempt_download_with_plan(
            ytdlp_cmd=ytdlp_cmd,
            plan=plan,
            tokens_data=tokens_data,
            js_runtime=js_runtime,
        )

        if rc == 0:
            plan = touch_plan_verified(plan)
            update_plan_cache_entry(plan_cache, cache_key, plan)
            continue

        new_status = classify_plan_failure(plan, output, had_partial)
        plan = mark_plan_status(plan, new_status, reason=clip_err(output, 300))
        update_plan_cache_entry(plan_cache, cache_key, plan)

        failures.append(url)

    print("\n=== Done ===")
    print(f"downloads dir: {DOWNLOADS_DIR}")

    if failures:
        print(f"[Result] Failed: {len(failures)}")
        for u in failures:
            print(u)
    else:
        print("[Result] All downloads finished successfully.")


if __name__ == "__main__":
    main()
