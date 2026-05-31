#!/usr/bin/env python3
"""Fresh scrape: imported spirits (洋酒) and beer (啤酒) YouTube commercial ads."""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.hard_constraints import apply_hard_constraints, hard_constraints_from_config
from src.utils import clean_text, extract_video_id, write_jsonl
from src.youtube_collect import collect_search_page_urls, enrich_video_metadata

SP_FILTER = "EgYQARgEcAE%253D"
TODAY = date(2026, 5, 22)

SEARCH_TERMS: dict[str, list[str]] = {
    "洋酒": [
        "whiskey commercial -ai",
        "vodka commercial -ai",
        "cognac commercial -ai",
        "liquor commercial -ai",
        "spirits commercial -ai",
        "bourbon commercial -ai",
        "scotch commercial -ai",
        "tequila commercial -ai",
        "rum commercial -ai",
        "gin commercial -ai",
    ],
    "啤酒": [
        "beer commercial -ai",
        "lager commercial -ai",
        "ale commercial -ai",
        "craft beer commercial -ai",
        "pilsner commercial -ai",
        "stout commercial -ai",
    ],
}

SPIRITS_TOPIC_RE = re.compile(
    r"\b(?:whiskey|whisky|vodka|cognac|liquor|spirits|bourbon|scotch|"
    r"tequila|rum|gin|brandy|hennessy|absolut|jack\s+daniels|"
    r"johnnie\s+walker|chivas|martell|bacardi|smirnoff|"
    r"glenfiddich|macallan|jameson|grey\s+goose|belvedere)\b",
    re.I,
)
BEER_TOPIC_RE = re.compile(
    r"\b(?:beer|lager|ale|pilsner|stout|ipa|brewery|brewing|"
    r"heineken|budweiser|corona|guinness|stella|carlsberg|"
    r"asahi|tsingtao|craft\s+beer)\b",
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
    r"reaction\s+video|street\s+interview|live\s+stream|"
    r"lyrics|music\s+video|cover\s+song|fan\s+edit|fanmade|"
    r"parody\s+review|honest\s+review|product\s+review|tasting\s+notes|"
    r"beer\s+review|whiskey\s+review|cocktail\s+recipe|mixology\s+class)\b",
    re.I,
)
NON_LIQUOR_RE = re.compile(
    r"\b(?:root\s+beer|ginger\s+beer|near\s+beer|rootbeer)\b",
    re.I,
)


def search_url(query: str) -> str:
    q = quote_plus(query.strip())
    return f"https://www.youtube.com/results?search_query={q}&sp={SP_FILTER}"


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


def infer_category(row: dict) -> str:
    text = combined_text(row)
    beer = bool(BEER_TOPIC_RE.search(text))
    spirits = bool(SPIRITS_TOPIC_RE.search(text))
    if beer and not spirits:
        return "啤酒"
    if spirits and not beer:
        return "洋酒"
    if beer and spirits:
        return row.get("liquor_category") or "洋酒"
    return str(row.get("liquor_category") or "")


def content_filter_reasons(row: dict) -> list[str]:
    text = combined_text(row)
    reasons: list[str] = []
    category = infer_category(row) or str(row.get("liquor_category") or "")
    if AD_NEGATIVE_RE.search(text):
        reasons.append("non_ad_content_signal")
    if NON_LIQUOR_RE.search(text) and not (SPIRITS_TOPIC_RE.search(text) or BEER_TOPIC_RE.search(text)):
        reasons.append("non_liquor_topic")
    if category == "洋酒" and not SPIRITS_TOPIC_RE.search(text):
        reasons.append("missing_spirits_topic")
    if category == "啤酒" and not BEER_TOPIC_RE.search(text):
        reasons.append("missing_beer_topic")
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
            "brewery",
        )
    )
    if not has_ad and not brand_channel:
        reasons.append("missing_commercial_ad_signal")
    title = clean_text(row.get("title") or "").lower()
    if re.search(r"\b(short\s+film|indie\s+film|student\s+film|crowdfund)\b", title):
        reasons.append("likely_non_commercial_film")
    return reasons


def hard_filters() -> dict:
    filters = hard_constraints_from_config({})
    filters.update(
        {
            "require_4k": True,
            "min_height": 2160,
            "max_duration_seconds": 120,
            "published_within_days": 1826,
            "reject_if_missing_4k_evidence": True,
            "reject_if_missing_duration": True,
            "reject_if_missing_publish_date": True,
            "require_professional_campaign": False,
            "require_specific_brand_product_ad": False,
        }
    )
    return filters


