from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Tuple

import isodate


DEFAULT_FILTERS = {
    "require_4k": True,
    "min_height": 2160,
    "min_duration_seconds": 0,
    "max_duration_seconds": 60,
    "published_within_days": 730,
    "reject_if_missing_4k_evidence": True,
    "reject_if_missing_duration": True,
    "reject_if_missing_publish_date": True,
    "require_professional_campaign": False,
    "reject_if_missing_professional_signal": True,
    "require_specific_brand_product_ad": False,
    "reject_if_missing_brand_product_signal": True,
    "required_topic_keywords": [],
    "topic_negative_keywords": [],
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
    "professional_positive_keywords": [
        "campaign film",
        "campaign video",
        "campaign short film",
        "commercial",
        "advertisement",
        "advertising",
        "ad film",
        "brand film",
        "brand campaign",
        "launch film",
        "product film",
        "fashion film",
        "official campaign",
        "global campaign",
        "directed by",
        "director's cut",
        "creative director",
        "director of photography",
        "production company",
        "production house",
        "produced by",
        "agency",
        "client",
        "cinematographer",
        "dop",
        "tvc",
        "spot",
    ],
    "professional_negative_keywords": [
        "ai generated",
        "ai-generated",
        "artificial intelligence",
        "midjourney",
        "runway ai",
        "sora",
        "stable diffusion",
        "vlog",
        "reaction",
        "review",
        "tutorial",
        "behind the scenes",
        "behind-the-scenes",
        "bts",
        "making of",
        "compilation",
        "showreel",
        "reel",
        "fanmade",
        "fan made",
        "fan edit",
        "student film",
        "homemade",
        "shot at home",
        "created at home",
        "home studio",
        "camera test",
        "test footage",
        "travel video",
        "wedding",
        "lyrics",
        "crowdfunding",
        "crowdfund",
        "indiegogo",
        "kickstarter",
        "gofundme",
        "gofund.me",
        "seed&spark",
        "seed and spark",
        "seedandspark",
        "fundraiser",
        "fundraising",
        "funding campaign",
        "donate",
        "donation",
        "greenlit",
        "givebutter",
        "support the short film",
        "director's statement",
        "director statement",
        "director profile",
        "meet the director",
        "film festival",
        "festival trailer",
        "campaign video for a film",
        "feature film promo",
        "election campaign",
        "name a seat",
        "anti-drug movement",
        "grad film",
        "teaser",
        "trailer",
        "gearing up",
    ],
    "brand_product_negative_keywords": [
        "behind the scenes",
        "behind-the-scenes",
        "bts",
        "making of",
        "tutorial",
        "workshop",
        "how to",
        "livestream",
        "playlist",
        "news",
        "showreel",
        "reel",
        "portfolio",
        "student film",
        "short film",
        "experimental movie",
        "music video",
        "cover shoot",
        "commercialphoto",
        "commercial photo",
        "photography journey",
        "economics class",
        "video production",
        "content by",
        "social & ad-ready",
        "commercial video shoot",
        "full-service video production",
        "food video ad for brand",
        "cinematic vegetarian pizza",
        "restaurant & food content",
        "restaurant and food content",
        "food commercial with",
        "fast food commercial with",
    ],
}

