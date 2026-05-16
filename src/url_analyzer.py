from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import isodate
from dotenv import load_dotenv

from .cookie_loader import CookieSettings, cookie_status_for_record, webpage_cookie_file, ytdlp_cookie_args
from .review_schema import default_manual_review
from .utils import PROJECT_ROOT, extract_video_id, load_yaml_mapping, read_jsonl, sniff_description, watch_url, write_jsonl
from .webpage_metadata import empty_webpage_metadata, fetch_webpage_metadata


URL_ANALYSIS_CONFIG_PATH = PROJECT_ROOT / "config" / "app.yaml"


REVIEW_COLUMNS = [
    "video_url",
    "title",
    "channel_title",
    "brand",
    "category",
    "subcategory",
    "duration_seconds",
    "max_format_height",
    "has_2160p_format",
    "query_used",
    "quality_score",
    "llm_decision",
    "llm_reason",
    "manual_status",
    "manual_passed",
    "manual_reject_reasons",
    "manual_pass_features",
    "manual_notes",
    "reviewer",
    "reviewed_at",
]


def load_url_analysis_config(path: Path | str = URL_ANALYSIS_CONFIG_PATH) -> Dict[str, Any]:
    if Path(path).name == "app.yaml":
        from .core.config import url_analysis_compat_config

        return url_analysis_compat_config()
    cfg = load_yaml_mapping(path) if Path(path).exists() else {}
    if not cfg:
        from .core.config import url_analysis_compat_config

        return url_analysis_compat_config()
    cfg.setdefault("url_analysis", {})
    cfg.setdefault("review_export", {})
    cfg.setdefault("feedback_analysis", {})
    ua = cfg["url_analysis"]
    ua.setdefault("use_youtube_api", True)
    ua.setdefault("use_ytdlp_metadata", True)
    ua.setdefault("use_webpage_metadata", True)
    ua.setdefault("use_cookie", False)
    ua.setdefault("max_description_chars", 1500)
    ua.setdefault("include_thumbnails", True)
    ua.setdefault("include_tags", True)
    ua.setdefault("include_format_info", True)
    ua.setdefault("skip_unavailable", False)
    cfg["review_export"].setdefault("output_csv", "output/review/review_sheet.csv")
    cfg["review_export"].setdefault("output_md", "output/review/review_sheet.md")
    return cfg


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("1", "true", "yes", "on", "y")


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


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_list(value: Any) -> List[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return list(value.values())
    raw = str(value).strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    return [x.strip() for x in raw.replace("|", ";").split(";") if x.strip()]


def _unique_strs(values: Iterable[Any]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for value in values:
        s = str(value or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _extract_hashtags(*texts: Any) -> List[str]:
    tags: List[str] = []
    for text in texts:
        for hit in re.findall(r"(?<!\w)#([\w-]{2,80})", str(text or ""), re.UNICODE):
            tags.append("#" + hit)
    return _unique_strs(tags)


def _youtube_api_key() -> str | None:
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    return key or None


def _duration_seconds_from_iso(value: Any) -> int | None:
    if not value:
        return None
    try:
        return int(isodate.parse_duration(str(value)).total_seconds())
    except Exception:
        return None


def _duration_iso_from_seconds(value: Any) -> str:
    sec = _as_int(value)
    if sec is None:
        return ""
    return f"PT{sec}S"


def _best_url(row: Dict[str, Any]) -> str:
    for key in ("video_url", "canonical_url", "url", "webpage_url", "original_url"):
        val = str(row.get(key) or "").strip()
        if val:
            return val
    vid = str(row.get("video_id") or "").strip()
    return watch_url(vid) if vid else ""


def _thumbnail_urls(row: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    urls.extend(_as_list(row.get("thumbnail_urls")))
    best = row.get("thumbnail_best_url")
    if best:
        urls.append(str(best))
    thumbs = row.get("thumbnails")
    if isinstance(thumbs, dict):
        for v in thumbs.values():
            if isinstance(v, dict) and v.get("url"):
                urls.append(str(v["url"]))
    elif isinstance(thumbs, list):
        for item in thumbs:
            if isinstance(item, dict) and item.get("url"):
                urls.append(str(item["url"]))
    return _unique_strs(urls)


def _description_limit(cfg: Dict[str, Any]) -> int:
    try:
        return max(0, int(((cfg.get("url_analysis") or {}).get("max_description_chars") or 1500)))
    except (TypeError, ValueError):
        return 1500


def _source_query(row: Dict[str, Any]) -> str:
    val = str(row.get("query_used") or "").strip()
    if val:
        return val
    kws = _as_list(row.get("matched_keywords"))
    return "; ".join(str(x) for x in kws if str(x).strip())


def _llm_decision(row: Dict[str, Any]) -> str:
    if row.get("llm_relevant") is True:
        return "pass"
    if row.get("llm_relevant") is False:
        return "reject"
    return str(row.get("llm_status") or "").strip()


def _analysis_template(row: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    raw_url = _best_url(row)
    vid = str(row.get("video_id") or "").strip() or str(extract_video_id(raw_url) or "")
    video_url = watch_url(vid) if vid else raw_url
    errors: List[str] = []
    if not raw_url and not vid:
        errors.append("invalid_url")
    if raw_url and not raw_url.startswith(("http://", "https://")) and not extract_video_id(raw_url):
        errors.append("invalid_url")
    if not vid:
        errors.append("missing_video_id")

    desc = str(row.get("description") or "")
    limit = _description_limit(cfg)
    if limit and len(desc) > limit:
        desc = desc[:limit]

    channel_id = str(row.get("channel_id") or "").strip()
    channel_url = str(row.get("channel_url") or "").strip()
    if not channel_url and channel_id:
        channel_url = f"https://www.youtube.com/channel/{channel_id}"

    duration_seconds = _as_int(row.get("duration_seconds"))
    if duration_seconds is None:
        duration_seconds = _duration_seconds_from_iso(row.get("duration_iso8601"))

    heights = sorted({_as_int(x) for x in _as_list(row.get("available_format_heights")) if _as_int(x) is not None})
    max_h = _as_int(row.get("max_format_height"))
    if max_h is None:
        max_h = _as_int(row.get("probe_max_height"))
    if max_h is None and heights:
        max_h = max(heights)
    has_2160 = bool(row.get("has_2160p_format") or row.get("probe_confirmed_4k") or (max_h is not None and max_h >= 2160))
    format_status = str(row.get("format_probe_status") or "").strip() or ("ok" if heights else "pending")

    manual = default_manual_review()
    nested_manual = row.get("manual_review")
    if isinstance(nested_manual, dict):
        manual.update(deepcopy(nested_manual))
    elif row.get("manual_review_status"):
        manual["status"] = str(row.get("manual_review_status") or "pending")

    tags = _as_list(row.get("tags"))
    hashtags = _unique_strs([*_extract_hashtags(row.get("title"), desc), *[str(x) for x in tags if str(x).startswith("#")]])

    rec = {
        "video_url": video_url,
        "video_id": vid,
        "title": str(row.get("title") or ""),
        "channel_title": str(row.get("channel_title") or ""),
        "channel_id": channel_id,
        "channel_url": channel_url,
        "description": desc,
        "description_snippet": str(row.get("description_snippet") or sniff_description(desc)),
        "tags": [str(x) for x in tags if str(x).strip()],
        "hashtags": hashtags,
        "category": str(row.get("category") or ""),
        "subcategory": str(row.get("subcategory") or ""),
        "brand": str(row.get("brand") or ""),
        "published_at": str(row.get("published_at") or ""),
        "duration_seconds": duration_seconds,
        "duration_iso8601": str(row.get("duration_iso8601") or _duration_iso_from_seconds(duration_seconds)),
        "view_count": _as_int(row.get("view_count")),
        "like_count": _as_int(row.get("like_count")),
        "comment_count": _as_int(row.get("comment_count")),
        "thumbnail_urls": _thumbnail_urls(row),
        "webpage_metadata": empty_webpage_metadata(status="not_requested"),
        "webpage_metadata_status": "not_requested",
        "format_info": {
            "available_format_heights": heights,
            "max_format_height": max_h,
            "has_2160p_format": has_2160,
            "format_probe_status": format_status,
        },
        "source_context": {
            "query_used": _source_query(row),
            "category": str(row.get("category") or ""),
            "subcategory": str(row.get("subcategory") or ""),
            "brand": str(row.get("brand") or ""),
            "source_stage": str(row.get("source_stage") or row.get("rejection_stage") or ""),
            "search_task_id": str(row.get("search_task_id") or ""),
        },
        "auto_filter": {
            "rule_filter_passed": row.get("hard_filter_pass"),
            "rule_reject_reasons": _as_list(row.get("rejection_codes")),
            "llm_decision": _llm_decision(row),
            "llm_reason": str(row.get("llm_notes") or row.get("llm_reason") or ""),
            "quality_score": _as_float(row.get("quality_score") if row.get("quality_score") is not None else row.get("filter_score")),
        },
        "manual_review": manual,
        "analysis": {
            "llm_feature_summary": str(row.get("llm_feature_analysis") or ""),
            "likely_positive_features": _as_list(row.get("likely_positive_features")),
            "likely_negative_features": _as_list(row.get("likely_negative_features")),
            "search_keywords_suggested": _as_list(row.get("search_keywords_suggested")),
        },
        "llm_feature_analysis": str(row.get("llm_feature_analysis") or ""),
        "next_search_suggestion": str(row.get("next_search_suggestion") or ""),
        "metadata_sources": ["input_record"],
        "cookie": {"enabled": False, "mode": "none", "status": "disabled"},
        "errors": errors,
    }
    return rec


def load_url_input(path: Path | str) -> List[Dict[str, Any]]:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".jsonl":
        return [dict(r) for r in read_jsonl(p)]
    if suffix == ".csv":
        with p.open(newline="", encoding="utf-8") as f:
            return [dict(r) for r in csv.DictReader(f)]
    rows: List[Dict[str, Any]] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            val = line.strip()
            if val:
                rows.append({"video_url": val})
    return rows


def _record_needs_api(rec: Dict[str, Any]) -> bool:
    if not rec.get("video_id"):
        return False
    required = ("title", "channel_title", "description", "duration_seconds")
    return any(rec.get(k) in (None, "", []) for k in required)


def _record_needs_ytdlp(rec: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
    if not rec.get("video_url"):
        return False
    if any(rec.get(k) in (None, "", []) for k in ("title", "channel_title", "description")):
        return True
    fmt = rec.get("format_info") if isinstance(rec.get("format_info"), dict) else {}
    include_format = _truthy((cfg.get("url_analysis") or {}).get("include_format_info"))
    status = str((fmt or {}).get("format_probe_status") or "").strip().lower()
    return bool(include_format and status in ("", "pending"))


def _record_needs_webpage(rec: Dict[str, Any]) -> bool:
    if not rec.get("video_url"):
        return False
    if any(rec.get(k) in (None, "", []) for k in ("title", "description")):
        return True
    meta = rec.get("webpage_metadata")
    return not isinstance(meta, dict)


def _chunks(seq: List[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _merge_api_item(rec: Dict[str, Any], item: Dict[str, Any]) -> None:
    sn = item.get("snippet") or {}
    st = item.get("statistics") or {}
    cd = item.get("contentDetails") or {}

    desc = sn.get("description") or ""
    duration = _duration_seconds_from_iso(cd.get("duration"))
    thumbs = sn.get("thumbnails") or {}
    thumb_urls = _thumbnail_urls({"thumbnails": thumbs})

    updates = {
        "title": sn.get("title") or "",
        "description": desc,
        "description_snippet": sniff_description(desc),
        "channel_id": sn.get("channelId") or "",
        "channel_title": sn.get("channelTitle") or "",
        "published_at": sn.get("publishedAt") or "",
        "duration_iso8601": cd.get("duration") or "",
        "duration_seconds": duration,
        "view_count": _as_int(st.get("viewCount")),
        "like_count": _as_int(st.get("likeCount")),
        "comment_count": _as_int(st.get("commentCount")),
    }
    if sn.get("tags"):
        updates["tags"] = sn.get("tags") or []
    if sn.get("categoryId") and not rec.get("youtube_category_id"):
        rec["youtube_category_id"] = str(sn.get("categoryId"))
    for key, val in updates.items():
        if rec.get(key) in (None, "", []):
            rec[key] = val
    if rec.get("channel_id") and not rec.get("channel_url"):
        rec["channel_url"] = f"https://www.youtube.com/channel/{rec['channel_id']}"
    if thumb_urls and not rec.get("thumbnail_urls"):
        rec["thumbnail_urls"] = thumb_urls
    if desc and not rec.get("hashtags"):
        rec["hashtags"] = _extract_hashtags(rec.get("title"), desc)
    rec.setdefault("metadata_sources", []).append("youtube_data_api")


def enrich_with_youtube_api(records: List[Dict[str, Any]], api_key: str) -> None:
    if not api_key:
        return
    ids = _unique_strs(r.get("video_id") for r in records if _record_needs_api(r))
    if not ids:
        return
    try:
        from googleapiclient.discovery import build

        youtube = build("youtube", "v3", developerKey=api_key)
        details: Dict[str, Dict[str, Any]] = {}
        for batch in _chunks(ids, 50):
            res = youtube.videos().list(
                part="snippet,statistics,contentDetails",
                id=",".join(batch),
                maxResults=50,
            ).execute()
            for item in res.get("items") or []:
                vid = str(item.get("id") or "")
                if vid:
                    details[vid] = item
        for rec in records:
            item = details.get(str(rec.get("video_id") or ""))
            if item:
                _merge_api_item(rec, item)
            elif _record_needs_api(rec):
                rec.setdefault("errors", []).append("youtube_api_missing_item")
    except Exception as exc:
        for rec in records:
            if _record_needs_api(rec):
                rec.setdefault("errors", []).append(f"youtube_api_failed:{type(exc).__name__}")


def _collect_format_heights(info: Dict[str, Any]) -> Tuple[List[int], int | None, bool]:
    heights: set[int] = set()
    for fmt in info.get("formats") or []:
        h = _as_int((fmt or {}).get("height"))
        if h:
            heights.add(h)
    sorted_heights = sorted(heights)
    max_h = max(sorted_heights) if sorted_heights else None
    has_2160 = bool(max_h is not None and max_h >= 2160) or "2160p" in str(info.get("format") or "")
    return sorted_heights, max_h, has_2160


def _merge_ytdlp_info(rec: Dict[str, Any], info: Dict[str, Any]) -> None:
    desc = str(info.get("description") or "")
    updates = {
        "title": info.get("title") or "",
        "description": desc,
        "description_snippet": sniff_description(desc),
        "channel_title": info.get("channel") or info.get("uploader") or "",
        "channel_id": info.get("channel_id") or "",
        "channel_url": info.get("channel_url") or info.get("uploader_url") or "",
        "published_at": info.get("release_timestamp") or info.get("timestamp") or "",
        "duration_seconds": _as_int(info.get("duration")),
        "view_count": _as_int(info.get("view_count")),
        "like_count": _as_int(info.get("like_count")),
        "comment_count": _as_int(info.get("comment_count")),
        "tags": info.get("tags") or [],
    }
    timestamp = _as_int(updates["published_at"])
    if timestamp:
        updates["published_at"] = datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(microsecond=0).isoformat()
    if not updates["channel_url"] and updates["channel_id"]:
        updates["channel_url"] = f"https://www.youtube.com/channel/{updates['channel_id']}"
    for key, val in updates.items():
        if rec.get(key) in (None, "", []):
            rec[key] = val
    cats = info.get("categories") or []
    if cats and not rec.get("category"):
        rec["category"] = str(cats[0])
        rec["source_context"]["category"] = str(cats[0])
    thumb_urls = _thumbnail_urls({"thumbnails": info.get("thumbnails") or []})
    if thumb_urls and not rec.get("thumbnail_urls"):
        rec["thumbnail_urls"] = thumb_urls

    heights, max_h, has_2160 = _collect_format_heights(info)
    fmt = rec.setdefault("format_info", {})
    if heights:
        fmt["available_format_heights"] = heights
    if max_h is not None:
        fmt["max_format_height"] = max_h
    fmt["has_2160p_format"] = bool(fmt.get("has_2160p_format") or has_2160)
    fmt["format_probe_status"] = "ok"
    rec["hashtags"] = _unique_strs([*(rec.get("hashtags") or []), *_extract_hashtags(rec.get("title"), rec.get("description"))])
    rec.setdefault("metadata_sources", []).append("yt_dlp_metadata")


def enrich_with_ytdlp(records: List[Dict[str, Any]], cfg: Dict[str, Any], cookie_settings: CookieSettings) -> None:
    if os.environ.get("SKIP_FORMAT_PROBE", "").strip() or os.environ.get("URL_ANALYSIS_OFFLINE", "").strip():
        for rec in records:
            if _record_needs_ytdlp(rec, cfg):
                rec.setdefault("format_info", {})["format_probe_status"] = "skipped"
        return
    bin_path = shutil.which("yt-dlp")
    if not bin_path:
        for rec in records:
            if _record_needs_ytdlp(rec, cfg):
                rec.setdefault("format_info", {})["format_probe_status"] = "skipped"
                rec.setdefault("errors", []).append("yt_dlp_not_found")
        return

    cookie_args = ytdlp_cookie_args(cookie_settings)
    for rec in records:
        if not _record_needs_ytdlp(rec, cfg):
            continue
        cmd = [
            bin_path,
            "--skip-download",
            "--quiet",
            "--dump-single-json",
            "--no-playlist",
            *cookie_args,
            str(rec.get("video_url") or ""),
        ]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180, text=True)
            if proc.returncode != 0 or not proc.stdout.strip():
                if cookie_args:
                    fallback = [
                        bin_path,
                        "--skip-download",
                        "--quiet",
                        "--dump-single-json",
                        "--no-playlist",
                        str(rec.get("video_url") or ""),
                    ]
                    proc = subprocess.run(fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180, text=True)
                    rec.setdefault("errors", []).append("yt_dlp_cookie_failed_fallback_no_cookie")
                if proc.returncode != 0 or not proc.stdout.strip():
                    rec.setdefault("format_info", {})["format_probe_status"] = "unavailable"
                    rec.setdefault("errors", []).append("yt_dlp_metadata_failed")
                    continue
            info = json.loads(proc.stdout)
            _merge_ytdlp_info(rec, info)
        except subprocess.TimeoutExpired:
            rec.setdefault("format_info", {})["format_probe_status"] = "unavailable"
            rec.setdefault("errors", []).append("yt_dlp_timeout")
        except Exception as exc:
            rec.setdefault("format_info", {})["format_probe_status"] = "unavailable"
            rec.setdefault("errors", []).append(f"yt_dlp_failed:{type(exc).__name__}")


def _merge_json_ld_video_object(rec: Dict[str, Any], video_obj: Dict[str, Any]) -> None:
    if not isinstance(video_obj, dict):
        return
    if not rec.get("title") and video_obj.get("name"):
        rec["title"] = str(video_obj.get("name") or "")
    if not rec.get("description") and video_obj.get("description"):
        rec["description"] = str(video_obj.get("description") or "")
        rec["description_snippet"] = sniff_description(rec["description"])
    if not rec.get("published_at") and video_obj.get("uploadDate"):
        rec["published_at"] = str(video_obj.get("uploadDate") or "")
    if not rec.get("duration_seconds") and video_obj.get("duration"):
        rec["duration_seconds"] = _duration_seconds_from_iso(video_obj.get("duration"))
    thumbs = _as_list(video_obj.get("thumbnailUrl"))
    if thumbs and not rec.get("thumbnail_urls"):
        rec["thumbnail_urls"] = _unique_strs(thumbs)
    author = video_obj.get("author")
    if isinstance(author, dict) and not rec.get("channel_title"):
        rec["channel_title"] = str(author.get("name") or "")


def enrich_with_webpage_metadata(records: List[Dict[str, Any]], cookie_settings: CookieSettings) -> None:
    cookie_file = webpage_cookie_file(cookie_settings)
    for rec in records:
        if not _record_needs_webpage(rec):
            continue
        meta = fetch_webpage_metadata(str(rec.get("video_url") or ""), cookie_file=cookie_file)
        rec["webpage_metadata"] = meta
        rec["webpage_metadata_status"] = meta.get("webpage_metadata_status")
        if meta.get("webpage_metadata_status") == "ok":
            if not rec.get("title"):
                rec["title"] = meta.get("og_title") or meta.get("page_title") or ""
            if not rec.get("description"):
                rec["description"] = meta.get("og_description") or meta.get("page_description") or ""
                rec["description_snippet"] = sniff_description(rec.get("description") or "")
            json_ld = meta.get("json_ld") if isinstance(meta.get("json_ld"), dict) else {}
            _merge_json_ld_video_object(rec, json_ld.get("video_object") if isinstance(json_ld, dict) else {})
            rec.setdefault("metadata_sources", []).append("webpage_metadata")
        else:
            rec.setdefault("errors", []).append("webpage_metadata_failed")


def analyze_url_records(
    input_records: List[Dict[str, Any]],
    *,
    cfg: Dict[str, Any],
    cookie_settings: CookieSettings,
    offline: bool = False,
) -> List[Dict[str, Any]]:
    records = [_analysis_template(dict(row), cfg) for row in input_records]
    for rec in records:
        rec["cookie"] = cookie_status_for_record(cookie_settings)

    ua = cfg.get("url_analysis") or {}
    if offline:
        for rec in records:
            rec.setdefault("metadata_sources", []).append("offline_existing_fields_only")
        return records

    api_key = _youtube_api_key() if _truthy(ua.get("use_youtube_api")) else None
    if api_key:
        enrich_with_youtube_api(records, api_key)
    else:
        for rec in records:
            if _record_needs_api(rec):
                rec.setdefault("errors", []).append("youtube_api_key_missing")

    if _truthy(ua.get("use_ytdlp_metadata")):
        enrich_with_ytdlp(records, cfg, cookie_settings)

    if _truthy(ua.get("use_webpage_metadata")):
        enrich_with_webpage_metadata(records, cookie_settings)

    return records


def analyze_url_file(
    *,
    input_path: Path | str,
    output_path: Path | str,
    cfg_path: Path | str = URL_ANALYSIS_CONFIG_PATH,
    cookie_settings: CookieSettings,
    offline: bool = False,
) -> List[Dict[str, Any]]:
    cfg = load_url_analysis_config(cfg_path)
    rows = load_url_input(input_path)
    analyzed = analyze_url_records(rows, cfg=cfg, cookie_settings=cookie_settings, offline=offline)
    write_jsonl(output_path, analyzed)
    return analyzed


def _review_row(rec: Dict[str, Any], *, include_existing_manual: bool = False) -> Dict[str, Any]:
    fmt = rec.get("format_info") if isinstance(rec.get("format_info"), dict) else {}
    source = rec.get("source_context") if isinstance(rec.get("source_context"), dict) else {}
    auto = rec.get("auto_filter") if isinstance(rec.get("auto_filter"), dict) else {}
    manual = rec.get("manual_review") if isinstance(rec.get("manual_review"), dict) else {}
    return {
        "video_url": rec.get("video_url") or "",
        "title": rec.get("title") or "",
        "channel_title": rec.get("channel_title") or "",
        "brand": rec.get("brand") or source.get("brand") or "",
        "category": rec.get("category") or source.get("category") or "",
        "subcategory": rec.get("subcategory") or source.get("subcategory") or "",
        "duration_seconds": rec.get("duration_seconds") if rec.get("duration_seconds") is not None else "",
        "max_format_height": fmt.get("max_format_height") if fmt.get("max_format_height") is not None else "",
        "has_2160p_format": fmt.get("has_2160p_format"),
        "query_used": source.get("query_used") or "",
        "quality_score": auto.get("quality_score") if auto.get("quality_score") is not None else "",
        "llm_decision": auto.get("llm_decision") or "",
        "llm_reason": auto.get("llm_reason") or "",
        "manual_status": manual.get("status") if include_existing_manual else "",
        "manual_passed": manual.get("passed") if include_existing_manual else "",
        "manual_reject_reasons": ";".join(manual.get("reject_reasons") or []) if include_existing_manual else "",
        "manual_pass_features": ";".join(manual.get("pass_features") or []) if include_existing_manual else "",
        "manual_notes": manual.get("notes") if include_existing_manual else "",
        "reviewer": manual.get("reviewer") if include_existing_manual else "",
        "reviewed_at": manual.get("reviewed_at") if include_existing_manual else "",
    }


def export_review_sheet(
    records: Iterable[Dict[str, Any]],
    *,
    output_csv: Path | str,
    output_md: Path | str,
    include_existing_manual: bool = False,
) -> Tuple[Path, Path]:
    rows = [_review_row(r, include_existing_manual=include_existing_manual) for r in records]

    csv_path = Path(output_csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    md_path = Path(output_md)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_lines = [
        "# Manual review sheet",
        "",
        "| 序号 | 标题 | 频道 | URL | 品牌 | 时长 | 最大格式高度 | 自动评分 | LLM 判断 | 人工状态 | 人工拒绝原因 | 备注 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for idx, row in enumerate(rows, start=1):
        cells = [
            str(idx),
            str(row.get("title") or ""),
            str(row.get("channel_title") or ""),
            str(row.get("video_url") or ""),
            str(row.get("brand") or ""),
            str(row.get("duration_seconds") or ""),
            str(row.get("max_format_height") or ""),
            str(row.get("quality_score") or ""),
            str(row.get("llm_decision") or ""),
            str(row.get("manual_status") or ""),
            str(row.get("manual_reject_reasons") or ""),
            str(row.get("manual_notes") or ""),
        ]
        md_lines.append("| " + " | ".join(c.replace("|", "\\|").replace("\n", " ") for c in cells) + " |")
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return csv_path, md_path


def export_review_sheet_from_file(
    *,
    analysis_path: Path | str,
    output_csv: Path | str,
    output_md: Path | str,
    include_existing_manual: bool = False,
) -> Tuple[Path, Path]:
    return export_review_sheet(
        list(read_jsonl(analysis_path)),
        output_csv=output_csv,
        output_md=output_md,
        include_existing_manual=include_existing_manual,
    )
