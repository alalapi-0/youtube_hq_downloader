from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import isodate

from .env_loader import load_dotenv
from .utils import (
    PROJECT_ROOT,
    append_error,
    blank_candidate,
    detect_text_4k_evidence,
    extract_video_id,
    flatten_brand_names,
    load_yaml_mapping,
    merge_candidates,
    sniff_description,
    watch_url,
)


def youtube_api_key() -> Optional[str]:
    load_dotenv(PROJECT_ROOT / ".env")
    k = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if "your_" in k or "optional_" in k:
        k = ""
    return k or None


def chunks(seq: List[str], n: int) -> Iterable[List[str]]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _detect_brand(title: str, description: str, brand_names: List[str]) -> str:
    hay = f"{title or ''}\n{description or ''}".lower()
    for name in brand_names:
        if name.lower() in hay:
            return name
    return ""


def enrich_records(records: List[Dict[str, Any]], api_key: str) -> List[Dict[str, Any]]:
    from googleapiclient.discovery import build
    from tqdm import tqdm

    brand_cfg = load_yaml_mapping(PROJECT_ROOT / "config" / "brands.yaml")
    brand_names = flatten_brand_names(brand_cfg)

    youtube = build("youtube", "v3", developerKey=api_key)
    indexed = [(i, dict(r)) for i, r in enumerate(records)]

    fixed: Dict[str, Dict[str, Any]] = {}
    for _, row in indexed:
        vid = row.get("video_id") or extract_video_id(row.get("canonical_url") or "")
        if not vid:
            continue
        vid = str(vid)
        base = dict(row)
        base["video_id"] = vid
        cand = blank_candidate(**base)
        if vid in fixed:
            fixed[vid] = merge_candidates(fixed[vid], cand)
        else:
            fixed[vid] = cand

    unique_ids = list(fixed.keys())
    details: Dict[str, Dict[str, Any]] = {}

    for batch in tqdm(list(chunks(unique_ids, 50)), desc="videos.list", unit="batch"):
        res = youtube.videos().list(
            part="snippet,statistics,contentDetails,liveStreamingDetails",
            id=",".join(batch),
            maxResults=50,
        ).execute()
        for it in res.get("items") or []:
            vid = (it.get("id") or "").strip()
            if not vid:
                continue
            details[vid] = it

    out: List[Dict[str, Any]] = []
    for _, row in sorted(indexed, key=lambda x: x[0]):
        vid = row.get("video_id") or extract_video_id(row.get("canonical_url") or "")
        vid = str(vid or "")
        if not vid:
            continue
        base = blank_candidate(**fixed.get(vid, row), video_id=vid)
        it = details.get(vid)
        if not it:
            base["canonical_url"] = watch_url(vid)
            text_ok, td = detect_text_4k_evidence(base["title"], base["description"])
            base["resolution_text_evidence_4k"] = text_ok
            base["resolution_text_evidence_detail"] = td
            base["description_snippet"] = sniff_description(base.get("description") or "")
            base.setdefault("live_broadcast_content", "none")
            base["brand"] = base.get("brand") or _detect_brand(base["title"], base["description"], brand_names)
            append_error(base, "videos.list:missing_item")
            out.append(base)
            continue

        sn = it.get("snippet") or {}
        st = it.get("statistics") or {}
        cd = it.get("contentDetails") or {}
        live = sn.get("liveBroadcastContent") or "none"
        duration_iso = cd.get("duration") or ""
        duration_sec: Optional[int] = None
        if duration_iso:
            try:
                duration_sec = int(isodate.parse_duration(duration_iso).total_seconds())
            except Exception:
                duration_sec = None

        thumbs = sn.get("thumbnails") or {}
        best_thumb = thumbs.get("maxres") or thumbs.get("high") or {}

        desc = sn.get("description") or ""
        title = sn.get("title") or ""
        merged = merge_candidates(
            base,
            {
                "title": title,
                "description": desc,
                "description_snippet": sniff_description(desc),
                "channel_id": sn.get("channelId") or "",
                "channel_title": sn.get("channelTitle") or "",
                "published_at": sn.get("publishedAt") or "",
                "tags": sn.get("tags") or [],
                "duration_iso8601": duration_iso,
                "duration_seconds": duration_sec,
                "definition": cd.get("definition") or "",
                "caption_available": cd.get("caption") == "true",
                "is_live": str(live) != "none"
                or (
                    isinstance(it.get("liveStreamingDetails"), dict) and bool(it.get("liveStreamingDetails"))
                ),
                "live_broadcast_content": str(live),
                "view_count": int(st["viewCount"])
                if st.get("viewCount") and str(st["viewCount"]).isdigit()
                else None,
                "like_count": int(st["likeCount"])
                if st.get("likeCount") and str(st["likeCount"]).isdigit()
                else None,
                "comment_count": int(st["commentCount"])
                if st.get("commentCount") and str(st["commentCount"]).isdigit()
                else None,
                "thumbnail_best_url": base.get("thumbnail_best_url") or (best_thumb.get("url") or ""),
                "canonical_url": watch_url(vid),
                "brand": base.get("brand") or _detect_brand(title, desc, brand_names),
            },
        )

        canon = merged.get("canonical_url") or ""
        merged["is_shorts_candidate"] = bool(
            (
                duration_sec is not None
                and duration_sec <= 180
                and ("shorts" in canon.lower() or "#shorts" in desc.lower())
            )
            or "/shorts/" in canon.lower()
            or merged.get("is_shorts_candidate")
        )

        t_ok, t_det = detect_text_4k_evidence(merged["title"], merged["description"])
        merged["resolution_text_evidence_4k"] = t_ok
        merged["resolution_text_evidence_detail"] = t_det

        out.append(merged)

    return out
