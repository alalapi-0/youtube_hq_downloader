from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .review_schema import reviewed_rows
from .utils import PROJECT_ROOT, load_yaml_mapping, read_jsonl


URL_ANALYSIS_CONFIG_PATH = PROJECT_ROOT / "config" / "app.yaml"


def _feedback_cfg(path: Path | str = URL_ANALYSIS_CONFIG_PATH) -> Dict[str, Any]:
    if Path(path).name == "app.yaml":
        raw = load_yaml_mapping(path) if Path(path).exists() else {}
        block = raw.get("review") if isinstance(raw.get("review"), dict) else {}
        return {
            "min_sample_size_for_strategy": int(block.get("min_sample_size_for_strategy") or 20),
            "high_pass_rate_threshold": float(block.get("high_pass_rate_threshold") or 0.4),
            "low_pass_rate_threshold": float(block.get("low_pass_rate_threshold") or 0.1),
            "min_count_for_keyword_stats": int(block.get("min_count_for_keyword_stats") or 3),
        }
    raw = load_yaml_mapping(path) if Path(path).exists() else {}
    block = raw.get("feedback_analysis") if isinstance(raw.get("feedback_analysis"), dict) else {}
    return {
        "min_sample_size_for_strategy": int(block.get("min_sample_size_for_strategy") or 20),
        "high_pass_rate_threshold": float(block.get("high_pass_rate_threshold") or 0.4),
        "low_pass_rate_threshold": float(block.get("low_pass_rate_threshold") or 0.1),
        "min_count_for_keyword_stats": int(block.get("min_count_for_keyword_stats") or 3),
    }


def _manual(row: Dict[str, Any]) -> Dict[str, Any]:
    return row.get("manual_review") if isinstance(row.get("manual_review"), dict) else {}


def _status(row: Dict[str, Any]) -> str:
    return str(_manual(row).get("status") or row.get("manual_review_status") or "").strip().lower()


def _is_pass(row: Dict[str, Any]) -> bool:
    manual = _manual(row)
    if manual.get("passed") is True:
        return True
    return _status(row) == "pass"


def _is_reject(row: Dict[str, Any]) -> bool:
    manual = _manual(row)
    if manual.get("passed") is False:
        return True
    return _status(row) == "reject"


def _source(row: Dict[str, Any]) -> Dict[str, Any]:
    return row.get("source_context") if isinstance(row.get("source_context"), dict) else {}


def _fmt(row: Dict[str, Any]) -> Dict[str, Any]:
    return row.get("format_info") if isinstance(row.get("format_info"), dict) else {}


def _field(row: Dict[str, Any], name: str, default: str = "unknown") -> str:
    source = _source(row)
    val = row.get(name)
    if val in (None, ""):
        val = source.get(name)
    text = str(val or "").strip()
    return text or default


def _duration_bucket(row: Dict[str, Any]) -> str:
    try:
        sec = int(row.get("duration_seconds") or 0)
    except (TypeError, ValueError):
        sec = 0
    if sec <= 0:
        return "unknown"
    if sec < 30:
        return "<30s"
    if sec < 90:
        return "30-89s"
    if sec < 180:
        return "90-179s"
    if sec < 600:
        return "3-9min"
    if sec < 1800:
        return "10-29min"
    return ">=30min"


def _height_bucket(row: Dict[str, Any]) -> str:
    h = _fmt(row).get("max_format_height")
    try:
        hv = int(h)
    except (TypeError, ValueError):
        return "unknown"
    if hv >= 2160:
        return "2160p+"
    if hv >= 1440:
        return "1440p"
    if hv >= 1080:
        return "1080p"
    return "<1080p"


def _group_stats(rows: Iterable[Dict[str, Any]], key_fn) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "pass": 0, "reject": 0, "uncertain": 0})
    for row in rows:
        key = str(key_fn(row) or "unknown").strip() or "unknown"
        buckets[key]["total"] += 1
        if _is_pass(row):
            buckets[key]["pass"] += 1
        elif _is_reject(row):
            buckets[key]["reject"] += 1
        else:
            buckets[key]["uncertain"] += 1
    out: List[Dict[str, Any]] = []
    for key, vals in buckets.items():
        total = vals["total"]
        out.append(
            {
                "key": key,
                "total": total,
                "pass": vals["pass"],
                "reject": vals["reject"],
                "uncertain": vals["uncertain"],
                "pass_rate": round(vals["pass"] / total, 4) if total else 0.0,
            }
        )
    out.sort(key=lambda x: (-int(x["total"]), -float(x["pass_rate"]), str(x["key"])))
    return out


