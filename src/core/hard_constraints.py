from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Tuple

import isodate


DEFAULT_FILTERS = {
    "require_4k": True,
    "min_height": 2160,
    "max_duration_seconds": 60,
    "published_within_days": 730,
    "reject_if_missing_4k_evidence": True,
    "reject_if_missing_duration": True,
    "reject_if_missing_publish_date": True,
    "negative_keywords": [
        "ai generated",
        "review",
        "unboxing",
        "vlog",
        "behind the scenes",
        "compilation",
        "showreel",
        "reupload",
        "fanmade",
        "interview",
        "tutorial",
    ],
}

FOUR_K_RE = re.compile(r"\b(?:4k|2160p|uhd|ultra\s*hd|3840\s*[x×]\s*2160|4096\s*[x×]\s*2160)\b", re.I)
LOW_HEIGHT_RE = re.compile(r"\b(?:360p|480p|540p|720p|1080p|1440p|2k)\b", re.I)


def hard_constraints_from_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    block = cfg.get("filters") if isinstance(cfg.get("filters"), dict) else {}
    out = dict(DEFAULT_FILTERS)
    out.update(block)
    return out


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def parse_duration_seconds(value: Any) -> int | None:
    direct = _as_int(value)
    if direct is not None:
        return direct
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text.startswith("pt"):
        try:
            return int(isodate.parse_duration(text.upper()).total_seconds())
        except Exception:
            pass
    clock = re.search(r"\b(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\b", text)
    if clock:
        return int(clock.group(1) or 0) * 3600 + int(clock.group(2)) * 60 + int(clock.group(3))
    short_clock = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if short_clock:
        return int(short_clock.group(1)) * 60 + int(short_clock.group(2))
    minutes = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:minutes?|mins?|min)\b", text)
    if minutes:
        return int(float(minutes.group(1)) * 60)
    seconds = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|sec|s)\b", text)
    if seconds:
        return int(float(seconds.group(1)))
    return None


def parse_publish_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y%m%d"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            pass
    hit = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", normalized)
    if hit:
        try:
            return date(int(hit.group(1)), int(hit.group(2)), int(hit.group(3)))
        except ValueError:
            return None
    return None


def _height_from_row(row: Dict[str, Any]) -> int | None:
    values = [
        row.get("max_format_height"),
        row.get("height"),
        row.get("resolution_height"),
        row.get("probe_max_height"),
    ]
    values.extend(row.get("available_format_heights") or [])
    parsed = [_as_int(v) for v in values]
    parsed = [v for v in parsed if v is not None]
    return max(parsed) if parsed else None


def _row_duration(row: Dict[str, Any]) -> int | None:
    for key in ("duration_seconds", "duration", "duration_string", "duration_text"):
        parsed = parse_duration_seconds(row.get(key))
        if parsed is not None:
            return parsed
    return None


def _row_publish_date(row: Dict[str, Any]) -> date | None:
    for key in ("published_at", "upload_date", "timestamp", "release_date"):
        value = row.get(key)
        if key == "timestamp":
            ts = _as_int(value)
            if ts is not None:
                return datetime.fromtimestamp(ts, timezone.utc).date()
        parsed = parse_publish_date(value)
        if parsed is not None:
            return parsed
    return None


def _check_resolution(row: Dict[str, Any], filters: Dict[str, Any]) -> List[str]:
    if not filters.get("require_4k", True):
        return []
    min_height = int(filters.get("min_height") or 2160)
    height = _height_from_row(row)
    text = "\n".join(str(row.get(k) or "") for k in ("title", "description", "resolution_evidence"))
    has_text_4k = bool(FOUR_K_RE.search(text))
    if height is not None:
        row["max_format_height"] = height
        row["has_2160p_format"] = height >= min_height
        return [] if height >= min_height else ["not_4k"]
    if row.get("has_2160p_format") is True or has_text_4k:
        row["has_2160p_format"] = True
        return []
    if LOW_HEIGHT_RE.search(text):
        return ["not_4k"]
    return ["missing_4k_evidence"] if filters.get("reject_if_missing_4k_evidence", True) else []


def _check_duration(row: Dict[str, Any], filters: Dict[str, Any]) -> List[str]:
    limit = int(filters.get("max_duration_seconds") or 60)
    duration = _row_duration(row)
    if duration is None:
        return ["missing_duration"] if filters.get("reject_if_missing_duration", True) else []
    row["duration_seconds"] = duration
    return ["duration_too_long"] if duration > limit else []


def _check_publish_date(row: Dict[str, Any], filters: Dict[str, Any], *, today: date | None = None) -> List[str]:
    max_days = int(filters.get("published_within_days") or 730)
    published = _row_publish_date(row)
    if published is None:
        return ["missing_publish_date"] if filters.get("reject_if_missing_publish_date", True) else []
    row["published_at"] = published.isoformat()
    cutoff = (today or datetime.now(timezone.utc).date()) - timedelta(days=max_days)
    return ["published_too_old"] if published < cutoff else []


def _check_negative_keywords(row: Dict[str, Any], filters: Dict[str, Any]) -> List[str]:
    text = "\n".join(str(row.get(k) or "") for k in ("title", "description", "channel_title")).lower()
    hits = []
    for keyword in filters.get("negative_keywords") or []:
        needle = str(keyword or "").strip().lower()
        if needle and needle in text:
            hits.append(f"negative_keyword:{needle}")
    return hits


def apply_hard_constraints(
    rows: Iterable[Dict[str, Any]],
    filters: Dict[str, Any],
    *,
    today: date | None = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    kept: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    stats: Dict[str, int] = {}
    total = 0
    for record in rows:
        total += 1
        row = dict(record)
        reasons: List[str] = []
        reasons.extend(_check_resolution(row, filters))
        reasons.extend(_check_duration(row, filters))
        reasons.extend(_check_publish_date(row, filters, today=today))
        reasons.extend(_check_negative_keywords(row, filters))
        if reasons:
            uniq = sorted(set(reasons))
            row["hard_constraint_passed"] = False
            row["hard_constraint_reject_reasons"] = uniq
            row["rejection_stage"] = "hard_constraints"
            rejected.append(row)
            for reason in uniq:
                stats[reason] = stats.get(reason, 0) + 1
            continue
        row["hard_constraint_passed"] = True
        row["hard_constraint_reject_reasons"] = []
        kept.append(row)
    return kept, rejected, {"total": total, "kept": len(kept), "rejected": len(rejected), **stats}
