from __future__ import annotations

import csv
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import isodate

from .review_schema import default_manual_review
from .utils import extract_video_id, read_jsonl, sniff_description, watch_url, write_jsonl


REVIEW_COLUMNS = [
    "video_url",
    "title",
    "channel_title",
    "brand",
    "category",
    "subcategory",
    "duration_seconds",
    "max_format_height",
    "has_2160p_format",
    "query_used",
    "quality_score",
    "llm_decision",
    "llm_reason",
    "manual_status",
    "manual_passed",
    "manual_reject_reasons",
    "manual_pass_features",
    "manual_notes",
    "reviewer",
    "reviewed_at",
]

VIMEO_ID_PATTERN = re.compile(r"vimeo\.com/(?:[^/\s]+/)*(\d{6,})", re.I)


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


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_list(value: Any) -> List[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return list(value.values())
    raw = str(value).strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    return [x.strip() for x in raw.replace("|", ";").split(";") if x.strip()]


def _unique_strs(values: Iterable[Any]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _extract_hashtags(*texts: Any) -> List[str]:
    tags: List[str] = []
    for text in texts:
        for hit in re.findall(r"(?<!\w)#([\w-]{2,80})", str(text or ""), re.UNICODE):
            tags.append("#" + hit)
    return _unique_strs(tags)


def _duration_seconds_from_iso(value: Any) -> int | None:
    if not value:
        return None
    try:
        return int(isodate.parse_duration(str(value)).total_seconds())
    except Exception:
        return None


def _duration_iso_from_seconds(value: Any) -> str:
    seconds = _as_int(value)
    return f"PT{seconds}S" if seconds is not None else ""


def _best_url(row: Dict[str, Any]) -> str:
    for key in ("video_url", "canonical_url", "url", "webpage_url", "original_url"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    vid = str(row.get("video_id") or "").strip()
    return watch_url(vid) if vid else ""


def _video_id(row: Dict[str, Any], url: str) -> str:
    explicit = str(row.get("video_id") or "").strip()
    if explicit:
        return explicit
    youtube_id = extract_video_id(url)
    if youtube_id:
        return youtube_id
    match = VIMEO_ID_PATTERN.search(url or "")
    return match.group(1) if match else ""


def _thumbnail_urls(row: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    urls.extend(_as_list(row.get("thumbnail_urls")))
    if row.get("thumbnail_best_url"):
        urls.append(str(row["thumbnail_best_url"]))
    thumbs = row.get("thumbnails")
    if isinstance(thumbs, dict):
        for value in thumbs.values():
            if isinstance(value, dict) and value.get("url"):
                urls.append(str(value["url"]))
    elif isinstance(thumbs, list):
        for item in thumbs:
            if isinstance(item, dict) and item.get("url"):
                urls.append(str(item["url"]))
    return _unique_strs(urls)


def _description_limit(cfg: Dict[str, Any]) -> int:
    try:
        return max(0, int(((cfg.get("url_analysis") or {}).get("max_description_chars") or 1500)))
    except (TypeError, ValueError):
        return 1500


def _source_query(row: Dict[str, Any]) -> str:
    value = str(row.get("query_used") or "").strip()
    if value:
        return value
    return "; ".join(str(x) for x in _as_list(row.get("matched_keywords")) if str(x).strip())


def _llm_decision(row: Dict[str, Any]) -> str:
    if row.get("llm_relevant") is True:
        return "pass"
    if row.get("llm_relevant") is False:
        return "reject"
    return str(row.get("llm_status") or "").strip()


def _empty_webpage_metadata() -> Dict[str, Any]:
    return {
        "og_title": "",
        "og_description": "",
        "meta_keywords": [],
        "json_ld": {},
        "canonical_url": "",
        "page_title": "",
        "page_description": "",
        "status": "not_requested",
        "error": "",
    }


def _analysis_template(row: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    raw_url = _best_url(row)
    vid = _video_id(row, raw_url)
    video_url = raw_url or (watch_url(vid) if vid and len(vid) == 11 else "")
    errors: List[str] = []
    if not video_url:
        errors.append("invalid_url")
    if video_url and not video_url.startswith(("http://", "https://")):
        errors.append("invalid_url")

    description = str(row.get("description") or "")
    limit = _description_limit(cfg)
    if limit and len(description) > limit:
        description = description[:limit]

    duration_seconds = _as_int(row.get("duration_seconds"))
    if duration_seconds is None:
        duration_seconds = _duration_seconds_from_iso(row.get("duration_iso8601"))

    heights = sorted({_as_int(x) for x in _as_list(row.get("available_format_heights")) if _as_int(x) is not None})
    max_height = _as_int(row.get("max_format_height"))
    if max_height is None:
        max_height = _as_int(row.get("probe_max_height"))
    if max_height is None and heights:
        max_height = max(heights)
    has_2160 = bool(row.get("has_2160p_format") or row.get("probe_confirmed_4k") or (max_height is not None and max_height >= 2160))

    manual = default_manual_review()
    nested_manual = row.get("manual_review")
    if isinstance(nested_manual, dict):
        manual.update(deepcopy(nested_manual))
    elif row.get("manual_review_status"):
        manual["status"] = str(row.get("manual_review_status") or "pending")

    tags = [str(x) for x in _as_list(row.get("tags")) if str(x).strip()]
    hashtags = _unique_strs([*_extract_hashtags(row.get("title"), description), *[x for x in tags if x.startswith("#")]])

    return {
        "video_url": video_url,
        "video_id": vid,
        "source_platform": str(row.get("source_platform") or ("vimeo" if "vimeo.com" in video_url.lower() else "youtube" if "youtu" in video_url.lower() else "")),
        "title": str(row.get("title") or ""),
        "channel_title": str(row.get("channel_title") or ""),
        "channel_id": str(row.get("channel_id") or ""),
        "channel_url": str(row.get("channel_url") or ""),
        "description": description,
        "description_snippet": str(row.get("description_snippet") or sniff_description(description)),
        "tags": tags,
        "hashtags": hashtags,
        "category": str(row.get("category") or ""),
        "subcategory": str(row.get("subcategory") or ""),
        "brand": str(row.get("brand") or ""),
        "published_at": str(row.get("published_at") or ""),
        "duration_seconds": duration_seconds,
        "duration_iso8601": str(row.get("duration_iso8601") or _duration_iso_from_seconds(duration_seconds)),
        "view_count": _as_int(row.get("view_count")),
        "like_count": _as_int(row.get("like_count")),
        "comment_count": _as_int(row.get("comment_count")),
        "thumbnail_urls": _thumbnail_urls(row),
        "webpage_metadata": _empty_webpage_metadata(),
        "webpage_metadata_status": "not_requested",
        "format_info": {
            "available_format_heights": heights,
            "max_format_height": max_height,
            "has_2160p_format": has_2160,
            "format_probe_status": str(row.get("format_probe_status") or "not_requested"),
        },
        "source_context": {
            "query_used": _source_query(row),
            "category": str(row.get("category") or ""),
            "subcategory": str(row.get("subcategory") or ""),
            "brand": str(row.get("brand") or ""),
            "source_stage": str(row.get("source_stage") or "openrouter_web_search"),
            "search_task_id": str(row.get("search_task_id") or ""),
        },
        "auto_filter": {
            "rule_filter_passed": row.get("hard_filter_pass"),
            "rule_reject_reasons": _as_list(row.get("rejection_codes")),
            "llm_decision": _llm_decision(row),
            "llm_reason": str(row.get("llm_notes") or row.get("llm_reason") or ""),
            "quality_score": _as_float(row.get("quality_score") if row.get("quality_score") is not None else row.get("filter_score")),
        },
        "manual_review": manual,
        "analysis": {
            "llm_feature_summary": str(row.get("llm_feature_analysis") or ""),
            "likely_positive_features": _as_list(row.get("likely_positive_features")),
            "likely_negative_features": _as_list(row.get("likely_negative_features")),
            "search_keywords_suggested": _as_list(row.get("search_keywords_suggested")),
        },
        "metadata_sources": ["openrouter_web_search"],
        "errors": errors,
    }


def load_url_input(path: Path | str) -> List[Dict[str, Any]]:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".jsonl":
        return [dict(row) for row in read_jsonl(source)]
    if suffix == ".csv":
        with source.open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    rows: List[Dict[str, Any]] = []
    with source.open(encoding="utf-8") as handle:
        for line in handle:
            value = line.strip()
            if value:
                rows.append({"video_url": value})
    return rows


def analyze_url_records(
    input_records: List[Dict[str, Any]],
    *,
    cfg: Dict[str, Any],
    offline: bool = True,
) -> List[Dict[str, Any]]:
    return [_analysis_template(dict(row), cfg) for row in input_records]


def analyze_url_file(
    *,
    input_path: Path | str,
    output_path: Path | str,
    cfg_path: Path | str | None = None,
    offline: bool = True,
) -> List[Dict[str, Any]]:
    from .core.config import url_analysis_compat_config

    rows = load_url_input(input_path)
    analyzed = analyze_url_records(rows, cfg=url_analysis_compat_config(), offline=offline)
    write_jsonl(output_path, analyzed)
    return analyzed


def _review_row(rec: Dict[str, Any], *, include_existing_manual: bool = False) -> Dict[str, Any]:
    fmt = rec.get("format_info") if isinstance(rec.get("format_info"), dict) else {}
    source = rec.get("source_context") if isinstance(rec.get("source_context"), dict) else {}
    auto = rec.get("auto_filter") if isinstance(rec.get("auto_filter"), dict) else {}
    manual = rec.get("manual_review") if isinstance(rec.get("manual_review"), dict) else {}
    return {
        "video_url": rec.get("video_url") or "",
        "title": rec.get("title") or "",
        "channel_title": rec.get("channel_title") or "",
        "brand": rec.get("brand") or source.get("brand") or "",
        "category": rec.get("category") or source.get("category") or "",
        "subcategory": rec.get("subcategory") or source.get("subcategory") or "",
        "duration_seconds": rec.get("duration_seconds") if rec.get("duration_seconds") is not None else "",
        "max_format_height": fmt.get("max_format_height") if fmt.get("max_format_height") is not None else "",
        "has_2160p_format": fmt.get("has_2160p_format"),
        "query_used": source.get("query_used") or "",
        "quality_score": auto.get("quality_score") if auto.get("quality_score") is not None else "",
        "llm_decision": auto.get("llm_decision") or "",
        "llm_reason": auto.get("llm_reason") or "",
        "manual_status": manual.get("status") if include_existing_manual else "",
        "manual_passed": manual.get("passed") if include_existing_manual else "",
        "manual_reject_reasons": ";".join(manual.get("reject_reasons") or []) if include_existing_manual else "",
        "manual_pass_features": ";".join(manual.get("pass_features") or []) if include_existing_manual else "",
        "manual_notes": manual.get("notes") if include_existing_manual else "",
        "reviewer": manual.get("reviewer") if include_existing_manual else "",
        "reviewed_at": manual.get("reviewed_at") if include_existing_manual else "",
    }


def export_review_sheet(
    records: Iterable[Dict[str, Any]],
    *,
    output_csv: Path | str,
    output_md: Path | str,
    include_existing_manual: bool = False,
) -> Tuple[Path, Path]:
    rows = [_review_row(row, include_existing_manual=include_existing_manual) for row in records]

    csv_path = Path(output_csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    md_path = Path(output_md)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_lines = [
        "# Manual review sheet",
        "",
        "| 序号 | 标题 | 频道 | URL | 品牌 | 时长 | 最大格式高度 | 自动评分 | LLM 判断 | 人工状态 | 人工拒绝原因 | 备注 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for idx, row in enumerate(rows, start=1):
        cells = [
            str(idx),
            str(row.get("title") or ""),
            str(row.get("channel_title") or ""),
            str(row.get("video_url") or ""),
            str(row.get("brand") or ""),
            str(row.get("duration_seconds") or ""),
            str(row.get("max_format_height") or ""),
            str(row.get("quality_score") or ""),
            str(row.get("llm_decision") or ""),
            str(row.get("manual_status") or ""),
            str(row.get("manual_reject_reasons") or ""),
            str(row.get("manual_notes") or ""),
        ]
        md_lines.append("| " + " | ".join(cell.replace("|", "\\|").replace("\n", " ") for cell in cells) + " |")
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return csv_path, md_path


def export_review_sheet_from_file(
    *,
    analysis_path: Path | str,
    output_csv: Path | str,
    output_md: Path | str,
    include_existing_manual: bool = False,
) -> Tuple[Path, Path]:
    return export_review_sheet(
        list(read_jsonl(analysis_path)),
        output_csv=output_csv,
        output_md=output_md,
        include_existing_manual=include_existing_manual,
    )
