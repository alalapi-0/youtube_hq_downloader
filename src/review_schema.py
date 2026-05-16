from __future__ import annotations

import csv
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .utils import PROJECT_ROOT, extract_video_id, read_jsonl, write_jsonl


REVIEW_LABELS_PATH = PROJECT_ROOT / "config" / "labels.yaml"


def load_review_labels(path: Path | str = REVIEW_LABELS_PATH) -> Dict[str, Any]:
    import yaml

    p = Path(path)
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def default_manual_review() -> Dict[str, Any]:
    return {
        "status": "pending",
        "passed": None,
        "reject_reasons": [],
        "pass_features": [],
        "notes": "",
        "reviewer": "",
        "reviewed_at": "",
        "unrecognized_labels": [],
    }


def flatten_reject_reasons(labels: Dict[str, Any]) -> set[str]:
    out: set[str] = set()
    groups = labels.get("reject_reasons") or {}
    if isinstance(groups, dict):
        for vals in groups.values():
            if isinstance(vals, list):
                out.update(str(x).strip() for x in vals if str(x).strip())
    return out


def allowed_pass_features(labels: Dict[str, Any]) -> set[str]:
    vals = labels.get("pass_features") or []
    return {str(x).strip() for x in vals if str(x).strip()} if isinstance(vals, list) else set()


def allowed_statuses(labels: Dict[str, Any]) -> set[str]:
    vals = labels.get("manual_status") or []
    return {str(x).strip() for x in vals if str(x).strip()} if isinstance(vals, list) else {"pending", "pass", "reject", "uncertain"}


def split_label_cell(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    raw = str(value).strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass
    out: List[str] = []
    for token in raw.replace("|", ";").replace(",", ";").split(";"):
        t = token.strip()
        if t:
            out.append(t)
    return out


def parse_bool_cell(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in ("", "none", "null"):
        return None
    if raw in ("1", "true", "yes", "y", "pass", "passed", "是", "通过"):
        return True
    if raw in ("0", "false", "no", "n", "reject", "rejected", "否", "不通过"):
        return False
    return None


def infer_passed_from_status(status: str, explicit: bool | None) -> bool | None:
    if explicit is not None:
        return explicit
    s = (status or "").strip().lower()
    if s == "pass":
        return True
    if s == "reject":
        return False
    return None


def review_identity(row: Dict[str, Any]) -> Tuple[str, str]:
    url = str(row.get("video_url") or row.get("canonical_url") or row.get("url") or "").strip()
    vid = str(row.get("video_id") or "").strip() or str(extract_video_id(url) or "")
    return vid, url


def _merge_existing_manual(record: Dict[str, Any]) -> Dict[str, Any]:
    base = default_manual_review()
    nested = record.get("manual_review")
    if isinstance(nested, dict):
        base.update(deepcopy(nested))
    status = record.get("manual_review_status")
    if status and base.get("status") in ("", "pending", None):
        base["status"] = str(status)
    return base


def validate_manual_review_row(csv_row: Dict[str, Any], labels: Dict[str, Any]) -> Dict[str, Any]:
    valid_status = allowed_statuses(labels)
    valid_reject = flatten_reject_reasons(labels)
    valid_pass = allowed_pass_features(labels)

    status = str(csv_row.get("manual_status") or csv_row.get("status") or "").strip().lower()
    if not status:
        status = "pending"

    reject_reasons = split_label_cell(csv_row.get("manual_reject_reasons"))
    pass_features = split_label_cell(csv_row.get("manual_pass_features"))
    unrecognized: List[str] = []

    if status not in valid_status:
        unrecognized.append(status)
        status = "pending"

    clean_reject: List[str] = []
    for reason in reject_reasons:
        if reason in valid_reject:
            clean_reject.append(reason)
        else:
            unrecognized.append(reason)

    clean_pass: List[str] = []
    for feat in pass_features:
        if feat in valid_pass:
            clean_pass.append(feat)
        else:
            unrecognized.append(feat)

    explicit_passed = parse_bool_cell(csv_row.get("manual_passed"))
    passed = infer_passed_from_status(status, explicit_passed)

    return {
        "status": status,
        "passed": passed,
        "reject_reasons": clean_reject,
        "pass_features": clean_pass,
        "notes": str(csv_row.get("manual_notes") or "").strip(),
        "reviewer": str(csv_row.get("reviewer") or "").strip(),
        "reviewed_at": str(csv_row.get("reviewed_at") or "").strip(),
        "unrecognized_labels": unrecognized,
    }


def import_manual_reviews(
    *,
    analysis_path: Path | str,
    review_csv_path: Path | str,
    output_path: Path | str,
    labels_path: Path | str = REVIEW_LABELS_PATH,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    labels = load_review_labels(labels_path)
    analysis_rows = list(read_jsonl(analysis_path))
    by_vid: Dict[str, Dict[str, Any]] = {}
    by_url: Dict[str, Dict[str, Any]] = {}

    out_rows = [deepcopy(r) for r in analysis_rows]
    for row in out_rows:
        vid, url = review_identity(row)
        if vid:
            by_vid[vid] = row
        if url:
            by_url[url] = row

    updates = 0
    unknown_rows = 0
    unrecognized_counter: Dict[str, int] = {}

    with Path(review_csv_path).open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for csv_row in reader:
            vid, url = review_identity(csv_row)
            target = by_vid.get(vid) if vid else None
            if target is None and url:
                target = by_url.get(url)
            if target is None:
                unknown_rows += 1
                continue

            manual = _merge_existing_manual(target)
            previous_unrecognized = split_label_cell(manual.get("unrecognized_labels"))
            update = validate_manual_review_row(csv_row, labels)
            manual.update(update)

            combined_unrecognized: List[str] = []
            for label in [*previous_unrecognized, *update.get("unrecognized_labels", [])]:
                if label and label not in combined_unrecognized:
                    combined_unrecognized.append(label)
                    unrecognized_counter[label] = unrecognized_counter.get(label, 0) + 1
            manual["unrecognized_labels"] = combined_unrecognized

            target["manual_review"] = manual
            target["manual_review_status"] = manual["status"]
            updates += 1

    write_jsonl(output_path, out_rows)
    summary = {
        "analysis_rows": len(analysis_rows),
        "review_rows_updated": updates,
        "review_rows_unmatched": unknown_rows,
        "unrecognized_labels": unrecognized_counter,
    }
    return out_rows, summary


def reviewed_rows(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in records:
        manual = r.get("manual_review") if isinstance(r.get("manual_review"), dict) else {}
        status = str((manual or {}).get("status") or r.get("manual_review_status") or "").strip().lower()
        if status in ("pass", "reject", "uncertain"):
            out.append(r)
    return out
