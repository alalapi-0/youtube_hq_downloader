from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from ..utils import extract_video_id, read_jsonl
from .paths import output_root


def canonical_url_key(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    video_id = extract_video_id(raw)
    if video_id:
        return f"youtube:{video_id}"
    cleaned = raw.split("#", 1)[0].rstrip("/")
    return cleaned.lower()


def _row_url(row: Dict[str, Any]) -> str:
    return str(row.get("canonical_url") or row.get("video_url") or row.get("url") or "")


def prior_url_keys(*, exclude_task_dir: Path | None = None) -> set[str]:
    keys: set[str] = set()
    root = output_root()
    if not root.exists():
        return keys
    for task in root.glob("task_*"):
        if exclude_task_dir and task.resolve() == exclude_task_dir.resolve():
            continue
        for name in ("final_candidates.jsonl", "candidates_raw.jsonl", "collected_urls.jsonl"):
            path = task / name
            if not path.exists():
                continue
            for row in read_jsonl(path):
                key = canonical_url_key(_row_url(row))
                if key:
                    keys.add(key)
    return keys


def dedupe_records(records: Iterable[Dict[str, Any]], *, exclude_task_dir: Path | None = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    prior = prior_url_keys(exclude_task_dir=exclude_task_dir)
    seen: set[str] = set()
    unique: List[Dict[str, Any]] = []
    duplicates: List[Dict[str, Any]] = []
    total = 0
    for record in records:
        total += 1
        row = dict(record)
        key = canonical_url_key(_row_url(row))
        row["dedupe_key"] = key
        if not key:
            row["duplicate_reason"] = "missing_url"
            duplicates.append(row)
            continue
        if key in seen:
            row["duplicate_reason"] = "duplicate_in_current_task"
            duplicates.append(row)
            continue
        if key in prior:
            row["duplicate_reason"] = "duplicate_in_previous_tasks"
            duplicates.append(row)
            continue
        seen.add(key)
        row["duplicate_reason"] = ""
        unique.append(row)
    return unique, duplicates, {"total": total, "unique": len(unique), "duplicates": len(duplicates), "prior_keys": len(prior)}
