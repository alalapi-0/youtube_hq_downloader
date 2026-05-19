from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Tuple

import isodate

DEFAULT_HARD_CONSTRAINTS = {
    "require_4k": True,
    "min_height": 2160,
    "max_duration_seconds": 60,
    "published_within_days": 730,
    "reject_if_missing_4k_evidence": True,
    "reject_if_missing_duration": True,
    "reject_if_missing_publish_date": True,
    "require_commercial_feature": True,
    "reject_if_missing_commercial_feature": True,
    "commercial_feature_terms": [
        "this video contains an advertisement",
        "advertisement",
        "commercial",
        "campaign",
        "brand film",
        "product film",
        "hero film",
        "agency:",
        "creative director",
        "art director",
        "agency producer",
        "production company:",
        "director:",
        "producer:",
        "dop",
        "dp:",
        "editor:",
        "colorist",
        "post:",
        "vfx",
        "packshot",
        "still life",
        "hero product",
    ],
}

FOUR_K_RE = re.compile(r"\b(?:4k|2160p|uhd|ultra\s*hd|3840\s*x\s*2160|4096\s*x\s*2160)\b", re.I)
LOW_HEIGHT_RE = re.compile(r"\b(?:360p|480p|540p|720p|1080p|1440p|2k)\b", re.I)
SEASON_CAMPAIGN_RE = re.compile(
    r"\b(?:(?:fall|spring|summer|winter|holiday)\s+20\d{2}\s+campaign|(?:fw|ss)\s*20\d{2})\b",
    re.I,
)


def hard_constraints_from_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    block = cfg.get("hard_constraints") if isinstance(cfg.get("hard_constraints"), dict) else {}
    out = dict(DEFAULT_HARD_CONSTRAINTS)
    out.update(block)
    out["commercial_feature_terms"] = _normalize_commercial_terms(out.get("commercial_feature_terms") or [])
    return out


def _normalize_commercial_terms(values: Iterable[Any]) -> List[str]:
    terms: List[str] = []
    for value in values:
        if isinstance(value, dict):
            for key, nested in value.items():
                text = f"{key}:" if nested is None else f"{key}: {nested}"
                terms.append(text)
            continue
        text = str(value or "").strip()
        if text:
            terms.append(text)
    return terms


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
        hours = int(clock.group(1) or 0)
        minutes = int(clock.group(2))
        seconds = int(clock.group(3))
        return hours * 3600 + minutes * 60 + seconds
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


def _row_duration(row: Dict[str, Any]) -> int | None:
    for key in ("duration_seconds", "duration", "duration_text", "length", "runtime"):
        parsed = parse_duration_seconds(row.get(key))
        if parsed is not None:
            return parsed
    haystack = " ".join(str(row.get(k) or "") for k in ("title", "description", "llm_notes", "duration_evidence"))
    return parse_duration_seconds(haystack)


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


def _row_publish_date(row: Dict[str, Any]) -> date | None:
    for key in ("published_at", "publish_date", "published_date", "upload_date", "date", "created_at"):
        parsed = parse_publish_date(row.get(key))
        if parsed is not None:
            return parsed
    haystack = " ".join(str(row.get(k) or "") for k in ("description", "llm_notes", "date_evidence"))
    return parse_publish_date(haystack)


def _height_from_row(row: Dict[str, Any]) -> int | None:
    values = [
        row.get("max_format_height"),
        row.get("resolution_height"),
        row.get("height"),
        row.get("max_height"),
        row.get("probe_max_height"),
    ]
    for item in row.get("available_format_heights") or []:
        values.append(item)
    parsed = [_as_int(v) for v in values]
    parsed = [v for v in parsed if v is not None]
    return max(parsed) if parsed else None


def _resolution_text(row: Dict[str, Any]) -> str:
    fields = (
        "title",
        "description",
        "description_snippet",
        "llm_notes",
        "resolution",
        "resolution_text",
        "resolution_evidence",
        "quality_evidence",
    )
    return "\n".join(str(row.get(k) or "") for k in fields)