FOUR_K_RE = re.compile(r"\b(?:4k|2160p|uhd|ultra\s*hd|3840\s*[x×]\s*2160|4096\s*[x×]\s*2160)\b", re.I)
LOW_HEIGHT_RE = re.compile(r"\b(?:360p|480p|540p|720p|1080p|1440p|2k)\b", re.I)
BRAND_LABEL_RE = re.compile(
    r"\b(?:client|brand|product)\s*[:：=|-]\s*([^\n\r|,;#@]{2,80})",
    re.I,
)
FOR_BRAND_RE = re.compile(
    r"\b(?:created\s+for|produced\s+for|shot\s+for|made\s+for|film\s+for|commercial\s+for|ad\s+for|for)\s+(@?[\w][\w&'. -]{2,80})",
    re.I,
)
AD_MARKER_RE = re.compile(
    r"\b(?:commercial|advertisement|ad\s*film|ad\b|tvc|brand\s*film|product\s*(?:video|film|commercial)|campaign|spot)\b",
    re.I,
)
GENERIC_SUBJECT_WORDS = {
    "a",
    "ad",
    "advertisement",
    "advertising",
    "agency",
    "b",
    "beauty",
    "brand",
    "broll",
    "commercial",
    "content",
    "creative",
    "demo",
    "digital",
    "director",
    "film",
    "food",
    "for",
    "full",
    "generic",
    "high",
    "house",
    "in",
    "lifestyle",
    "media",
    "photo",
    "photography",
    "product",
    "production",
    "project",
    "promo",
    "ready",
    "restaurant",
    "service",
    "services",
    "shoot",
    "shot",
    "social",
    "spec",
    "studio",
    "the",
    "video",
    "videography",
    "with",
}
GENERIC_TITLE_PHRASES = {
    "cinematic vegetarian pizza",
    "food commercial",
    "food video ad",
    "full-service video production",
    "restaurant and food content",
    "restaurant & food content",
    "commercial video shoot",
    "full-service video production",
    "food video ad for brand",
    "cinematic vegetarian pizza",
    "restaurant & food content",
    "restaurant and food content",
    "food commercial with",
    "fast food commercial with",
}
BRAND_PRODUCT_HARD_NEGATIVES = {
    "behind the scenes",
    "behind-the-scenes",
    "bts",
    "making of",
    "tutorial",
    "workshop",
    "how to",
    "livestream",
    "playlist",
    "news",
    "showreel",
    "reel",
    "portfolio",
    "student film",
    "short film",
    "experimental movie",
    "music video",
    "cover shoot",
    "commercialphoto",
    "commercial photo",
    "photography journey",
    "economics class",
    "content by",
    "social & ad-ready",
    "full-service video production",
    "food video ad for brand",
    "cinematic vegetarian pizza",
    "restaurant & food content",
    "restaurant and food content",
    "food commercial with",
    "fast food commercial with",
}


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
    floor = int(filters.get("min_duration_seconds") or 0)
    limit = int(filters.get("max_duration_seconds") or 60)
    duration = _row_duration(row)
    if duration is None:
        return ["missing_duration"] if filters.get("reject_if_missing_duration", True) else []
    row["duration_seconds"] = duration
    reasons: List[str] = []
    if floor and duration < floor:
        reasons.append("duration_too_short")
    if duration > limit:
        reasons.append("duration_too_long")
    return reasons


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


def _keyword_hits(text: str, keywords: Iterable[Any]) -> List[str]:
    haystack = text.lower()
    hits: List[str] = []
    for keyword in keywords:
        needle = str(keyword or "").strip().lower()
        if needle and needle in haystack:
            hits.append(needle)
    return sorted(set(hits))


