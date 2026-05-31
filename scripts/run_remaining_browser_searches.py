#!/usr/bin/env python3
"""Print remaining search URLs for browser MCP collection (indices 2-15)."""
from merge_browser_cdp_result import SEARCHES  # type: ignore

import json
from pathlib import Path
from urllib.parse import quote_plus

SP = "EgYQARgEcAE%253D"
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "output" / "browser_collections" / "liquor_browser_raw_inprogress.json"
done = set()
if RAW.exists():
    data = json.loads(RAW.read_text(encoding="utf-8"))
    done = {s.get("query") for s in data.get("searches") or []}

for i, (cat, q) in enumerate(SEARCHES):
    if q in done:
        continue
    enc = quote_plus(q)
    print(f"{i}\t{cat}\t{q}\thttps://www.youtube.com/results?search_query={enc}&sp={SP}")
