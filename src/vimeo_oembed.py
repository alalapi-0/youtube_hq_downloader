from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, Iterable, List, Tuple

from .llm.web_url_scout import is_vimeo_video_url
from .utils import clean_text


OEMBED_ENDPOINT = "https://vimeo.com/api/oembed.json"


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


def _date_only(value: Any) -> str:
    text = clean_text(value).strip()
    if not text:
        return ""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return text[:10] if len(text) >= 10 else text


def fetch_vimeo_oembed(url: str, *, timeout_seconds: int = 10) -> Tuple[Dict[str, Any] | None, str]:
    """Fetch Vimeo public oEmbed metadata without cookies, API keys, or downloads."""
    if not is_vimeo_video_url(url):
        return None, "not_vimeo_video_url"
    query = urllib.parse.urlencode({"url": url})
    request = urllib.request.Request(
        f"{OEMBED_ENDPOINT}?{query}",
        headers={
            "Accept": "application/json",
            "User-Agent": "ad-url-scout/1.0 (+https://vimeo.com)",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1, int(timeout_seconds))) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return None, f"http_{exc.code}"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        return None, f"invalid_json: {exc}"
    return data if isinstance(data, dict) else None, "ok"


def merge_vimeo_oembed_metadata(row: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    title = clean_text(data.get("title") or "")
    description = clean_text(data.get("description") or "")
    author = clean_text(data.get("author_name") or "")
    author_url = clean_text(data.get("author_url") or "")
    upload_date = _date_only(data.get("upload_date"))
    duration = _as_int(data.get("duration"))
    video_id = clean_text(data.get("video_id") or "")
    thumbnail_url = clean_text(data.get("thumbnail_url") or "")

    if title:
        out["title"] = title
    if description:
        out["description"] = description
        out["description_snippet"] = " ".join(description.split())[:240]
    if author:
        out["channel_title"] = author
    if author_url:
        out["channel_url"] = author_url
    if upload_date:
        out["published_at"] = upload_date
        if not out.get("date_evidence"):
            out["date_evidence"] = f"Vimeo oEmbed upload_date {upload_date}"
    if duration is not None:
        out["duration_seconds"] = duration
        if not out.get("duration_evidence"):
            out["duration_evidence"] = f"Vimeo oEmbed duration {duration}s"
    if video_id:
        out["video_id"] = video_id
    if thumbnail_url:
        existing = out.get("thumbnail_urls") if isinstance(out.get("thumbnail_urls"), list) else []
        out["thumbnail_urls"] = [*existing, thumbnail_url]

    out["vimeo_oembed_status"] = "ok"
    out["vimeo_oembed"] = {
        "title": title,
        "author_name": author,
        "author_url": author_url,
        "duration": duration,
        "upload_date": upload_date,
        "video_id": video_id,
        "thumbnail_url": thumbnail_url,
    }
    return out


def enrich_vimeo_oembed_rows(
    rows: Iterable[Dict[str, Any]],
    *,
    enabled: bool = True,
    timeout_seconds: int = 10,
) -> Tuple[List[Dict[str, Any]], Dict[str, int], List[str]]:
    enriched: List[Dict[str, Any]] = []
    warnings: List[str] = []
    stats = {"total": 0, "ok": 0, "failed": 0, "skipped": 0}
    for record in rows:
        stats["total"] += 1
        row = dict(record)
        url = clean_text(row.get("canonical_url") or row.get("video_url") or row.get("url") or "").strip()
        if not enabled or not url:
            row["vimeo_oembed_status"] = "skipped"
            stats["skipped"] += 1
            enriched.append(row)
            continue
        data, status = fetch_vimeo_oembed(url, timeout_seconds=timeout_seconds)
        if data:
            stats["ok"] += 1
            enriched.append(merge_vimeo_oembed_metadata(row, data))
            continue
        row["vimeo_oembed_status"] = status
        stats["failed"] += 1
        warnings.append(f"Vimeo oEmbed 读取失败：{url} ({status})")
        enriched.append(row)
    return enriched, stats, warnings
