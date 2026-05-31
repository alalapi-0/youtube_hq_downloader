#!/usr/bin/env python3
"""Save browser URL chunks into a single JSON file for merge."""
from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "output" / "browser_collections" / "_pending_urls.json"


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: save_browser_urls_chunk.py <chunk_index> <urls_json_file>")
        return 1
    idx = int(sys.argv[1])
    chunk_path = Path(sys.argv[2])
    chunk = json.loads(chunk_path.read_text(encoding="utf-8"))
    urls = chunk if isinstance(chunk, list) else chunk.get("urls") or []
    if OUT.exists():
        data = json.loads(OUT.read_text(encoding="utf-8"))
    else:
        data = {"chunks": {}}
    data["chunks"][str(idx)] = urls
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total = sum(len(v) for v in data["chunks"].values())
    print(f"chunk {idx}: +{len(urls)} total_stored={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
