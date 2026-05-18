from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Tuple

from ..core.config import openrouter_config
from .openrouter_client import OpenRouterClient, OpenRouterError
from .prompts import CANDIDATE_FILTER_SYSTEM


def _parse_json(raw: str) -> Dict[str, Any]:
    text = raw.strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
        if m:
            return json.loads(m.group(1).strip())
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
    raise ValueError("LLM JSON parse failed")


def _trunc(text: str, limit: int = 900) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def _batches(rows: List[Dict[str, Any]], size: int) -> Iterable[List[Dict[str, Any]]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def semantic_filter_candidates(records: List[Dict[str, Any]], *, use_ai: bool = True) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    warnings: List[str] = []
    client = OpenRouterClient()
    if not use_ai:
        out = []
        for row in records:
            r = dict(row)
            r.update(llm_status="skipped", llm_relevant=True, llm_provider="", llm_model="")
            out.append(r)
        return out, [], ["AI 语义复筛已关闭，使用规则过滤结果作为最终候选。"]
    if not client.is_configured():
        out = []
        for row in records:
            r = dict(row)
            r.update(llm_status="skipped_missing_openrouter", llm_relevant=True, llm_provider="openrouter", llm_model=client.model)
            out.append(r)
        return out, [], ["未检测到 OPENROUTER_API_KEY，已跳过 AI 语义复筛。"]

    max_batch = int(openrouter_config().get("max_items_per_batch") or 20)
    kept: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    for batch in _batches(records, max_batch):
        compact = [
            {
                "video_id": r.get("video_id"),
                "title": r.get("title"),
                "channel_title": r.get("channel_title"),
                "brand": r.get("brand"),
                "category": r.get("category"),
                "subcategory": r.get("subcategory"),
                "duration_seconds": r.get("duration_seconds"),
                "max_format_height": r.get("probe_max_height") or r.get("max_format_height"),
                "description": _trunc(str(r.get("description") or "")),
                "positive_keyword_hits": r.get("positive_keyword_hits") or [],
                "negative_keyword_hits": r.get("negative_keyword_hits") or [],
            }
            for r in batch
        ]
        input_text = json.dumps(compact, ensure_ascii=False)
        messages = [
            {"role": "system", "content": CANDIDATE_FILTER_SYSTEM},
            {"role": "user", "content": "CANDIDATES_JSON:\n" + input_text},
        ]
        processed: Dict[str, Dict[str, Any]] = {}
        try:
            parsed, _raw, _cached = client.chat_cached(
                skill_name="candidate_filter",
                input_text=input_text,
                messages=messages,
                parser=_parse_json,
            )
            for item in parsed.get("results") or []:
                if isinstance(item, dict) and item.get("video_id"):
                    processed[str(item["video_id"])] = item
        except (OpenRouterError, Exception) as exc:
            warnings.append(f"AI 语义复筛批次失败，已保留该批次进入人工审核：{exc}")

        for row in batch:
            r = dict(row)
            meta = processed.get(str(row.get("video_id") or ""))
            if not meta:
                r.update(llm_status="parse_failed", llm_relevant=True, llm_provider="openrouter", llm_model=client.model)
                kept.append(r)
                continue
            r.update(
                llm_status="ok",
                llm_provider="openrouter",
                llm_model=client.model,
                llm_relevant=bool(meta.get("llm_relevant", True)),
                llm_brand_fit=meta.get("llm_brand_fit"),
                likely_ai_generated=bool(meta.get("likely_ai_generated", row.get("likely_ai_generated", False))),
                likely_low_value_noise=bool(meta.get("likely_low_value", row.get("likely_low_value_noise", False))),
                likely_premium_ad=bool(meta.get("likely_premium_ad", row.get("likely_premium_ad", False))),
                visual_quality_risk=str(meta.get("visual_quality_risk") or row.get("visual_quality_risk") or "low"),
                manual_review_priority=str(meta.get("manual_review_priority") or row.get("manual_review_priority") or "medium"),
                llm_notes=str(meta.get("llm_notes") or "")[:1200],
            )
            if r["llm_relevant"] is False:
                codes = list(r.get("rejection_codes") or [])
                if "llm_not_relevant" not in codes:
                    codes.append("llm_not_relevant")
                r["rejection_codes"] = codes
                r["rejection_stage"] = "llm"
                r["hard_filter_pass"] = False
                rejected.append(r)
            else:
                kept.append(r)
    return kept, rejected, warnings
