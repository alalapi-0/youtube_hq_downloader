from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .scorer import score_record
from .utils import load_yaml_mapping


def _truthy(v: Any) -> bool:
    return bool(v) and str(v).lower() not in ("false", "0", "no")


def resolve_path(project_root: Path, rel: str) -> Path:
    p = Path(rel)
    return p.resolve() if p.is_absolute() else (project_root / p).resolve()


def load_channel_whitelist(path: Path) -> Tuple[set[str], List[str]]:
    data = load_yaml_mapping(path)
    ids = set(str(x).strip() for x in (data.get("channel_ids") or []) if str(x).strip())
    substr = [str(s).strip().lower() for s in (data.get("channel_title_contains") or []) if str(s).strip()]
    return ids, substr


def channel_matches_whitelist(
    channel_id: str,
    channel_title: str,
    ids: set[str],
    title_substrings: List[str],
) -> bool:
    if channel_id and channel_id in ids:
        return True
    low = (channel_title or "").lower()
    return any(bool(s and s in low) for s in title_substrings)


def apply_filters(
    records: Iterable[Dict[str, Any]],
    rules_path: Path,
    project_root: Path,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    cfg = load_yaml_mapping(rules_path)

    nk = cfg.get("negative_keyword_sources") or {}
    neg_rel = nk.get("negative_keywords_file") or "config/negative_keywords.yaml"
    neg_yaml = resolve_path(project_root, str(neg_rel))
    nk_data = load_yaml_mapping(neg_yaml)

    ai_keywords = sorted({str(x).lower() for x in (nk_data.get("ai_content") or []) if str(x).strip()})
    lv_keywords = sorted({str(x).lower() for x in (nk_data.get("low_value_content") or []) if str(x).strip()})

    brand_rel = cfg.get("brand_positive_keywords_file") or "config/brand_whitelist.yaml"
    brand_yaml = resolve_path(project_root, str(brand_rel))
    brand_data = load_yaml_mapping(brand_yaml)
    pos_kw = sorted(
        {
            *[str(x).lower() for x in (brand_data.get("positive_keywords") or []) if str(x).strip()],
            *[str(x).lower() for x in (brand_data.get("brand_names") or []) if str(x).strip()],
        }
    )

    dur = cfg.get("duration") or {}
    mn, mx = dur.get("min_seconds"), dur.get("max_seconds")
    min_seconds = int(mn) if mn not in (None, "") else None
    max_seconds = int(mx) if mx not in (None, "") else None

    exclude_shorts = _truthy((cfg.get("shorts") or {}).get("exclude", True))
    exclude_live = _truthy((cfg.get("live") or {}).get("exclude", True))
    reject_ai = _truthy((cfg.get("ai_content") or {}).get("reject_on_keyword_hit", True))
    reject_low = _truthy((cfg.get("low_value_content") or {}).get("reject_on_keyword_hit", True))

    res = cfg.get("resolution") or {}
    require_4k = _truthy(res.get("require_4k", False))
    mh = res.get("min_height")
    min_height_i = int(mh) if mh not in (None, "") else None
    allow_text = _truthy(res.get("allow_text_evidence_when_format_unknown", True))
    allow_probe = _truthy(res.get("allow_format_probe", True))

    dedupe_cfg = cfg.get("dedupe") or {}
    dedupe_vid = _truthy(dedupe_cfg.get("by_video_id", True))
    max_per_channel = int(dedupe_cfg.get("max_per_channel") or 1)
    scope_key = str(dedupe_cfg.get("category_scope_field") or "category_subcategory")
    wl_rel = dedupe_cfg.get("channel_whitelist_file") or "config/channel_whitelist.yaml"
    wl_path = resolve_path(project_root, str(wl_rel))
    whitelist_max = int(dedupe_cfg.get("whitelist_max_per_channel", 3))
    wl_ids, wl_subs = load_channel_whitelist(wl_path) if wl_path.exists() else (set(), [])

    def scope_bucket(r: Dict[str, Any]) -> str:
        if scope_key == "category_only":
            return str(r.get("category") or "")
        if scope_key == "subcategory_only":
            return str(r.get("subcategory") or "")
        return f"{r.get('category') or ''}|{r.get('subcategory') or ''}"

    def resolution_threshold() -> int | None:
        if min_height_i is not None:
            return int(min_height_i)
        if require_4k:
            return 2160
        return None

    threshold = resolution_threshold()

    seen_video_ids: set[str] = set()
    accepted_channel_counts: Dict[str, int] = {}

    filtered: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    work = sorted(list(records), key=lambda r: float(r.get("filter_score") or 0.0), reverse=True)

    for row in work:
        r = dict(row)
        r["needs_resolution_check"] = False

        score_record(
            r,
            positive_keywords=pos_kw,
            negative_keywords_ai=ai_keywords,
            negative_keywords_low_value=lv_keywords,
        )

        codes: List[str] = []
        reasons: List[str] = []

        vid = str(r.get("video_id") or "")
        cid = str(r.get("channel_id") or "")
        ctitle = str(r.get("channel_title") or "")

        ds = r.get("duration_seconds")
        if min_seconds is not None and ds is not None:
            try:
                if float(ds) < float(min_seconds):
                    codes.append("duration_short")
                    reasons.append("duration_below_min")
            except (TypeError, ValueError):
                pass
        if max_seconds is not None and ds is not None:
            try:
                if float(ds) > float(max_seconds):
                    codes.append("duration_long")
                    reasons.append("duration_above_max")
            except (TypeError, ValueError):
                pass

        if exclude_shorts and r.get("is_shorts_candidate"):
            codes.append("shorts")
            reasons.append("exclude_shorts")
        if exclude_live and r.get("is_live"):
            codes.append("live")
            reasons.append("exclude_live")

        blob = f"{r.get('title') or ''}\n{r.get('description') or ''}".lower()
        if reject_ai:
            hits = [k for k in ai_keywords if k in blob]
            if hits:
                codes.append("ai_content_signal")
                reasons.append("ai_kw:" + ",".join(hits[:8]))
        if reject_low:
            hits = [k for k in lv_keywords if k in blob]
            if hits:
                codes.append("low_value_signal")
                reasons.append("lv_kw:" + ",".join(hits[:8]))

        if threshold is not None:
            ph = r.get("probe_max_height")
            probe_ok = r.get("format_probe_status") == "ok"

            probe_hits = False
            if probe_ok and allow_probe and ph not in (None, ""):
                try:
                    probe_hits = int(ph) >= int(threshold)
                except (TypeError, ValueError):
                    probe_hits = False

            text_claim = bool(r.get("resolution_text_evidence_4k"))
            probe_unavailable = not probe_ok

            passes_res = False
            needs_check = False

            if probe_hits:
                passes_res = True
            elif allow_text and text_claim and probe_unavailable:
                passes_res = True
                needs_check = True
            elif allow_text and text_claim and probe_ok and not probe_hits:
                passes_res = True
                needs_check = True

            r["needs_resolution_check"] = needs_check

            if not passes_res:
                codes.append("resolution_gate")
                reasons.append("resolution_not_met")

        if dedupe_vid and vid:
            if vid in seen_video_ids:
                codes.append("dedupe_video_id")
                reasons.append("duplicate_video")

        cap = whitelist_max if channel_matches_whitelist(cid, ctitle, wl_ids, wl_subs) else max_per_channel

        bucket = f"{scope_bucket(r)}::{cid}"
        used = accepted_channel_counts.get(bucket, 0)
        rank_if_accepted = used + 1

        channel_blocked = False
        if cid and cap > 0 and used >= cap:
            codes.append("channel_cap")
            reasons.append(f"channel_cap_bucket={bucket}:used={used}>={cap}")
            channel_blocked = True

        if not codes:
            if vid:
                seen_video_ids.add(vid)
            if cid:
                accepted_channel_counts[bucket] = used + 1
                r["dedupe_channel_rank_in_scope"] = rank_if_accepted
            r["hard_filter_pass"] = True
            r["rejection_codes"] = []
            r["rejection_reason"] = ""
            filtered.append(r)
        else:
            r["hard_filter_pass"] = False
            if channel_blocked and "channel_cap" in codes:
                r["dedupe_channel_rank_in_scope"] = None
            r["rejection_codes"] = codes
            r["rejection_reason"] = "; ".join(reasons)
            rejected.append(r)

    return filtered, rejected
