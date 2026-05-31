#!/usr/bin/env python3
"""Append one CDP Runtime.evaluate result into browser raw JSON."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
SP = "EgYQARgEcAE%253D"

SEARCHES = [
    ("洋酒", "whiskey commercial -ai"),
    ("洋酒", "vodka commercial -ai"),
    ("洋酒", "cognac commercial -ai"),
    ("洋酒", "liquor commercial -ai"),
    ("洋酒", "spirits commercial -ai"),
    ("洋酒", "bourbon commercial -ai"),
    ("洋酒", "scotch commercial -ai"),
    ("洋酒", "tequila commercial -ai"),
    ("洋酒", "rum commercial -ai"),
    ("洋酒", "gin commercial -ai"),
    ("啤酒", "beer commercial -ai"),
    ("啤酒", "lager commercial -ai"),
    ("啤酒", "ale commercial -ai"),
    ("啤酒", "craft beer commercial -ai"),
    ("啤酒", "pilsner commercial -ai"),
    ("啤酒", "stout commercial -ai"),
]


def merge_value(idx: int, val: dict) -> int:
    category, query = SEARCHES[idx]
    urls = val.get("urls") or []
    out = ROOT / "output" / "browser_collections" / "liquor_browser_raw_inprogress.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raw = json.loads(out.read_text(encoding="utf-8"))
    else:
        raw = {"searches": [], "summary": {}}
    q = quote_plus(query)
    entry = {
        "category": category,
        "query": query,
        "search_url": f"https://www.youtube.com/results?search_query={q}&sp={SP}",
        "scroll_rounds": val.get("rounds"),
        "scroll_stable": val.get("stable"),
        "url_count": len(urls),
        "urls": urls,
    }
    raw["searches"] = [s for s in raw["searches"] if s.get("query") != query]
    raw["searches"].append(entry)
    total = sum(len(s.get("urls") or []) for s in raw["searches"])
    raw["summary"] = {"searches_done": len(raw["searches"]), "total_urls_raw": total}
    out.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"merged idx={idx} query={query!r} urls={len(urls)} total_raw={total}")
    return 0


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--stdin":
        idx = int(sys.argv[2])
        val = json.load(sys.stdin)
        return merge_value(idx, val)
    if len(sys.argv) < 3:
        print("usage: merge_browser_cdp_result.py <cdp_json_path> <query_index_0based>")
        print("   or: merge_browser_cdp_result.py --stdin <query_index_0based>  # JSON value on stdin")
        return 1
    cdp_path = Path(sys.argv[1])
    idx = int(sys.argv[2])
    data = json.loads(cdp_path.read_text(encoding="utf-8"))
    val = data.get("result", {}).get("value") or {}
    return merge_value(idx, val)


if __name__ == "__main__":
    raise SystemExit(main())