def _tokenize_subject(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'&.-]*", text or "")


def _normalize_phrase(text: str) -> str:
    return " ".join((text or "").lower().replace("|", " ").split())


def _specific_subject_phrase(text: str) -> bool:
    phrase = re.sub(r"\([^)]*\)", " ", str(text or ""))
    phrase = re.sub(r"\b(?:4k|8k|uhd|hd|official|new|latest|\d{1,3}\s*sec(?:onds?)?|20\d{2})\b", " ", phrase, flags=re.I)
    normalized = _normalize_phrase(phrase)
    if not normalized or normalized in GENERIC_TITLE_PHRASES:
        return False
    if any(p in normalized for p in GENERIC_TITLE_PHRASES):
        return False
    tokens = _tokenize_subject(phrase)
    meaningful = [
        token
        for token in tokens
        if len(token.strip("'&.-")) >= 2 and token.lower().strip("'&.-") not in GENERIC_SUBJECT_WORDS
    ]
    if len(meaningful) >= 2:
        return True
    if meaningful:
        token = meaningful[0]
        if len(token) >= 3:
            return True
        if token.isupper() and len(token) >= 3:
            return True
        if any(ch.isdigit() for ch in token) and len(token) >= 3:
            return True
        if any(ch in token for ch in ("'", "&", ".")) and len(token) >= 3:
            return True
    return False


def _title_subject_candidates(title: str) -> List[str]:
    clean = re.sub(r"\s+", " ", str(title or "")).strip()
    if not clean:
        return []
    candidates: List[str] = []
    parts = [p.strip() for p in re.split(r"\s+[|–—-]\s+|\s*\|\s*", clean) if p.strip()]
    candidates.extend(parts[:3])
    marker = AD_MARKER_RE.search(clean)
    if marker:
        before = clean[: marker.start()].strip(" -|–—:")
        after = clean[marker.end() :].strip(" -|–—:")
        if before:
            candidates.append(before)
        if after:
            candidates.append(after)
    return candidates


def _brand_product_text(row: Dict[str, Any]) -> str:
    tags = row.get("tags") if isinstance(row.get("tags"), list) else []
    return "\n".join(
        [
            str(row.get("title") or ""),
            str(row.get("description") or ""),
            str(row.get("channel_title") or ""),
            "\n".join(str(x) for x in tags),
        ]
    )


def _brand_product_signal_hits(row: Dict[str, Any]) -> List[str]:
    title = str(row.get("title") or "")
    text = _brand_product_text(row)
    hits: List[str] = []
    for regex, label in ((BRAND_LABEL_RE, "label"), (FOR_BRAND_RE, "for")):
        for match in regex.finditer(text):
            phrase = match.group(1).strip()
            if _specific_subject_phrase(phrase):
                hits.append(f"{label}:{phrase[:80]}")
    if AD_MARKER_RE.search(title):
        for phrase in _title_subject_candidates(title):
            if _specific_subject_phrase(phrase):
                hits.append(f"title:{phrase[:80]}")
    if not hits:
        desc = str(row.get("description") or "")
        for phrase in _title_subject_candidates(title):
            if _specific_subject_phrase(phrase) and re.search(
                r"\b(?:client|brand|product|commercial|ad|tvc|campaign|agency|production\s+house|food\s+stylist)\b",
                desc,
                re.I,
            ):
                hits.append(f"title_context:{phrase[:80]}")
    return sorted(set(hits))


def _check_specific_brand_product_ad(row: Dict[str, Any], filters: Dict[str, Any]) -> List[str]:
    if not filters.get("require_specific_brand_product_ad", False):
        return []
    text = _brand_product_text(row)
    title_channel_text = "\n".join(str(row.get(k) or "") for k in ("title", "channel_title"))
    negative_hits = _keyword_hits(text, filters.get("brand_product_negative_keywords") or [])
    signal_hits = _brand_product_signal_hits(row)
    row["brand_product_signal_hits"] = signal_hits
    title_negative_hits = _keyword_hits(title_channel_text, filters.get("brand_product_negative_keywords") or [])
    hard_negative_hits = [hit for hit in title_negative_hits if hit in BRAND_PRODUCT_HARD_NEGATIVES]
    if hard_negative_hits:
        row["brand_product_reject_hits"] = hard_negative_hits
        return [f"not_brand_product_ad:{hit}" for hit in hard_negative_hits]
    if negative_hits and not signal_hits:
        row["brand_product_reject_hits"] = negative_hits
        return [f"not_brand_product_ad:{hit}" for hit in negative_hits]
    if signal_hits:
        return []
    if filters.get("reject_if_missing_brand_product_signal", True):
        return ["missing_specific_brand_product_signal"]
    return []


def _professional_text(row: Dict[str, Any]) -> str:
    tags = row.get("tags") if isinstance(row.get("tags"), list) else []
    return "\n".join(
        [
            str(row.get("title") or ""),
            str(row.get("description") or ""),
            str(row.get("channel_title") or ""),
            str(row.get("category") or ""),
            str(row.get("subcategory") or ""),
            "\n".join(str(x) for x in tags),
        ]
    )


def _check_required_topic_keywords(row: Dict[str, Any], filters: Dict[str, Any]) -> List[str]:
    text = _professional_text(row)
    negative_hits = _keyword_hits(text, filters.get("topic_negative_keywords") or [])
    if negative_hits:
        row["topic_reject_hits"] = negative_hits
        return [f"topic_negative_keyword:{hit}" for hit in negative_hits]
    required = [str(x or "").strip().lower() for x in (filters.get("required_topic_keywords") or []) if str(x or "").strip()]
    if not required:
        return []
    hits = _keyword_hits(text, required)
    row["topic_signal_hits"] = hits
    if hits:
        return []
    return ["missing_required_topic_keyword"]


def _check_professional_campaign(row: Dict[str, Any], filters: Dict[str, Any]) -> List[str]:
    if not filters.get("require_professional_campaign", False):
        return []
    text = _professional_text(row)
    negative_hits = _keyword_hits(text, filters.get("professional_negative_keywords") or [])
    if negative_hits:
        row["professional_reject_hits"] = negative_hits
        return [f"non_professional_keyword:{hit}" for hit in negative_hits]
    positive_hits = _keyword_hits(text, filters.get("professional_positive_keywords") or [])
    row["professional_signal_hits"] = positive_hits
    if positive_hits:
        return []
    if filters.get("reject_if_missing_professional_signal", True):
        return ["missing_professional_campaign_signal"]
    return []


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
        reasons.extend(_check_professional_campaign(row, filters))
        reasons.extend(_check_specific_brand_product_ad(row, filters))
        reasons.extend(_check_required_topic_keywords(row, filters))
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