def _check_resolution(row: Dict[str, Any], constraints: Dict[str, Any]) -> List[str]:
    if not constraints.get("require_4k", True):
        return []
    min_height = int(constraints.get("min_height") or 2160)
    height = _height_from_row(row)
    text = _resolution_text(row)
    has_text_4k = bool(FOUR_K_RE.search(text))
    low_text_without_4k = bool(LOW_HEIGHT_RE.search(text)) and not has_text_4k
    if height is not None:
        row["max_format_height"] = height
        row["has_2160p_format"] = height >= min_height
        if height < min_height:
            return ["not_4k"]
        return []
    if row.get("has_2160p_format") is True or has_text_4k:
        row["has_2160p_format"] = True
        return []
    if low_text_without_4k:
        return ["not_4k"]
    if constraints.get("reject_if_missing_4k_evidence", True):
        return ["missing_4k_evidence"]
    return []


def _check_duration(row: Dict[str, Any], constraints: Dict[str, Any]) -> List[str]:
    limit = int(constraints.get("max_duration_seconds") or 60)
    duration = _row_duration(row)
    if duration is None:
        return ["missing_duration"] if constraints.get("reject_if_missing_duration", True) else []
    row["duration_seconds"] = duration
    return ["duration_too_long"] if duration > limit else []


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _check_publish_date(row: Dict[str, Any], constraints: Dict[str, Any], *, today: date | None = None) -> List[str]:
    max_days = int(constraints.get("published_within_days") or 730)
    published = _row_publish_date(row)
    if published is None:
        return ["missing_publish_date"] if constraints.get("reject_if_missing_publish_date", True) else []
    row["published_at"] = published.isoformat()
    cutoff = (today or _today_utc()) - timedelta(days=max_days)
    return ["published_too_old"] if published < cutoff else []


def _commercial_text(row: Dict[str, Any]) -> str:
    values: List[str] = []
    for key in (
        "title",
        "description",
        "description_snippet",
        "llm_notes",
        "query_used",
        "brand",
        "channel_title",
        "commercial_feature_evidence",
        "advertisement_evidence",
    ):
        values.append(str(row.get(key) or ""))
    oembed = row.get("vimeo_oembed")
    if isinstance(oembed, dict):
        values.extend(str(oembed.get(key) or "") for key in ("title", "author_name"))
    return "\n".join(values)


def _commercial_feature_hits(row: Dict[str, Any], constraints: Dict[str, Any]) -> List[str]:
    text = _commercial_text(row).lower()
    hits: List[str] = []
    for term in constraints.get("commercial_feature_terms") or DEFAULT_HARD_CONSTRAINTS["commercial_feature_terms"]:
        needle = str(term or "").strip().lower()
        if needle and needle in text:
            hits.append(needle)
    if SEASON_CAMPAIGN_RE.search(text):
        hits.append("season_campaign")
    if row.get("contains_advertisement") is True or row.get("is_advertisement") is True or row.get("advertisement_disclosure") is True:
        hits.append("advertisement_disclosure")
    seen: set[str] = set()
    unique: List[str] = []
    for hit in hits:
        if hit in seen:
            continue
        seen.add(hit)
        unique.append(hit)
    return unique


def _check_commercial_feature(row: Dict[str, Any], constraints: Dict[str, Any]) -> List[str]:
    if not constraints.get("require_commercial_feature", True):
        return []
    hits = _commercial_feature_hits(row, constraints)
    if hits:
        row["commercial_feature_evidence"] = row.get("commercial_feature_evidence") or ", ".join(hits[:8])
        row["commercial_feature_passed"] = True
        return []
    row["commercial_feature_passed"] = False
    if constraints.get("reject_if_missing_commercial_feature", True):
        return ["missing_commercial_feature"]
    return []


def apply_hard_constraints(
    rows: Iterable[Dict[str, Any]],
    constraints: Dict[str, Any],
    *,
    today: date | None = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    kept: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    reason_counts: Dict[str, int] = {}
    total = 0
    for record in rows:
        total += 1
        row = dict(record)
        reasons: List[str] = []
        reasons.extend(_check_resolution(row, constraints))
        reasons.extend(_check_duration(row, constraints))
        reasons.extend(_check_publish_date(row, constraints, today=today))
        reasons.extend(_check_commercial_feature(row, constraints))
        if reasons:
            uniq = sorted(set(reasons))
            row["hard_constraint_passed"] = False
            row["hard_constraint_reject_reasons"] = uniq
            row["rejection_stage"] = "hard_constraints"
            rejected.append(row)
            for reason in uniq:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            continue
        row["hard_constraint_passed"] = True
        row["hard_constraint_reject_reasons"] = []
        kept.append(row)
    return kept, rejected, {"total": total, "kept": len(kept), "rejected": len(rejected), **reason_counts}
