from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List

from .utils import write_jsonl


def _stats_header(
    filtered: List[Dict[str, Any]],
    rejected: List[Dict[str, Any]] | None = None,
) -> str:
    rej = rejected or []
    n_f = len(filtered)
    n_r = len(rej)
    n_4k_probe = sum(1 for r in filtered if r.get("probe_confirmed_4k"))
    n_text_4k = sum(
        1
        for r in filtered
        if r.get("resolution_text_evidence_4k") and not r.get("probe_confirmed_4k")
    )
    n_needs_check = sum(1 for r in filtered if r.get("needs_resolution_check"))
    lines = [
        "## Export summary",
        "",
        f"- **filtered_count**: {n_f}",
        f"- **rejected_count**: {n_r}",
        f"- **4k_probe_confirmed**: {n_4k_probe}",
        f"- **4k_text_only_claims**: {n_text_4k}",
        f"- **needs_resolution_check**: {n_needs_check}",
        "",
    ]
    return "\n".join(lines)


def export_markdown(filtered: List[Dict[str, Any]], path: Path, rejected: List[Dict[str, Any]] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "video_id",
        "title",
        "channel_title",
        "duration_seconds",
        "canonical_url",
        "filter_score",
        "probe_confirmed_4k",
        "format_probe_status",
        "resolution_text_evidence_4k",
        "needs_resolution_check",
        "manual_review_status",
    ]
    header = _stats_header(filtered, rejected)
    head_row = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    lines = [header, head_row, sep]
    for r in filtered:
        cells = []
        for c in cols:
            v = r.get(c)
            if v is None:
                cells.append("")
            else:
                s = str(v).replace("|", "\\|")
                cells.append(s)
        lines.append("| " + " | ".join(cells) + " |")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_csv(filtered: List[Dict[str, Any]], path: Path) -> None:
    import pandas as pd

    cols = [
        "video_id",
        "title",
        "channel_title",
        "duration_seconds",
        "canonical_url",
        "filter_score",
        "probe_confirmed_4k",
        "format_probe_status",
        "resolution_text_evidence_4k",
        "needs_resolution_check",
        "manual_review_status",
        "category",
        "subcategory",
        "matched_keywords",
    ]
    rows: List[Dict[str, Any]] = []
    for r in filtered:
        row = {c: r.get(c) for c in cols}
        mk = r.get("matched_keywords")
        row["matched_keywords"] = ";".join(mk) if isinstance(mk, list) else mk
        rows.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=cols)
    df.to_csv(path, index=False)


def export_jsonl(filtered: List[Dict[str, Any]], path: Path) -> None:
    write_jsonl(path, filtered)


def export_all(
    filtered: List[Dict[str, Any]],
    output_dir: Path,
    rejected: List[Dict[str, Any]] | None = None,
) -> None:
    export_csv(filtered, output_dir / "csv" / "filtered_urls.csv")
    export_jsonl(filtered, output_dir / "jsonl" / "filtered_urls.jsonl")
    export_markdown(filtered, output_dir / "markdown" / "filtered_urls.md", rejected=rejected)
