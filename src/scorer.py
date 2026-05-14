from __future__ import annotations

from typing import Dict, List, Sequence, Tuple


def score_record(
    record: Dict,
    *,
    positive_keywords: Sequence[str],
    negative_keywords_ai: Sequence[str],
    negative_keywords_low_value: Sequence[str],
) -> Tuple[float, List[str], List[str]]:
    text = f"{record.get('title') or ''}\n{record.get('description') or ''}".lower()
    pos_hits = [kw for kw in positive_keywords if kw and kw.lower() in text]
    neg_ai = [kw for kw in negative_keywords_ai if kw and kw.lower() in text]
    neg_lv = [kw for kw in negative_keywords_low_value if kw and kw.lower() in text]

    score = 0.0
    score += 2.5 * len(pos_hits)
    score -= 3.5 * len(neg_ai)
    score -= 2.0 * len(neg_lv)

    merged_neg = sorted(set([*neg_ai, *neg_lv]))

    record["positive_keyword_hits"] = pos_hits
    record["negative_keyword_hits"] = merged_neg
    record["filter_score"] = float(score)

    return float(score), pos_hits, merged_neg
