from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def workspace_path(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath(*parts)


def read_jsonl(path: Path | str) -> Iterator[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return iter(())
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def write_jsonl(path: Path | str, records: Iterable[Dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False))
            f.write("\n")


def load_yaml_mapping(path: Path | str) -> Dict[str, Any]:
    import yaml

    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


VIDEO_ID_PATTERN = re.compile(
    r"(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/(?:shorts|embed|live)\/)([\w-]{11})",
    re.I,
)


def extract_video_id(text: str) -> Optional[str]:
    if not text:
        return None
    m = VIDEO_ID_PATTERN.search(text)
    if m:
        return m.group(1)
    # bare 11-char id fallback
    t = text.strip()
    if re.fullmatch(r"[\w-]{11}", t):
        return t
    return None


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def blank_candidate(**overrides: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "source_platform": "youtube",
        "video_id": "",
        "canonical_url": "",
        "title": "",
        "description": "",
        "channel_id": "",
        "channel_title": "",
        "published_at": "",
        "category": "",
        "subcategory": "",
        "search_task_id": "",
        "matched_keywords": [],
        "region_code": "",
        "relevance_language": "",
        "duration_seconds": None,
        "duration_iso8601": "",
        "definition": "",
        "caption_available": False,
        "is_live": False,
        "is_shorts_candidate": False,
        "view_count": None,
        "like_count": None,
        "comment_count": None,
        "thumbnail_best_url": "",
        "tags": [],
        "format_probe_status": "pending",
        "probe_confirmed_4k": False,
        "probe_max_height": None,
        "resolution_text_evidence_4k": False,
        "resolution_text_evidence_detail": "",
        "needs_resolution_check": False,
        "filter_score": 0.0,
        "positive_keyword_hits": [],
        "negative_keyword_hits": [],
        "hard_filter_pass": None,
        "rejection_codes": [],
        "rejection_reason": "",
        "dedupe_channel_rank_in_scope": None,
        "manual_review_status": "pending",
    }
    row.update(overrides)
    return row


def merge_candidates(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out = deepcopy(a)
    for k, v in b.items():
        if k == "matched_keywords":
            out[k] = sorted(set(out.get(k) or []) | set(v or []))
            continue
        if v is None or v == "" or v == []:
            continue
        if isinstance(v, dict) and not v:
            continue
        prev = out.get(k)
        if prev in (None, "", []):
            out[k] = v
            continue
    return out


def detect_text_4k_evidence(title: str, description: str) -> Tuple[bool, str]:
    hay = f"{title or ''}\n{description or ''}".lower()
    ptrns = (
        r"\b2160p\b",
        r"\b4k\b",
        r"\buhd\b",
        r"\bultra\s*hd\b",
        r"\b3840\s*[x×]\s*2160\b",
        r"\b2160\s*[x×]\s*\d+\b",
    )
    hits: list[str] = []
    for p in ptrns:
        if re.search(p, hay, re.I):
            hits.append(p)
    if hits:
        return True, ",".join(hits)
    return False, ""
