from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .llm_cache import CacheParams, cache_fingerprint, read_cache, write_cache
from .llm_client import ChatMessage, GrokUnsupportedError, openai_compatible_chat_completion, require_non_empty_api_key
from .utils import PROJECT_ROOT, load_yaml_mapping

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


def _cache_dir(llm_cfg: Dict[str, Any]) -> Path:
    rel = (((llm_cfg or {}).get("cache") or {}) or {}).get("directory") or "cache"
    p = Path(rel)
    return p if p.is_absolute() else PROJECT_ROOT / p


def _parse_json_with_retry(raw: str) -> Dict[str, Any]:
    blob = raw.strip()
    errs: List[str] = []
    try:
        return json.loads(blob)
    except Exception as e:
        errs.append(str(e))

    try:
        m = _JSON_FENCE_RE.search(blob)
        if m:
            return json.loads(m.group(1).strip())
    except Exception as e:
        errs.append(str(e))

    try:
        start = blob.find("{")
        end = blob.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(blob[start : end + 1])
    except Exception as e:
        errs.append(str(e))
    joined = "; ".join(errs)
    raise ValueError(f"LLM JSON parse failed: {joined}") from None


def _trunc(text: str, limit: int) -> str:
    t = text or ""
    return t if len(t) <= limit else t[:limit] + "…"


def _batch(records: List[Dict[str, Any]], n: int) -> Iterable[List[Dict[str, Any]]]:
    for i in range(0, len(records), n):
        yield records[i : i + n]


