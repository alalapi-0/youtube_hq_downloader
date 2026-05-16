from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import yaml

from .utils import PROJECT_ROOT, load_yaml_mapping, read_jsonl


URL_ANALYSIS_CONFIG_PATH = PROJECT_ROOT / "config" / "url_analysis.yaml"


DEFAULT_POSITIVE_EXPANSIONS = [
    "product film",
    "studio",
    "packshot",
    "still life",
    "macro",
    "campaign film",
    "commercial",
]

REJECT_REASON_NEGATIVE_KEYWORDS = {
    "review_or_unboxing": ["review", "unboxing", "hands on", "first impression"],
    "behind_the_scenes": ["behind the scenes", "making of", "bts"],
    "live_or_full_show": ["full show", "live stream", "runway full show"],
    "fanmade_or_compilation": ["fanmade", "compilation", "edit"],
    "vlog_or_user_content": ["vlog", "daily", "user review"],
    "ai_generated": ["ai generated", "midjourney", "stable diffusion"],
    "not_advertisement": ["review", "news", "tutorial"],
    "not_product_focused": ["interview", "behind the scenes"],
    "not_4k": ["hd", "1080p only"],
}


def _feedback_cfg(path: Path | str = URL_ANALYSIS_CONFIG_PATH) -> Dict[str, Any]:
    raw = load_yaml_mapping(path) if Path(path).exists() else {}
    block = raw.get("feedback_analysis") if isinstance(raw.get("feedback_analysis"), dict) else {}
    return {
        "min_sample_size_for_strategy": int(block.get("min_sample_size_for_strategy") or 20),
        "high_pass_rate_threshold": float(block.get("high_pass_rate_threshold") or 0.4),
        "low_pass_rate_threshold": float(block.get("low_pass_rate_threshold") or 0.1),
    }


