from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .utils import PROJECT_ROOT, coerce_candidate, read_jsonl, write_jsonl


def _count_jsonl(path: Path | None) -> int:
    if not path or not path.exists():
        return 0
    return sum(1 for _ in read_jsonl(path))


def _histogram_manual_review(rows: List[Dict[str, Any]]) -> Counter[str]:
    c: Counter[str] = Counter()
    for r in rows:
        cat = str(r.get("category") or "∅")
        sub = str(r.get("subcategory") or "∅")
        prio = str(r.get("manual_review_priority") or "∅")
        c[f"{cat} / {sub} / {prio}"] += 1
    return c


def _stats_header_extended(
    *,
    filtered: List[Dict[str, Any]],
    generated_at_iso: str,
    stage_counts: Dict[str, int],
    rejected_rule: int,
    rejected_llm: int,
) -> str:
    n_f = len(filtered)
    n_4k_probe = sum(1 for r in filtered if r.get("probe_confirmed_4k"))
    n_text_4k = sum(
        1
        for r in filtered
        if r.get("resolution_text_evidence_4k") and not r.get("probe_confirmed_4k")
    )
    n_needs_check = sum(1 for r in filtered if r.get("needs_resolution_check"))

    lines = [
        "## Export statistics",
        "",
        f"- **generated_at_utc**: {generated_at_iso}",
        f"- **final_filtered_count**: {n_f}",
        f"- **rejected_rule_count**: {rejected_rule}",
        f"- **rejected_llm_count**: {rejected_llm}",
        "",
        "### Stage counts（若对应 JSONL 存在则自动计数；否则显示 0）",
        "",
    ]
    for k in (
        "raw_search",
        "enriched",
        "probed",
        "rule_filtered",
        "llm_filtered",
    ):
        lines.append(f"- **{k}**: {int(stage_counts.get(k) or 0)}")
    lines.extend(
        [
            "",
            "### 4K 相关",
            "",
            f"- **4k_probe_confirmed**: {n_4k_probe}",
            f"- **4k_text_only_claims**: {n_text_4k}",
            f"- **needs_resolution_check**: {n_needs_check}",
            "",
            "### Manual review priority × category 直方（Top 12）",
            "",
        ]
    )
    hist = _histogram_manual_review(filtered).most_common(12)
    for bucket, cnt in hist:
        lines.append(f"- `{bucket}` → **{cnt}**")

    lines.append("")
    return "\n".join(lines)


def export_markdown(
    filtered: List[Dict[str, Any]],
    path: Path,
    *,
    rejected_rule_rows: List[Dict[str, Any]] | None = None,
    rejected_llm_rows: List[Dict[str, Any]] | None = None,
    stage_paths: Dict[str, Path | None] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "video_id",
        "title",
        "channel_title",
        "brand",
        "duration_seconds",
        "canonical_url",
        "filter_score",
        "probe_confirmed_4k",
        "format_probe_status",
        "available_format_heights",
        "resolution_text_evidence_4k",
        "needs_resolution_check",
        "visual_quality_risk",
        "llm_status",
        "llm_relevant",
        "llm_brand_fit",
        "llm_notes",
        "manual_review_priority",
        "manual_review_status",
        "category",
        "subcategory",
    ]

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    sp = dict(stage_paths or {})
    defaults = {
        "raw_search": PROJECT_ROOT / "data" / "raw" / "candidates.jsonl",
        "enriched": PROJECT_ROOT / "data" / "enriched" / "enriched.jsonl",
        "probed": PROJECT_ROOT / "data" / "enriched" / "probed.jsonl",
        "rule_filtered": PROJECT_ROOT / "data" / "filtered" / "rule_filtered.jsonl",
        "llm_filtered": PROJECT_ROOT / "data" / "filtered" / "llm_filtered.jsonl",
    }
    for k, v in defaults.items():
        sp.setdefault(k, v)

    stage_counts = {k: _count_jsonl(Path(p)) for k, p in sp.items() if p}

    rej_r = rejected_rule_rows or []
    rej_l = rejected_llm_rows or []
    rejected_rule_cnt = len(rej_r)
    rejected_llm_cnt = len(rej_l)

    header = _stats_header_extended(
        filtered=filtered,
        generated_at_iso=now,
        stage_counts=stage_counts,
        rejected_rule=rejected_rule_cnt,
        rejected_llm=rejected_llm_cnt,
    )

    head_row = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    lines = [header, "", head_row, sep]
    for r in filtered:
        cells = []
        for c in cols:
            v = r.get(c)
            if c == "available_format_heights" and isinstance(v, list):
                v_render = ";".join(str(x) for x in v[:40])
                if len(v) > 40:
                    v_render += "…"
                v = v_render
            if v is None:
                cells.append("")
            else:
                cells.append(str(v).replace("|", "\\|").replace("\n", " "))
        lines.append("| " + " | ".join(cells) + " |")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_csv(filtered: List[Dict[str, Any]], path: Path) -> None:
    import pandas as pd

    cols = [
        "video_id",
        "title",
        "channel_title",
        "brand",
        "duration_seconds",
        "canonical_url",
        "filter_score",
        "probe_confirmed_4k",
        "format_probe_status",
        "available_format_heights",
        "resolution_text_evidence_4k",
        "needs_resolution_check",
        "visual_quality_risk",
        "llm_status",
        "llm_relevant",
        "llm_brand_fit",
        "llm_notes",
        "manual_review_priority",
        "manual_review_status",
        "category",
        "subcategory",
        "matched_keywords",
    ]
    rows: List[Dict[str, Any]] = []
    for r in filtered:
        row = {c: r.get(c) for c in cols if c != "matched_keywords"}
        mk = r.get("matched_keywords")
        row["matched_keywords"] = ";".join(mk) if isinstance(mk, list) else mk
        af = r.get("available_format_heights")
        if isinstance(af, list):
            row["available_format_heights"] = ";".join(str(x) for x in af)
        rows.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=cols)
    df.to_csv(path, index=False)


def export_jsonl(filtered: List[Dict[str, Any]], path: Path) -> None:
    write_jsonl(path, filtered)


def export_all(
    filtered: List[Dict[str, Any]],
    output_dir: Path,
    *,
    rejected_rule_rows: List[Dict[str, Any]] | None = None,
    rejected_llm_rows: List[Dict[str, Any]] | None = None,
    stage_paths: Dict[str, Path | None] | None = None,
) -> None:
    export_csv(filtered, output_dir / "csv" / "filtered_urls.csv")
    export_jsonl(filtered, output_dir / "jsonl" / "filtered_urls.jsonl")
    export_markdown(
        filtered,
        output_dir / "markdown" / "filtered_urls.md",
        rejected_rule_rows=rejected_rule_rows,
        rejected_llm_rows=rejected_llm_rows,
        stage_paths=stage_paths,
    )


def normalize_records_for_export(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [coerce_candidate(dict(r)) for r in rows]