def annotate_candidates_llm(
    records: List[Dict[str, Any]],
    *,
    llm_config_path: Path | str,
    prompts_path: Path | str,
    prompt_version: str,
) -> List[Dict[str, Any]]:
    """
    永不向 CLI 抛出致命异常；批量解析失败则将对应行标记为 `llm_status=parse_failed`。
    """
    llm_cfg = load_yaml_mapping(Path(llm_config_path))
    prompts = load_yaml_mapping(Path(prompts_path))
    cfg = llm_cfg
    provider = str(cfg.get("provider") or "openrouter")
    model = str(cfg.get("model") or "gpt-4o-mini")
    sys_msg = str(prompts.get("candidate_filter_system") or "").strip()

    rows_out: List[Dict[str, Any]] = []

    for batch in list(_batch(records, 20)):
        compact = []
        for r in batch:
            compact.append(
                {
                    "video_id": r.get("video_id"),
                    "title": r.get("title"),
                    "channel_title": r.get("channel_title"),
                    "category": r.get("category"),
                    "subcategory": r.get("subcategory"),
                    "description": _trunc(str(r.get("description") or ""), 900),
                    "positive_keyword_hits": r.get("positive_keyword_hits") or [],
                    "negative_keyword_hits": r.get("negative_keyword_hits") or [],
                    "brand": r.get("brand"),
                }
            )
        inp = json.dumps(compact, ensure_ascii=False)

        fingerprint = cache_fingerprint(
            CacheParams(
                provider=provider,
                model=model,
                skill_name="candidate_filter",
                prompt_version=prompt_version,
                input_text=inp,
            )
        )
        cdir = _cache_dir(cfg)
        cached = read_cache(cdir, fingerprint)
        processed: Dict[str, Dict[str, Any]] = {}
        raw_reply = ""

        if cached and isinstance(cached["parsed"], dict):
            ws = cached["parsed"].get("results")
            if isinstance(ws, list):
                for obj in ws:
                    if isinstance(obj, dict) and obj.get("video_id"):
                        processed[str(obj.get("video_id"))] = obj

        try:
            if not processed:
                try:
                    base, api_key = require_non_empty_api_key(provider, cfg)
                except GrokUnsupportedError as exc:
                    for r in batch:
                        rr = dict(r)
                        rr["llm_status"] = "skipped"
                        rr["llm_provider"] = provider
                        rr["llm_model"] = model
                        rr["llm_notes"] = str(exc)
                        rows_out.append(rr)
                    continue

                raw_reply = openai_compatible_chat_completion(
                    base_url=base,
                    api_key=api_key,
                    model=model,
                    messages=[
                        ChatMessage("system", sys_msg),
                        ChatMessage("user", f"CANDIDATES_JSON:\n{inp}\n"),
                    ],
                    temperature=float(cfg.get("temperature") or 0.2),
                    max_tokens=int(((cfg.get("max_output_tokens") or 2048))),
                )

                try:
                    payload = _parse_json_with_retry(raw_reply)
                except ValueError:
                    raw_reply2 = openai_compatible_chat_completion(
                        base_url=base,
                        api_key=api_key,
                        model=model,
                        messages=[
                            ChatMessage("system", sys_msg + '\nReturn ONLY compact JSON {"results":[...]}'),
                            ChatMessage("user", f"CANDIDATES_JSON:\n{inp}\n"),
                        ],
                        temperature=float(cfg.get("temperature") or 0.15),
                        max_tokens=int(((cfg.get("max_output_tokens") or 2048))),
                    )
                    payload = _parse_json_with_retry(raw_reply2)
                    raw_reply = raw_reply2

                ws = payload.get("results") if isinstance(payload, dict) else None
                if not isinstance(ws, list):
                    raise ValueError("missing results[]")

                for obj in ws:
                    if isinstance(obj, dict) and obj.get("video_id"):
                        processed[str(obj.get("video_id"))] = obj

                meta = {"provider": provider, "model": model, "skill": "candidate_filter"}
                write_cache(
                    cdir,
                    fingerprint,
                    meta=meta,
                    raw_text=raw_reply,
                    parsed={"results": list(processed.values())},
                )

        except Exception:
            processed = {}

        if not processed:
            for r in batch:
                rr = dict(r)
                rr.update(
                    llm_provider=provider,
                    llm_model=model,
                    llm_status="parse_failed",
                    llm_relevant=None,
                    llm_brand_fit=None,
                    likely_ai_generated=r.get("likely_ai_generated", False),
                    likely_low_value_noise=r.get("likely_low_value_noise", False),
                    likely_premium_ad=r.get("likely_premium_ad", False),
                    visual_quality_risk=r.get("visual_quality_risk", "medium"),
                    manual_review_priority=r.get("manual_review_priority", "high"),
                    llm_notes="parse_failed_batch",
                )
                rows_out.append(rr)
            continue

        for r in batch:
            rr = dict(r)
            vid = str(r.get("video_id") or "")
            meta = processed.get(vid) or {}

            rr["llm_provider"] = provider
            rr["llm_model"] = model
            rr["llm_status"] = "ok" if vid in processed else "parse_failed"

            rr["llm_relevant"] = meta.get("llm_relevant", True if vid in processed else None)
            rr["llm_brand_fit"] = meta.get("llm_brand_fit", None)

            rr["likely_ai_generated"] = bool(meta.get("likely_ai_generated", rr.get("likely_ai_generated", False)))
            rr["likely_low_value_noise"] = bool(
                meta.get("likely_low_value", meta.get("likely_low_value_noise", rr.get("likely_low_value_noise", False)))
            )
            rr["likely_premium_ad"] = bool(meta.get("likely_premium_ad", rr.get("likely_premium_ad", False)))

            vqr = meta.get("visual_quality_risk") or rr.get("visual_quality_risk") or "low"
            rr["visual_quality_risk"] = str(vqr)

            mrp = meta.get("manual_review_priority") or rr.get("manual_review_priority") or "medium"
            rr["manual_review_priority"] = str(mrp)

            rr["llm_notes"] = str(meta.get("llm_notes") or rr.get("llm_notes") or "")[:1200]

            rows_out.append(rr)

    return rows_out


def llm_semantic_gate_copy_skipped_defaults(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in records:
        rr = dict(r)
        rr.setdefault("llm_status", "skipped")
        rr.setdefault("llm_relevant", True)
        rr.setdefault("llm_brand_fit", None)
        rr.setdefault("likely_ai_generated", False)
        rr.setdefault("likely_low_value_noise", False)
        rr.setdefault("likely_premium_ad", rr.get("likely_premium_ad", False))
        rr.setdefault("visual_quality_risk", rr.get("visual_quality_risk", "low"))
        rr.setdefault("manual_review_priority", rr.get("manual_review_priority", "medium"))
        rr.setdefault("llm_notes", "")
        rr.setdefault("llm_provider", "")
        rr.setdefault("llm_model", "")
        out.append(rr)
    return out