def main() -> int:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ROOT / "output" / "browser_collections"
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / f"liquor_commercial_search_{ts}"

    youtube_cfg = {
        "metadata_timeout_seconds": 90,
        "cookies_enabled": True,
        "cookies_from_browser": "chrome",
        "metadata_sleep_seconds": 0.3,
        "extractor_retries": "3",
        "sleep_requests_seconds": "1",
    }

    search_urls: list[str] = []
    url_to_category: dict[str, str] = {}
    url_to_query: dict[str, str] = {}
    for category, queries in SEARCH_TERMS.items():
        for q in queries:
            u = search_url(q)
            search_urls.append(u)
            url_to_category[u] = category
            url_to_query[u] = q

    print(f"[1/5] Collecting from {len(search_urls)} search pages...", flush=True)
    rows, warnings, stats = collect_search_page_urls(
        search_urls,
        youtube_cfg=youtube_cfg,
        max_entries_per_page=300,
    )
    for row in rows:
        src = str(row.get("source_search_url") or "")
        row["liquor_category"] = url_to_category.get(src, "")
        row["search_query"] = url_to_query.get(src, "")
    print(f"  collected={stats.get('video_urls')} warnings={len(warnings)}", flush=True)

    unique, dups = dedupe_in_run(rows)
    print(f"[2/5] In-run dedupe: unique={len(unique)} duplicates={len(dups)}", flush=True)

    print("[3/5] Enriching metadata (concurrency=4)...", flush=True)
    enriched, meta_warnings, meta_stats = enrich_video_metadata(
        unique,
        youtube_cfg=youtube_cfg,
        concurrency=4,
    )
    print(f"  metadata ok={meta_stats.get('ok')} failed={meta_stats.get('failed')}", flush=True)

    filters = hard_filters()
    hard_kept, hard_rejected, hard_stats = apply_hard_constraints(
        enriched,
        filters,
        today=TODAY,
    )
    print(
        f"[4/5] Hard constraints: kept={len(hard_kept)} rejected={len(hard_rejected)}",
        flush=True,
    )
    print(f"  reject_stats={json.dumps({k: v for k, v in hard_stats.items() if k not in ('total', 'kept', 'rejected')}, ensure_ascii=False)}", flush=True)

    kept: list[dict] = []
    content_rejected: list[dict] = []
    for row in hard_kept:
        row = dict(row)
        row["liquor_category"] = infer_category(row) or row.get("liquor_category") or ""
        reasons = content_filter_reasons(row)
        row["content_filter_passed"] = not reasons
        row["content_filter_reject_reasons"] = reasons
        if reasons:
            row["rejection_stage"] = "content_filter"
            content_rejected.append(row)
        else:
            kept.append(row)

    kept.sort(key=lambda r: (r.get("liquor_category") or "", clean_text(r.get("title") or "")))
    urls = [str(r.get("video_url") or r.get("canonical_url") or "") for r in kept]

    by_cat = {"洋酒": 0, "啤酒": 0}
    for r in kept:
        c = str(r.get("liquor_category") or "")
        if c in by_cat:
            by_cat[c] += 1

    payload = {
        "scraped_at_utc": ts,
        "today_reference": TODAY.isoformat(),
        "search_terms": SEARCH_TERMS,
        "search_urls": search_urls,
        "collection_method": "yt-dlp flat-playlist + full metadata (Chrome cookies)",
        "collect_stats": stats,
        "dedupe_in_run": {"unique": len(unique), "duplicates": len(dups)},
        "metadata_stats": meta_stats,
        "hard_constraint_filters": {
            "require_4k": True,
            "min_height": 2160,
            "max_duration_seconds": 120,
            "published_within_days": 1826,
            "publish_cutoff_approx": "2021-05-22",
        },
        "hard_constraint_stats": hard_stats,
        "content_filter_criteria": {
            "keep_requires": [
                "category topic keywords (spirits/beer)",
                "commercial/ad/campaign/TVC signal OR production-style channel",
            ],
            "reject_if": [
                "tutorial/vlog/review/recipe/tasting/etc.",
                "non-liquor beer (root beer) without liquor topic",
                "missing category topic or ad signal",
            ],
        },
        "stage_counts": {
            "collected": len(rows),
            "unique_in_run": len(unique),
            "metadata_enriched": len(enriched),
            "after_hard_constraints": len(hard_kept),
            "hard_rejected": len(hard_rejected),
            "kept_after_content_filter": len(kept),
            "content_rejected": len(content_rejected),
            "by_category_kept": by_cat,
        },
        "urls": urls,
        "kept_records": kept,
        "hard_rejected_records": hard_rejected,
        "content_rejected_records": content_rejected,
        "collect_warnings": warnings[:30],
        "metadata_warnings": meta_warnings[:30],
    }

    json_path = base.with_suffix(".json")
    txt_path = base.with_suffix(".urls.txt")
    jsonl_kept = base.with_suffix(".kept.jsonl")
    jsonl_hard_rej = base.with_suffix(".hard_rejected.jsonl")
    jsonl_content_rej = base.with_suffix(".rejected.jsonl")

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    txt_path.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
    write_jsonl(jsonl_kept, kept)
    write_jsonl(jsonl_hard_rej, hard_rejected)
    write_jsonl(jsonl_content_rej, content_rejected)

    print(f"[5/5] Done. kept={len(kept)} (洋酒={by_cat['洋酒']} 啤酒={by_cat['啤酒']})", flush=True)
    print(f"  json: {json_path}", flush=True)
    print(f"  urls: {txt_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
