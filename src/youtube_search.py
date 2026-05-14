from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Set

from dotenv import load_dotenv

from .search_plan_builder import load_search_plan
from .utils import (
    PROJECT_ROOT,
    blank_candidate,
    extract_video_id,
    load_yaml_mapping,
    merge_candidates,
    sniff_description,
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
        merged.setdefault("brands", [])
        merged.setdefault("preferred_channels", [])
        if not isinstance(merged.get("brands"), list):
            merged["brands"] = []
        if not isinstance(merged.get("preferred_channels"), list):
            merged["preferred_channels"] = []
        out.append(merged)
    return out


def _expand_keywords(task: Dict[str, Any]) -> List[str]:
    base_kws = [str(k).strip() for k in (task.get("keywords") or []) if str(k).strip()]
    brands = [str(b).strip() for b in (task.get("brands") or []) if str(b).strip()]
    out: List[str] = []
    seen: Set[str] = set()

    def add(k: str) -> None:
        kk = k.strip()
        if not kk:
            return
        low = kk.lower()
        if low in seen:
            return
        seen.add(low)
        out.append(kk)

    for k in base_kws:
        add(k)
    for b in brands:
        for k in base_kws:
            add(f"{b} {k}".strip())
    return out


def execute_search_plan(plan: Dict[str, Any], api_key: str) -> List[Dict[str, Any]]:
    from googleapiclient.discovery import build
    from tqdm import tqdm

    tasks = plan.get("tasks") or []
    if not isinstance(tasks, list):
        tasks = []

    glob = plan.get("global_rules") or {}
    default_region = str(glob.get("default_region_code") or "US")
    default_lang = str(glob.get("default_relevance_language") or "en")
    default_cap = int(glob.get("max_results_per_keyword") or 10)

    youtube = build("youtube", "v3", developerKey=api_key)
    merged_by_id: Dict[str, Dict[str, Any]] = {}

    total_kw = 0
    norm_tasks: List[Dict[str, Any]] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        kws = _expand_keywords(t)
        total_kw += len(kws)
        tt = dict(t)
        tt["_expanded_keywords"] = kws
        norm_tasks.append(tt)

    progress = tqdm(total=max(1, total_kw), desc="youtube.search", unit="kw")

    try:
        for task in norm_tasks:
            task_id = str(task.get("id") or "")
            category = str(task.get("category") or "")
            subcategory = str(task.get("subcategory") or "")
            region = str(task.get("region_code") or default_region)
            rel_lang = str(task.get("relevance_language") or default_lang)
            mrpk = int(task.get("max_results_per_keyword") or default_cap)

            for kw in task.get("_expanded_keywords") or []:
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
                            desc = snippet.get("description") or ""
                            cand = blank_candidate(
                                video_id=str(vid),
                                canonical_url=watch_url(str(vid)),
                                title=snippet.get("title") or "",
                                description=desc,
                                description_snippet=sniff_description(desc),
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
                                live_broadcast_content=str(live),
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


def run_search_plan(plan_yaml: Path | str, api_key: str) -> List[Dict[str, Any]]:
    plan = load_search_plan(Path(plan_yaml))
    return execute_search_plan(plan, api_key)


def run_search_tasks(task_yaml: Path | str, api_key: str) -> List[Dict[str, Any]]:
    """
    兼容旧 CLI：把 `search_tasks*.yaml` 机械包装为 plan dict 后执行检索。
    """
    from .search_plan_builder import build_search_plan_from_tasks

    plan = build_search_plan_from_tasks(task_yaml)
    return execute_search_plan(plan, api_key)