def _stats_items(stats: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    vals = stats.get(key) or []
    return vals if isinstance(vals, list) else []


def _high(stats: Dict[str, Any], key: str, threshold: float, min_total: int = 1) -> List[Dict[str, Any]]:
    return [
        x
        for x in _stats_items(stats, key)
        if int(x.get("total") or 0) >= min_total and float(x.get("pass_rate") or 0) >= threshold
    ]


def _low(stats: Dict[str, Any], key: str, threshold: float, min_total: int = 1) -> List[Dict[str, Any]]:
    return [
        x
        for x in _stats_items(stats, key)
        if int(x.get("total") or 0) >= min_total and float(x.get("pass_rate") or 0) <= threshold
    ]


def _unique(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for value in values:
        v = str(value or "").strip()
        if not v or v.lower() in seen:
            continue
        seen.add(v.lower())
        out.append(v)
    return out


def _queries_from_stats(stats: Dict[str, Any], *, threshold: float) -> List[str]:
    queries: List[str] = []
    for item in _high(stats, "by_query_used", threshold):
        key = str(item.get("key") or "").strip()
        if key and key != "unknown":
            queries.extend([p.strip() for p in key.split(";") if p.strip()])
    for item in stats.get("high_pass_keywords") or []:
        kw = str(item.get("keyword") or "").strip()
        if kw:
            queries.append(kw)
    return _unique(queries)


def _brands_from_stats(stats: Dict[str, Any], *, threshold: float) -> List[str]:
    brands: List[str] = []
    for item in _high(stats, "by_brand", threshold):
        key = str(item.get("key") or "").strip()
        if key and key != "unknown":
            brands.append(key)
    return _unique(brands)


def _channels_from_stats(stats: Dict[str, Any], *, threshold: float) -> List[str]:
    channels: List[str] = []
    for item in _high(stats, "by_channel_title", threshold, min_total=2):
        key = str(item.get("key") or "").strip()
        if key and key != "unknown":
            channels.append(key)
    return _unique(channels)


def _negative_keywords(stats: Dict[str, Any]) -> List[str]:
    words: List[str] = []
    for item in stats.get("low_pass_keywords") or []:
        kw = str(item.get("keyword") or "").strip()
        if kw:
            words.append(kw)
    for item in stats.get("common_reject_reasons") or []:
        label = str(item.get("label") or "")
        words.extend(REJECT_REASON_NEGATIVE_KEYWORDS.get(label, []))
    return _unique(words)


def _require_4k(stats: Dict[str, Any]) -> bool:
    for item in stats.get("common_reject_reasons") or []:
        if item.get("label") == "not_4k" and int(item.get("count") or 0) >= 2:
            return True
    for item in stats.get("metadata_risk_features") or []:
        if str(item.get("label") or "") == "max_format_height < 2160" and int(item.get("count") or 0) >= 2:
            return True
    return False


def _positive_expansions(stats: Dict[str, Any]) -> List[str]:
    features = {str(x.get("label") or "") for x in stats.get("common_pass_features") or []}
    out: List[str] = []
    if {"clean_studio_visual", "product_focused", "official_campaign"} & features:
        out.extend(DEFAULT_POSITIVE_EXPANSIONS)
    for item in stats.get("high_pass_keywords") or []:
        kw = str(item.get("keyword") or "").strip()
        if kw:
            out.append(kw)
    return _unique(out)


def build_rule_based_plan(stats: Dict[str, Any], reviewed_records: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    cfg = _feedback_cfg()
    summary = stats.get("summary") or {}
    high_th = cfg["high_pass_rate_threshold"]
    low_th = cfg["low_pass_rate_threshold"]
    sample_small = bool(summary.get("sample_size_too_small"))

    base_queries = _queries_from_stats(stats, threshold=high_th)
    expansions = _positive_expansions(stats)
    if not base_queries:
        base_queries = ["product film", "campaign film", "commercial"]
    keywords = _unique([*base_queries, *expansions])
    if sample_small:
        keywords = keywords[:6]

    brands = _brands_from_stats(stats, threshold=high_th)
    channels = _channels_from_stats(stats, threshold=high_th)
    negative = _negative_keywords(stats)
    require_4k = _require_4k(stats)

    plan = {
        "project": {"name": "feedback_next_search_plan"},
        "global_rules": {
            "max_results_per_keyword": 3 if sample_small else 8,
            "default_region_code": "US",
            "default_relevance_language": "en",
        },
        "duration": {
            "min_seconds": 30,
            "max_seconds": 7200,
        },
        "resolution": {
            "require_4k": bool(require_4k),
            "min_height": 2160 if require_4k else None,
            "allow_text_evidence_when_format_unknown": not require_4k,
            "allow_format_probe": True,
        },
        "positive_negative_keywords": {
            "negative_keywords_file": "config/negative_keywords.yaml",
            "brand_positive_keywords_file": "config/brand_whitelist.yaml",
            "suggested_negative_keywords": negative[:40],
            "suggested_positive_expansions": expansions[:40],
        },
        "tasks": [
            {
                "id": "feedback_rule_based_next_round",
                "category": "campaigns",
                "subcategory": "product",
                "keywords": keywords[:40],
                "brands": brands[:30],
                "preferred_channels": channels[:30],
                "max_results_per_keyword": 3 if sample_small else 8,
                "region_code": "US",
                "relevance_language": "en",
            }
        ],
        "_strategy_suggestions": {
            "sample_size_too_small": sample_small,
            "lower_priority_queries": [
                x.get("key")
                for x in _low(stats, "by_query_used", low_th)
                if x.get("key") and x.get("key") != "unknown"
            ],
            "channel_whitelist_suggestions": channels[:30],
            "negative_keywords_suggested": negative[:40],
            "ranking_boosts": expansions[:40],
        },
    }
    return plan


def render_rule_based_strategy_markdown(stats: Dict[str, Any], plan: Dict[str, Any]) -> str:
    summary = stats.get("summary") or {}
    suggestions = plan.get("_strategy_suggestions") or {}
    lines = [
        "# Rule-based next search strategy",
        "",
        "## 样本量",
        f"- reviewed: {summary.get('total_reviewed', 0)}",
        f"- pass_rate: {float(summary.get('pass_rate') or 0) * 100:.1f}%",
        f"- sample_size_too_small: {bool(summary.get('sample_size_too_small'))}",
        "",
        "## 增加优先级",
    ]
    task = (plan.get("tasks") or [{}])[0]
    for kw in task.get("keywords") or []:
        lines.append(f"- `{kw}`")
    lines.extend(["", "## 保留品牌"])
    brands = task.get("brands") or []
    lines.extend([f"- `{b}`" for b in brands] or ["- 暂无高置信品牌；继续积累样本。"])
    lines.extend(["", "## 频道白名单建议"])
    channels = suggestions.get("channel_whitelist_suggestions") or []
    lines.extend([f"- `{c}`" for c in channels] or ["- 暂无。"])
    lines.extend(["", "## 降低优先级 query"])
    lows = suggestions.get("lower_priority_queries") or []
    lines.extend([f"- `{q}`" for q in lows] or ["- 暂无。"])
    lines.extend(["", "## 新增 negative_keywords 建议"])
    neg = suggestions.get("negative_keywords_suggested") or []
    lines.extend([f"- `{n}`" for n in neg] or ["- 暂无。"])
    lines.extend(
        [
            "",
            "## 规则建议",
            f"- require_4k: `{(plan.get('resolution') or {}).get('require_4k')}`",
            f"- max_results_per_keyword: `{(plan.get('global_rules') or {}).get('max_results_per_keyword')}`",
            "",
            "## 依据来自哪些统计结果",
            "- `by_query_used` high/low pass rate",
            "- `by_brand` pass rate",
            "- `by_channel_title` pass rate",
            "- `common_reject_reasons`",
            "- `common_pass_features`",
            "- `metadata_risk_features`",
            "",
        ]
    )
    return "\n".join(lines)


def generate_rule_based_strategy(
    *,
    feedback_json_path: Path | str,
    reviewed_jsonl_path: Path | str,
    output_md: Path | str,
    output_yaml: Path | str,
) -> Tuple[str, Dict[str, Any]]:
    stats = json.loads(Path(feedback_json_path).read_text(encoding="utf-8"))
    reviewed_records = list(read_jsonl(reviewed_jsonl_path)) if Path(reviewed_jsonl_path).exists() else []
    plan = build_rule_based_plan(stats, reviewed_records)
    md = render_rule_based_strategy_markdown(stats, plan)

    md_path = Path(output_md)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md + ("\n" if not md.endswith("\n") else ""), encoding="utf-8")
    yaml_path = Path(output_yaml)
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(yaml.safe_dump(plan, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return md, plan
