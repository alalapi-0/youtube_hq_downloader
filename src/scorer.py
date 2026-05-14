from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple


def _truthy(v: Any) -> bool:
    return bool(v) and str(v).lower() not in ("false", "0", "no")


def score_record(
    record: Dict[str, Any],
    *,
    positive_keywords: Sequence[str],
    negative_keywords_ai: Sequence[str],
    negative_keywords_low_value: Sequence[str],
    high_risk_keywords: Sequence[str] | None = None,
    ranking_cfg: Mapping[str, Any] | None = None,
) -> Tuple[float, List[str], List[str]]:
    text = f"{record.get('title') or ''}\n{record.get('description') or ''}\n{record.get('tags') or ''}".lower()
    if isinstance(record.get("tags"), list):
        text += "\n" + " ".join(str(t) for t in record.get("tags") or [])

    pos_hits = [kw for kw in positive_keywords if kw and kw.lower() in text]
    neg_ai = [kw for kw in negative_keywords_ai if kw and kw.lower() in text]
    neg_lv = [kw for kw in negative_keywords_low_value if kw and kw.lower() in text]

    score = 0.0
    score += 2.5 * len(pos_hits)
    score -= 3.5 * len(neg_ai)
    score -= 2.0 * len(neg_lv)

    rk = ranking_cfg or {}
    motion_tokens = [str(x).lower() for x in (rk.get("high_motion_tokens") or []) if str(x).strip()]
    static_tokens = [str(x).lower() for x in (rk.get("static_product_tokens") or []) if str(x).strip()]

    likely_motion = any(tok in text for tok in motion_tokens)
    likely_static = any(tok in text for tok in static_tokens)

    record["likely_ugc_high_motion"] = bool(likely_motion)
    record["likely_static_product_visual"] = bool(likely_static)

    if _truthy(rk.get("penalize_high_motion_content", True)) and likely_motion:
        score -= 1.5
    if _truthy(rk.get("prefer_static_product_visuals", True)) and likely_static:
        score += 1.2

    hr = [kw for kw in (high_risk_keywords or []) if kw and kw.lower() in text]
    if hr:
        record["visual_quality_risk"] = "high"
    elif likely_motion and not likely_static:
        record["visual_quality_risk"] = "medium"
    else:
        record["visual_quality_risk"] = record.get("visual_quality_risk") or "low"

    merged_neg = sorted(set([*neg_ai, *neg_lv]))

    record["positive_keyword_hits"] = pos_hits
    record["negative_keyword_hits"] = merged_neg
    record["filter_score"] = float(score)

    # soft heuristics for downstream LLM / manual triage
    record["likely_ai_generated"] = bool(neg_ai)
    record["likely_low_value_noise"] = bool(neg_lv)
    record["likely_premium_ad"] = bool(len(pos_hits) >= 2 and not likely_motion)

    return float(score), pos_hits, merged_neg