def _tokenize_keywords(row: Dict[str, Any]) -> List[str]:
    source = _source(row)
    parts: List[str] = []
    parts.extend(str(source.get("query_used") or "").split(";"))
    parts.extend(str(row.get("title") or "").split())
    parts.extend(str(row.get("channel_title") or "").split())
    parts.extend(str(x) for x in (row.get("tags") or [])[:20])
    tokens: List[str] = []
    for part in parts:
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{2,}", str(part).lower()):
            if token in {"the", "and", "for", "with", "official", "youtube", "video"}:
                continue
            tokens.append(token)
    return tokens


def _keyword_stats(rows: List[Dict[str, Any]], *, min_count: int, high: float, low: float) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    counts: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "pass": 0})
    for row in rows:
        for token in set(_tokenize_keywords(row)):
            counts[token]["total"] += 1
            if _is_pass(row):
                counts[token]["pass"] += 1
    all_stats: List[Dict[str, Any]] = []
    for token, vals in counts.items():
        if vals["total"] < min_count:
            continue
        rate = vals["pass"] / vals["total"] if vals["total"] else 0.0
        all_stats.append({"keyword": token, "total": vals["total"], "pass": vals["pass"], "pass_rate": round(rate, 4)})
    high_stats = sorted([s for s in all_stats if s["pass_rate"] >= high], key=lambda x: (-x["pass_rate"], -x["total"], x["keyword"]))[:30]
    low_stats = sorted([s for s in all_stats if s["pass_rate"] <= low], key=lambda x: (x["pass_rate"], -x["total"], x["keyword"]))[:30]
    return high_stats, low_stats


def _counter_list(counter: Counter[str], limit: int = 30) -> List[Dict[str, Any]]:
    return [{"label": k, "count": v} for k, v in counter.most_common(limit)]


