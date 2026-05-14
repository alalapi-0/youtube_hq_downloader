from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Dict, Iterable, List, Optional


def _yt_dlp_path() -> Optional[str]:
    return shutil.which("yt-dlp")


def _parse_max_height_from_json(info: Dict[str, Any]) -> tuple[Optional[int], bool]:
    max_h = None
    for fmt in info.get("formats") or []:
        h = fmt.get("height")
        try:
            if h is not None:
                hi = int(h)
                max_h = hi if max_h is None else max(max_h, hi)
        except (TypeError, ValueError):
            continue
    has_2160 = bool(max_h and max_h >= 2160) or ("2160p" in str(info.get("format") or ""))
    return max_h, has_2160


def probe_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if os.environ.get("SKIP_FORMAT_PROBE", "").strip():
        out: List[Dict[str, Any]] = []
        for r in records:
            row = dict(r)
            row["format_probe_status"] = "skipped"
            row.setdefault("probe_max_height", None)
            row.setdefault("probe_confirmed_4k", False)
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
                r["format_probe_status"] = "error"
                r["probe_confirmed_4k"] = False
            else:
                info = json.loads(proc.stdout)
                mx, ok = _parse_max_height_from_json(info)
                r["probe_max_height"] = mx
                r["probe_confirmed_4k"] = ok
                r["format_probe_status"] = "ok"
        except subprocess.TimeoutExpired:
            r["format_probe_status"] = "timeout_error"
            r.setdefault("probe_max_height", None)
            r["probe_confirmed_4k"] = False
        except Exception:
            r["format_probe_status"] = "error"
            r.setdefault("probe_max_height", None)
            r["probe_confirmed_4k"] = False
        out.append(r)

    return out


def iterate_probe(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return probe_records(list(records))
