from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

from .utils import (
    PROJECT_ROOT,
    blank_candidate,
    extract_video_id,
    load_yaml_mapping,
    merge_candidates,
    watch_url,
)


def ensure_api_key() -> str | None:
    load_dotenv(PROJECT_ROOT / ".env")
    k = os.environ.get("YOUTUBE_API_KEY", "").strip()
    return k or None


def load_search_tasks(task_path: Path | str) -> List[Dict[str, Any]]:
    data = load_yaml_mapping(task_path)
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        return []
    out: List[Dict[str, Any]] = []
    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id") or f"task_{i}")
        merged = dict(t)
        merged["id"] = tid
        out.append(merged)
    return out


def run_search_tasks(task_yaml: Path | str, api_key: str) -> List[Dict[str, Any]]:
    from googleapiclient.discovery import build

    tasks = load_search_tasks(task_yaml)
    youtube = build("youtube", "v3", developerKey=api_key)
    merged_by_id: Dict[str, Dict[str, Any]] = {}

    from tqdm import tqdm

    total_kw = sum(len((t.get("keywords") or [])) if isinstance(t.get("keywords"), list) else 0 for t in tasks)

    progress = tqdm(total=total_kw, desc="youtube.search", unit="kw")

    try:
        for task in tasks:
            task_id = str(task.get("id") or "")
            category = str(task.get("category") or "")
            subcategory = str(task.get("subcategory") or "")
            region = task.get("region_code") or "US"
            rel_lang = task.get("relevance_language") or "en"
            keywords = task.get("keywords") or []

            if not isinstance(keywords, list):
                keywords = []

            mrpk = int(task.get("max_results_per_keyword") or 10)

            for kw in keywords:
                kw = str(kw)
                fetched = 0
                page_token = None

                try:
                    while fetched < mrpk:
                        chunk = min(50, mrpk - fetched)
                        req = youtube.search().list(
                            part="snippet",
                            q=kw,
                            type="video",
                            maxResults=chunk,
                            regionCode=str(region),
                            relevanceLanguage=str(rel_lang),
                            pageToken=page_token,
                        )
                        res = req.execute()
                        items = res.get("items") or []

                        if not items:
                            break

                        for it in items:
                            vid = (it.get("id") or {}).get("videoId")
                            snippet = it.get("snippet") or {}
                            if not vid:
                                vid = extract_video_id(snippet.get("title") or "")
                            if not vid:
                                continue

                            thumbs = snippet.get("thumbnails") or {}
                            best_thumb = thumbs.get("maxres") or thumbs.get("high") or {}
                            live = snippet.get("liveBroadcastContent") or "none"
                            cand = blank_candidate(
                                video_id=str(vid),
                                canonical_url=watch_url(str(vid)),
                                title=snippet.get("title") or "",
                                description=snippet.get("description") or "",
                                channel_id=snippet.get("channelId") or "",
                                channel_title=snippet.get("channelTitle") or "",
                                published_at=snippet.get("publishedAt") or "",
                                thumbnail_best_url=best_thumb.get("url") or "",
                                region_code=str(region),
                                relevance_language=str(rel_lang),
                                category=category,
                                subcategory=subcategory,
                                search_task_id=task_id,
                                matched_keywords=[kw],
                                is_live=str(live) != "none",
                                format_probe_status="pending",
                                manual_review_status="pending",
                            )

                            if vid in merged_by_id:
                                merged_by_id[str(vid)] = merge_candidates(merged_by_id[str(vid)], cand)
                            else:
                                merged_by_id[str(vid)] = cand

                        fetched += len(items)
                        page_token = res.get("nextPageToken")
                        if not page_token:
                            break
                finally:
                    progress.update(1)
    finally:
        progress.close()

    return list(merged_by_id.values())
