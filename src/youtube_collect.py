from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Tuple

from .utils import clean_text, extract_video_id, watch_url


def ytdlp_available() -> bool:
    try:
        import yt_dlp  # noqa: F401

        return True
    except Exception:
        return bool(shutil.which("yt-dlp"))


def _ytdlp_command_base() -> List[str]:
    try:
        import yt_dlp  # noqa: F401

        return [sys.executable, "-m", "yt_dlp"]
    except Exception:
        return ["yt-dlp"]


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _yt_dlp_cookie_args(youtube_cfg: Dict[str, Any]) -> List[str]:
    if not youtube_cfg.get("cookies_enabled", False):
        return []
    cookie_file = str(youtube_cfg.get("cookie_file") or "").strip()
    if cookie_file:
        return ["--cookies", cookie_file]
    browser = str(youtube_cfg.get("cookies_from_browser") or "").strip()
    if browser:
        return ["--cookies-from-browser", browser]
    return []


def _yt_dlp_rate_limit_args(youtube_cfg: Dict[str, Any]) -> List[str]:
    args: List[str] = []
    sleep_requests = str(youtube_cfg.get("sleep_requests_seconds") or "").strip()
    if sleep_requests:
        args.extend(["--sleep-requests", sleep_requests])
    extractor_retries = str(youtube_cfg.get("extractor_retries") or "").strip()
    if extractor_retries:
        args.extend(["--extractor-retries", extractor_retries])
    return args


