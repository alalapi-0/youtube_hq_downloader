from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Tuple

from .utils import clean_text, extract_video_id, watch_url


def ytdlp_available() -> bool:
    return bool(shutil.which("yt-dlp"))


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


def _run_ytdlp_json(args: List[str], *, timeout_seconds: int) -> Tuple[Dict[str, Any] | None, str]:
    cmd = ["yt-dlp", "--dump-single-json", "--skip-download", "--no-warnings", *args]
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(10, int(timeout_seconds)),
            check=False,
        )
    except FileNotFoundError:
        return None, "yt-dlp_not_found"
    except subprocess.TimeoutExpired:
        return None, "yt-dlp_timeout"
    if proc.returncode != 0:
        detail = clean_text(proc.stderr or proc.stdout).strip().splitlines()
        return None, "; ".join(detail[-3:])[:500] or f"yt-dlp_exit_{proc.returncode}"
    try:
        data = json.loads(proc.stdout)
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
) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, int]]:
    enriched: List[Dict[str, Any]] = []
    warnings: List[str] = []
    stats = {"total": 0, "ok": 0, "failed": 0}
    timeout = int(youtube_cfg.get("metadata_timeout_seconds") or 90)
    cookie_args = _yt_dlp_cookie_args(youtube_cfg)
    for record in rows:
        stats["total"] += 1
        row = dict(record)
        url = str(row.get("video_url") or row.get("canonical_url") or "").strip()
        data, status = _run_ytdlp_json([*cookie_args, url], timeout_seconds=timeout)
        if not data:
            row["metadata_status"] = status
            warnings.append(f"视频元数据读取失败：{url} ({status})")
            stats["failed"] += 1
            enriched.append(row)
            continue
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
        stats["ok"] += 1
        enriched.append(row)
    return enriched, warnings, stats