def _metadata_risks(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    risks: Counter[str] = Counter()
    for row in rows:
        if not _is_reject(row):
            continue
        title = str(row.get("title") or "").lower()
        query = str(_source(row).get("query_used") or "").lower()
        height = _fmt(row).get("max_format_height")
        try:
            hv = int(height)
        except (TypeError, ValueError):
            hv = 0
        if hv and hv < 2160:
            risks["max_format_height < 2160"] += 1
        if not hv:
            risks["max_format_height unknown"] += 1
        for term in ("review", "unboxing", "behind the scenes", "full show", "vlog", "compilation"):
            if term in title or term in query:
                risks[f'contains "{term}"'] += 1
    return _counter_list(risks, 20)


def analyze_feedback_records(
    rows: List[Dict[str, Any]],
    *,
    cfg_path: Path | str = URL_ANALYSIS_CONFIG_PATH,
) -> Dict[str, Any]:
    cfg = _feedback_cfg(cfg_path)
    reviewed = reviewed_rows(rows)
    total = len(reviewed)
    passed = sum(1 for r in reviewed if _is_pass(r))
    rejected = sum(1 for r in reviewed if _is_reject(r))
    uncertain = total - passed - rejected

    reject_reasons: Counter[str] = Counter()
    pass_features: Counter[str] = Counter()
    for row in reviewed:
        manual = _manual(row)
        reject_reasons.update(str(x) for x in (manual.get("reject_reasons") or []) if str(x).strip())
        pass_features.update(str(x) for x in (manual.get("pass_features") or []) if str(x).strip())
        if _fmt(row).get("has_2160p_format") and _is_pass(row):
            pass_features["has_2160p_format"] += 1

    high_kw, low_kw = _keyword_stats(
        reviewed,
        min_count=cfg["min_count_for_keyword_stats"],
        high=cfg["high_pass_rate_threshold"],
        low=cfg["low_pass_rate_threshold"],
    )

    by_channel = _group_stats(reviewed, lambda r: r.get("channel_title") or "unknown")
    stats = {
        "summary": {
            "total_reviewed": total,
            "passed": passed,
            "rejected": rejected,
            "uncertain": uncertain,
            "pass_rate": round(passed / total, 4) if total else 0.0,
            "sample_size_too_small": total < cfg["min_sample_size_for_strategy"],
            "min_sample_size_for_strategy": cfg["min_sample_size_for_strategy"],
        },
        "by_category": _group_stats(reviewed, lambda r: _field(r, "category")),
        "by_subcategory": _group_stats(reviewed, lambda r: _field(r, "subcategory")),
        "by_brand": _group_stats(reviewed, lambda r: _field(r, "brand")),
        "by_channel_title": by_channel,
        "by_query_used": _group_stats(reviewed, lambda r: _source(r).get("query_used") or "unknown"),
        "by_duration_range": _group_stats(reviewed, _duration_bucket),
        "by_max_format_height": _group_stats(reviewed, _height_bucket),
        "common_reject_reasons": _counter_list(reject_reasons),
        "common_pass_features": _counter_list(pass_features),
        "high_pass_keywords": high_kw,
        "low_pass_keywords": low_kw,
        "high_pass_channels": [x for x in by_channel if x["total"] >= 2 and x["pass_rate"] >= cfg["high_pass_rate_threshold"]][:20],
        "low_pass_channels": [x for x in by_channel if x["total"] >= 2 and x["pass_rate"] <= cfg["low_pass_rate_threshold"]][:20],
        "metadata_risk_features": _metadata_risks(reviewed),
    }
    stats["recommended_next_directions"] = _recommend_from_stats(stats)
    return stats

def _recommend_from_stats(stats: Dict[str, Any]) -> List[str]:
    recs: List[str] = []
    summary = stats.get("summary") or {}
    if summary.get("sample_size_too_small"):
        recs.append("sample_size_too_small: keep the next strategy conservative until more reviewed examples are available.")
    for item in (stats.get("high_pass_keywords") or [])[:8]:
        recs.append(f"Increase keyword family: {item['keyword']} (pass_rate={item['pass_rate']}, n={item['total']}).")
    for item in (stats.get("low_pass_keywords") or [])[:8]:
        recs.append(f"Reduce or negate keyword: {item['keyword']} (pass_rate={item['pass_rate']}, n={item['total']}).")
    for item in (stats.get("high_pass_channels") or [])[:5]:
        recs.append(f"Keep watching channel: {item['key']} (pass_rate={item['pass_rate']}, n={item['total']}).")
    for item in (stats.get("common_reject_reasons") or [])[:5]:
        recs.append(f"Strengthen filter for reject reason: {item['label']} (count={item['count']}).")
    return recs


def _md_table(items: List[Dict[str, Any]], columns: List[str], *, limit: int = 15) -> List[str]:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for item in items[:limit]:
        cells = [str(item.get(c, "")).replace("|", "\\|") for c in columns]
        lines.append("| " + " | ".join(cells) + " |")
    if len(lines) == 2:
        lines.append("| " + " | ".join([""] * len(columns)) + " |")
    return lines


def render_feedback_markdown(stats: Dict[str, Any]) -> str:
    s = stats.get("summary") or {}
    lines = [
        "# Review feedback analysis",
        "",
        "## 总体",
        f"- 总审核数：{s.get('total_reviewed', 0)}",
        f"- 通过：{s.get('passed', 0)}",
        f"- 不通过：{s.get('rejected', 0)}",
        f"- 不确定：{s.get('uncertain', 0)}",
        f"- 通过率：{float(s.get('pass_rate') or 0) * 100:.1f}%",
        f"- sample_size_too_small：{bool(s.get('sample_size_too_small'))}",
        "",
        "## 按 query_used 通过率",
        *_md_table(stats.get("by_query_used") or [], ["key", "total", "pass", "reject", "pass_rate"]),
        "",
        "## 按品牌通过率",
        *_md_table(stats.get("by_brand") or [], ["key", "total", "pass", "reject", "pass_rate"]),
        "",
        "## 高通过率频道",
        *_md_table(stats.get("high_pass_channels") or [], ["key", "total", "pass", "reject", "pass_rate"]),
        "",
        "## 常见拒绝原因",
        *_md_table(stats.get("common_reject_reasons") or [], ["label", "count"], limit=20),
        "",
        "## 常见通过特征",
        *_md_table(stats.get("common_pass_features") or [], ["label", "count"], limit=20),
        "",
        "## 高通过率关键词",
        *_md_table(stats.get("high_pass_keywords") or [], ["keyword", "total", "pass", "pass_rate"], limit=20),
        "",
        "## 低通过率关键词",
        *_md_table(stats.get("low_pass_keywords") or [], ["keyword", "total", "pass", "pass_rate"], limit=20),
        "",
        "## 高风险 metadata 特征",
        *_md_table(stats.get("metadata_risk_features") or [], ["label", "count"], limit=20),
        "",
        "## 推荐下一轮搜索方向",
    ]
    recs = stats.get("recommended_next_directions") or []
    if recs:
        lines.extend(f"- {x}" for x in recs)
    else:
        lines.append("- 暂无足够规律，建议继续积累人工审核样本。")
    lines.append("")
    return "\n".join(lines)


def analyze_feedback_file(
    *,
    input_path: Path | str,
    output_md: Path | str,
    output_json: Path | str,
    cfg_path: Path | str = URL_ANALYSIS_CONFIG_PATH,
) -> Dict[str, Any]:
    rows = list(read_jsonl(input_path))
    stats = analyze_feedback_records(rows, cfg_path=cfg_path)
    out_json = Path(output_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md = Path(output_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_feedback_markdown(stats), encoding="utf-8")
    return stats