def _run_ytdlp_json(args: List[str], *, timeout_seconds: int) -> Tuple[Dict[str, Any] | None, str]:
    timeout = max(10, int(timeout_seconds))
    cmd = [
        *_ytdlp_command_base(),
        "--ignore-config",
        "--dump-single-json",
        "--skip-download",
        "--no-warnings",
        "--remote-components",
        "ejs:github",
        *args,
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        stdout, stderr = proc.communicate(timeout=timeout)
    except FileNotFoundError:
        return None, "yt-dlp_not_found"
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = proc.communicate()
        return None, f"yt-dlp_timeout_{timeout}s"
    if proc.returncode != 0:
        detail = clean_text(stderr or stdout).strip().splitlines()
        return None, "; ".join(detail[-3:])[:500] or f"yt-dlp_exit_{proc.returncode}"
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return None, f"yt-dlp_invalid_json: {exc}"
    return data if isinstance(data, dict) else None, "ok"


def _date_from_upload_date(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _date_from_timestamp(value: Any) -> str:
    ts = _as_int(value)
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, timezone.utc).date().isoformat()


def _format_heights(data: Dict[str, Any]) -> List[int]:
    heights: List[int] = []
    for item in data.get("formats") or []:
        if not isinstance(item, dict):
            continue
        height = _as_int(item.get("height"))
        if height is not None:
            heights.append(height)
    return sorted(set(heights))


def _thumbnail_urls(data: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    for item in data.get("thumbnails") or []:
        if isinstance(item, dict) and item.get("url"):
            urls.append(str(item["url"]))
    if data.get("thumbnail"):
        urls.append(str(data["thumbnail"]))
    seen: set[str] = set()
    out: List[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _candidate_from_entry(entry: Dict[str, Any], *, search_url: str) -> Dict[str, Any] | None:
    video_id = str(entry.get("id") or "").strip()
    raw_url = str(entry.get("url") or entry.get("webpage_url") or "").strip()
    if not video_id:
        video_id = extract_video_id(raw_url) or ""
    if not video_id:
        return None
    return {
        "source_platform": "youtube",
        "video_id": video_id,
        "video_url": watch_url(video_id),
        "canonical_url": watch_url(video_id),
        "title": clean_text(entry.get("title") or ""),
        "channel_title": clean_text(entry.get("channel") or entry.get("uploader") or ""),
        "source_search_url": search_url,
        "query_used": search_url,
        "duration_seconds": _as_int(entry.get("duration")),
        "view_count": _as_int(entry.get("view_count")),
        "collector_status": "flat_search_result",
    }


def collect_search_page_urls(
    search_urls: Iterable[str],
    *,
    youtube_cfg: Dict[str, Any],
    max_entries_per_page: int,
) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, int]]:
    rows: List[Dict[str, Any]] = []
    warnings: List[str] = []
    stats = {"search_pages": 0, "entries_seen": 0, "video_urls": 0, "failed_pages": 0}
    timeout = int(youtube_cfg.get("metadata_timeout_seconds") or 90)
    cookie_args = _yt_dlp_cookie_args(youtube_cfg)
    rate_limit_args = _yt_dlp_rate_limit_args(youtube_cfg)
    for search_url in search_urls:
        url = clean_text(search_url).strip()
        if not url:
            continue
        stats["search_pages"] += 1
        args = [
            "--flat-playlist",
            "--playlist-end",
            str(max_entries_per_page),
            *cookie_args,
            *rate_limit_args,
            url,
        ]
        data, status = _run_ytdlp_json(args, timeout_seconds=timeout)
        if not data:
            stats["failed_pages"] += 1
            warnings.append(f"搜索页读取失败：{url} ({status})")
            continue
        for entry in data.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            stats["entries_seen"] += 1
            row = _candidate_from_entry(entry, search_url=url)
            if row:
                rows.append(row)
                stats["video_urls"] += 1
    return rows, warnings, stats


def enrich_video_metadata(
    rows: Iterable[Dict[str, Any]],
    *,
    youtube_cfg: Dict[str, Any],
    concurrency: int = 1,
) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, int]]:
    records = list(rows)
    enriched: List[Dict[str, Any]] = []
    warnings: List[str] = []
    stats = {"total": 0, "ok": 0, "failed": 0}
    timeout = int(youtube_cfg.get("metadata_timeout_seconds") or 90)
    cookie_args = _yt_dlp_cookie_args(youtube_cfg)
    rate_limit_args = _yt_dlp_rate_limit_args(youtube_cfg)
    metadata_sleep = float(youtube_cfg.get("metadata_sleep_seconds") or 0)

    def enrich_one(record: Dict[str, Any]) -> Tuple[Dict[str, Any], str, bool]:
        row = dict(record)
        url = str(row.get("video_url") or row.get("canonical_url") or "").strip()
        if metadata_sleep > 0:
            time.sleep(metadata_sleep)
        data, status = _run_ytdlp_json([*cookie_args, *rate_limit_args, url], timeout_seconds=timeout)
        if not data:
            row["metadata_status"] = status
            return row, f"视频元数据读取失败：{url} ({status})", False
        heights = _format_heights(data)
        max_height = max(heights) if heights else None
        published_at = _date_from_upload_date(data.get("upload_date")) or _date_from_timestamp(data.get("timestamp"))
        row.update(
            {
                "source_platform": "youtube",
                "video_id": str(data.get("id") or row.get("video_id") or ""),
                "video_url": watch_url(str(data.get("id") or row.get("video_id") or "")),
                "canonical_url": watch_url(str(data.get("id") or row.get("video_id") or "")),
                "title": clean_text(data.get("title") or row.get("title") or ""),
                "channel_title": clean_text(data.get("channel") or data.get("uploader") or row.get("channel_title") or ""),
                "channel_id": clean_text(data.get("channel_id") or data.get("uploader_id") or ""),
                "channel_url": clean_text(data.get("channel_url") or data.get("uploader_url") or ""),
                "description": clean_text(data.get("description") or ""),
                "duration_seconds": _as_int(data.get("duration")),
                "published_at": published_at,
                "view_count": _as_int(data.get("view_count")),
                "like_count": _as_int(data.get("like_count")),
                "comment_count": _as_int(data.get("comment_count")),
                "thumbnail_urls": _thumbnail_urls(data),
                "tags": data.get("tags") if isinstance(data.get("tags"), list) else [],
                "available_format_heights": heights,
                "max_format_height": max_height,
                "has_2160p_format": bool(max_height is not None and max_height >= 2160),
                "format_probe_status": "ok" if heights else "no_formats",
                "metadata_status": "ok",
            }
        )
        return row, "", True

    stats["total"] = len(records)
    if not records:
        return enriched, warnings, stats

    concurrency = max(1, int(concurrency or 1))
    if concurrency == 1:
        results = [enrich_one(record) for record in records]
    else:
        results: List[Tuple[Dict[str, Any], str, bool] | None] = [None] * len(records)
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            future_to_idx = {pool.submit(enrich_one, record): idx for idx, record in enumerate(records)}
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as exc:  # defensive: keep batch jobs moving on unexpected metadata bugs
                    row = dict(records[idx])
                    url = str(row.get("video_url") or row.get("canonical_url") or "").strip()
                    row["metadata_status"] = f"metadata_exception: {exc}"
                    results[idx] = (row, f"视频元数据读取失败：{url} (metadata_exception: {exc})", False)

    for result in results:
        if result is None:
            continue
        row, warning, ok = result
        if warning:
            warnings.append(warning)
        if ok:
            stats["ok"] += 1
        else:
            stats["failed"] += 1
        enriched.append(row)
    return enriched, warnings, stats
