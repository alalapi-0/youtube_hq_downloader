#!/usr/bin/env python3
"""One-off: scrape purse commercial search, enrich metadata, filter ads only."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils import clean_text, extract_video_id, watch_url, write_jsonl
from src.youtube_collect import collect_search_page_urls, enrich_video_metadata

SEARCH_URL = "https://www.youtube.com/results?search_query=purse+commercial+-ai&sp=EgYQARgEcAE%253D"

PURSE_TOPIC_RE = re.compile(
    r"\b(?:purse|purses|handbag|handbags|clutch|tote|satchel|crossbody|"
    r"shoulder\s+bag|kleio\s+bag|lux\s+de\s+ville|getaway\s+bag)\b",
    re.I,
)
AD_POSITIVE_RE = re.compile(
    r"\b(?:commercial|advertisement|advertising|ad\s+film|ad\b|tvc|"
    r"brand\s+film|campaign\s+film|campaign\s+video|product\s+film|"
    r"spec\s+ad|tv\s+spot|spot\b|promo\s+video|promotional)\b",
    re.I,
)
AD_NEGATIVE_RE = re.compile(
    r"\b(?:tutorial|how\s+to|vlog|unboxing|reaction|review(?!\s+sheet)|"
    r"news\b|interview|podcast|documentary|episode\s+\d|full\s+movie|"
    r"behind\s+the\s+scenes|making\s+of|compilation|showreel|haul\b|"
    r"asmr|diy\b|tips\s+and\s+tricks|lesson\b|course\b|explained|"
    r"reaction\s+video|street\s+interview|podcast|live\s+stream|"
    r"lyrics|music\s+video|cover\s+song|fan\s+edit|fanmade|"
    r"parody\s+review|honest\s+review|product\s+review)\b",
    re.I,
)
NON_PURSE_BAG_RE = re.compile(
    r"\b(?:ziploc|storage\s+bag|garbage\s+bag|trash\s+bag|vacuum\s+bag|"
    r"sleeping\s+bag|tea\s+bag|dog\s+bag|poop\s+bag)\b",
    re.I,
)


def dedupe_in_run(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    seen: set[str] = set()
    unique: list[dict] = []
    dups: list[dict] = []
    for row in rows:
        vid = str(row.get("video_id") or extract_video_id(str(row.get("video_url") or "")) or "")
        key = f"youtube:{vid}" if vid else ""
        if not key or key in seen:
            dups.append(row)
            continue
        seen.add(key)
        unique.append(row)
    return unique, dups


def combined_text(row: dict) -> str:
    tags = row.get("tags") if isinstance(row.get("tags"), list) else []
    return "\n".join(
        clean_text(x)
        for x in (
            row.get("title"),
            row.get("description"),
            row.get("channel_title"),
            " ".join(str(t) for t in tags),
        )
    )


def filter_reasons(row: dict) -> list[str]:
    text = combined_text(row)
    reasons: list[str] = []
    if AD_NEGATIVE_RE.search(text):
        reasons.append("non_ad_content_signal")
    if NON_PURSE_BAG_RE.search(text) and not PURSE_TOPIC_RE.search(text):
        reasons.append("non_purse_bag_topic")
    if not PURSE_TOPIC_RE.search(text):
        reasons.append("missing_purse_handbag_topic")
    has_ad = bool(AD_POSITIVE_RE.search(text))
    channel = clean_text(row.get("channel_title") or "").lower()
    brand_channel = any(
        x in channel
        for x in (
            "commercial",
            "campaign",
            "advertising",
            "brand",
            "official",
            "production",
            "films",
            "studio",
        )
    )
    if not has_ad and not brand_channel:
        reasons.append("missing_commercial_ad_signal")
    duration = row.get("duration_seconds")
    if duration is not None and int(duration) > 180:
        reasons.append("duration_too_long_for_spot_ad")
    title = clean_text(row.get("title") or "").lower()
    if re.search(r"\b(short\s+film|indie\s+film|student\s+film|crowdfund)\b", title):
        reasons.append("likely_non_commercial_film")
    return reasons


def main() -> int:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ROOT / "output" / "browser_collections"
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / f"purse_commercial_search_{ts}"

    youtube_cfg = {
        "metadata_timeout_seconds": 90,
        "cookies_enabled": True,
        "cookies_from_browser": "chrome",
        "metadata_sleep_seconds": 0.3,
        "extractor_retries": "3",
        "sleep_requests_seconds": "1",
    }

    print("[1/4] Collecting search page URLs via yt-dlp...", flush=True)
    rows, warnings, stats = collect_search_page_urls(
        [SEARCH_URL],
        youtube_cfg=youtube_cfg,
        max_entries_per_page=500,
    )
    print(f"  collected={stats.get('video_urls')} warnings={len(warnings)}", flush=True)

    unique, dups = dedupe_in_run(rows)
    print(f"[2/4] In-run dedupe: unique={len(unique)} duplicates={len(dups)}", flush=True)

    print("[3/4] Enriching metadata (concurrency=4)...", flush=True)
    enriched, meta_warnings, meta_stats = enrich_video_metadata(
        unique,
        youtube_cfg=youtube_cfg,
        concurrency=4,
    )
    print(f"  metadata ok={meta_stats.get('ok')} failed={meta_stats.get('failed')}", flush=True)

    kept: list[dict] = []
    rejected: list[dict] = []
    for row in enriched:
        reasons = filter_reasons(row)
        row = dict(row)
        row["filter_passed"] = not reasons
        row["filter_reject_reasons"] = reasons
        if reasons:
            rejected.append(row)
        else:
            kept.append(row)

    kept.sort(key=lambda r: clean_text(r.get("title") or ""))
    urls = [str(r.get("video_url") or r.get("canonical_url") or "") for r in kept]

    payload = {
        "search_url": SEARCH_URL,
        "scraped_at_utc": ts,
        "collection_method": "yt-dlp flat-playlist (Chrome cookies); Cursor browser had no pre-scrolled user tab",
        "collect_stats": stats,
        "dedupe_in_run": {"unique": len(unique), "duplicates": len(dups)},
        "metadata_stats": meta_stats,
        "filter_criteria_summary": {
            "keep_requires": [
                "title/description/tags mention purse/handbag/bag product terms",
                "commercial/ad/campaign/TVC/spec-ad style signal OR production-style channel name",
            ],
            "reject_if": [
                "tutorial/vlog/review/news/interview/compilation/haul/ASMR/DIY etc.",
                "non-purse bag products (ziploc/storage/trash bags) without purse topic",
                "duration > 180s",
                "short/indie/student/crowdfund film signals in title",
            ],
        },
        "counts": {
            "collected": len(rows),
            "unique_in_run": len(unique),
            "metadata_enriched": len(enriched),
            "kept_after_filter": len(kept),
            "rejected_after_filter": len(rejected),
        },
        "urls": urls,
        "kept_records": kept,
        "rejected_records": rejected,
        "collect_warnings": warnings[:20],
        "metadata_warnings": meta_warnings[:20],
    }

    json_path = base.with_suffix(".json")
    txt_path = base.with_suffix(".urls.txt")
    jsonl_kept = base.with_suffix(".kept.jsonl")
    jsonl_rejected = base.with_suffix(".rejected.jsonl")

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    txt_path.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
    write_jsonl(jsonl_kept, kept)
    write_jsonl(jsonl_rejected, rejected)

    print(f"[4/4] Done. kept={len(kept)} rejected={len(rejected)}", flush=True)
    print(f"  json: {json_path}", flush=True)
    print(f"  urls: {txt_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
