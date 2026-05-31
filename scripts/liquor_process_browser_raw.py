#!/usr/bin/env python3
"""Process browser-scrolled YouTube search raw JSON → enrich, hard filter, content filter."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.liquor_commercial_scrape import (  # noqa: E402
    SEARCH_TERMS,
    TODAY,
    content_filter_reasons,
    dedupe_in_run,
    hard_filters,
    infer_category,
)
from src.core.hard_constraints import apply_hard_constraints
from src.utils import clean_text, extract_video_id, watch_url, write_jsonl
from src.youtube_collect import enrich_video_metadata


def rows_from_browser_raw(data: dict) -> list[dict]:
    rows: list[dict] = []
    for entry in data.get("searches") or []:
        category = str(entry.get("category") or "")
        query = str(entry.get("query") or "")
        search_url = str(entry.get("search_url") or "")
        for url in entry.get("urls") or []:
            vid = extract_video_id(str(url))
            if not vid:
                continue
            rows.append(
                {
                    "source_platform": "youtube",
                    "video_id": vid,
                    "video_url": watch_url(vid),
                    "canonical_url": watch_url(vid),
                    "source_search_url": search_url,
                    "search_query": query,
                    "liquor_category": category,
                    "collector_status": "browser_scroll_dom",
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser-raw", required=True, help="Path to browser raw JSON")
    args = parser.parse_args()

    raw_path = Path(args.browser_raw).resolve()
    data = json.loads(raw_path.read_text(encoding="utf-8"))
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ROOT / "output" / "browser_collections"
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / f"liquor_commercial_search_{ts}"

    youtube_cfg = {
        "metadata_timeout_seconds": 60,
        "cookies_enabled": True,
        "cookies_from_browser": "chrome",
        "metadata_sleep_seconds": 0.1,
        "extractor_retries": "2",
        "sleep_requests_seconds": "0.5",
    }

    rows = rows_from_browser_raw(data)
    print(f"[1/4] Browser raw URLs: {len(rows)}", flush=True)

    unique, dups = dedupe_in_run(rows)
    print(f"[2/4] In-run dedupe: unique={len(unique)} duplicates={len(dups)}", flush=True)

    print("[3/4] Enriching metadata (concurrency=4)...", flush=True)
    enriched, meta_warnings, meta_stats = enrich_video_metadata(
        unique, youtube_cfg=youtube_cfg, concurrency=8
    )
    print(f"  ok={meta_stats.get('ok')} failed={meta_stats.get('failed')}", flush=True)

    filters = hard_filters()
    hard_kept, hard_rejected, hard_stats = apply_hard_constraints(
        enriched, filters, today=TODAY
    )
    print(f"[4/4] Hard: kept={len(hard_kept)} rejected={len(hard_rejected)}", flush=True)

    kept: list[dict] = []
    content_rejected: list[dict] = []
    manual_review_pending: list[dict] = []
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
            manual_review_pending.append(row)

    # Manual metadata review pass (agent rules embedded)
    MANUAL_NEG = __import__("re").compile(
        r"\b(?:tutorial|how\s+to\s+make|vlog|unboxing|reaction|honest\s+review|"
        r"product\s+review|beer\s+review|whiskey\s+review|tasting|cocktail\s+recipe|"
        r"mixology|behind\s+the\s+scenes|making\s+of|bts\b|documentary|"
        r"news\s+report|interview|podcast|compilation|showreel|fan\s+edit|"
        r"music\s+video|lyrics|live\s+stream|episode\s+\d|full\s+movie|"
        r"explained|economics|class\s+project|student\s+project)\b",
        __import__("re").I,
    )
    for row in manual_review_pending:
        text = "\n".join(
            clean_text(x)
            for x in (row.get("title"), row.get("description"), row.get("channel_title"))
        )
        if MANUAL_NEG.search(text):
            row["manual_review_passed"] = False
            row["manual_review_reject_reasons"] = ["manual_non_ad_content"]
            row["rejection_stage"] = "manual_review"
            content_rejected.append(row)
        else:
            row["manual_review_passed"] = True
            row["manual_review_reject_reasons"] = []
            row["manual_review_note"] = "passed_agent_review"
            kept.append(row)

    kept.sort(key=lambda r: (r.get("liquor_category") or "", clean_text(r.get("title") or "")))
    urls = [str(r.get("video_url") or "") for r in kept]
    by_cat = {"洋酒": 0, "啤酒": 0}
    for r in kept:
        c = str(r.get("liquor_category") or "")
        if c in by_cat:
            by_cat[c] += 1

    payload = {
        "scraped_at_utc": ts,
        "today_reference": TODAY.isoformat(),
        "search_terms": SEARCH_TERMS,
        "collection_method": "browser scroll-to-bottom DOM scrape + yt-dlp metadata + hard/content/manual filters",
        "browser_raw_file": str(raw_path),
        "browser_collect_summary": data.get("summary"),
        "dedupe_in_run": {"unique": len(unique), "duplicates": len(dups)},
        "metadata_stats": meta_stats,
        "hard_constraint_stats": hard_stats,
        "stage_counts": {
            "browser_urls": len(rows),
            "unique_in_run": len(unique),
            "after_hard_constraints": len(hard_kept),
            "after_content_filter": len(manual_review_pending),
            "kept_after_manual_review": len(kept),
            "rejected_total": len(hard_rejected) + len(content_rejected),
            "by_category_kept": by_cat,
        },
        "urls": urls,
        "kept_records": kept,
        "hard_rejected_records": hard_rejected,
        "rejected_records": content_rejected,
        "metadata_warnings": meta_warnings[:30],
    }

    json_path = base.with_suffix(".json")
    txt_path = base.with_suffix(".urls.txt")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    txt_path.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
    write_jsonl(base.with_suffix(".kept.jsonl"), kept)
    write_jsonl(base.with_suffix(".hard_rejected.jsonl"), hard_rejected)
    write_jsonl(base.with_suffix(".rejected.jsonl"), content_rejected)

    print(f"Done kept={len(kept)} 洋酒={by_cat['洋酒']} 啤酒={by_cat['啤酒']}", flush=True)
    print(f"json={json_path}", flush=True)
    print(f"urls={txt_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
