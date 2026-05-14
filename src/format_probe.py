from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


def _yt_dlp_path() -> Optional[str]:
    return shutil.which("yt-dlp")


def _collect_heights(info: Dict[str, Any]) -> List[int]:
    hs: Set[int] = set()
    for fmt in info.get("formats") or []:
        h = fmt.get("height")
        try:
            if h is not None:
                hs.add(int(h))
        except (TypeError, ValueError):
            continue
    return sorted(hs)


def _parse_max_height_from_json(info: Dict[str, Any]) -> Tuple[Optional[int], bool, List[int]]:
    heights = _collect_heights(info)
    max_h = max(heights) if heights else None
    has_2160 = bool(max_h and max_h >= 2160) or ("2160p" in str(info.get("format") or ""))
    return max_h, has_2160, heights


def probe_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if os.environ.get("SKIP_FORMAT_PROBE", "").strip():
        out: List[Dict[str, Any]] = []
        for r in records:
            row = dict(r)
            row["format_probe_status"] = "skipped"
            row.setdefault("probe_max_height", None)
            row.setdefault("probe_confirmed_4k", False)
            row.setdefault("available_format_heights", row.get("available_format_heights") or [])
            out.append(row)
        return out

    bin_path = _yt_dlp_path()
    out: List[Dict[str, Any]] = []

    if not bin_path:
        for r in records:
            row = dict(r)
            row["format_probe_status"] = "skipped"
            row.setdefault("probe_max_height", None)
            row.setdefault("probe_confirmed_4k", False)
            row.setdefault("available_format_heights", row.get("available_format_heights") or [])
            out.append(row)
        return out

    for row in records:
        r = dict(row)
        url = r.get("canonical_url") or ""
        vid = r.get("video_id") or ""
        if url and vid and f"v={vid}" not in url and vid not in url:
            url = f"https://www.youtube.com/watch?v={vid}"
        if not url and vid:
            url = f"https://www.youtube.com/watch?v={vid}"
        cmd = [
            bin_path,
            "--skip-download",
            "--quiet",
            "--dump-single-json",
            "--no-playlist",
            url,
        ]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180, text=True)
            if proc.returncode != 0 or not proc.stdout.strip():
                r["format_probe_status"] = "unavailable"
                r["probe_confirmed_4k"] = False
                r.setdefault("available_format_heights", [])
            else:
                info = json.loads(proc.stdout)
                mx, ok, heights = _parse_max_height_from_json(info)
                r["probe_max_height"] = mx
                r["probe_confirmed_4k"] = ok
                r["available_format_heights"] = heights
                r["format_probe_status"] = "ok"
        except subprocess.TimeoutExpired:
            r["format_probe_status"] = "unavailable"
            r.setdefault("probe_max_height", None)
            r["probe_confirmed_4k"] = False
            r.setdefault("available_format_heights", [])
        except Exception:
            r["format_probe_status"] = "unavailable"
            r.setdefault("probe_max_height", None)
            r["probe_confirmed_4k"] = False
            r.setdefault("available_format_heights", [])
        out.append(r)

    return out


def iterate_probe(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return probe_records(list(records))
