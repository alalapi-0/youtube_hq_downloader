from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import yaml

from ..core.config import load_app_config
from ..utils import clean_text
from .openrouter_client import OpenRouterClient, OpenRouterError


VIMEO_VIDEO_URL_RE = re.compile(r"^https?://(?:www\.)?vimeo\.com/(?:[^/?#]+/)*\d{6,}(?:[?#].*)?$", re.I)
VIMEO_ALLOWED_DOMAINS = ["vimeo.com"]


def is_vimeo_video_url(url: str) -> bool:
    return bool(VIMEO_VIDEO_URL_RE.search(str(url or "").strip()))


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return None
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1", "是"}:
        return True
    if text in {"false", "no", "n", "0", "否"}:
        return False
    return None


def _parse_candidates(raw: str) -> List[Dict[str, Any]]:
    text = _strip_fences(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = yaml.safe_load(text)
    if isinstance(data, dict):
        items = data.get("candidates") or data.get("urls") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []
    rows: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("video_url") or "").strip()
        if not is_vimeo_video_url(url):
            continue
        title = clean_text(item.get("title") or "")
        reason = clean_text(item.get("reason") or item.get("evidence") or "")
        resolution_height = item.get("resolution_height") or item.get("max_height") or item.get("max_format_height")
        duration_seconds = item.get("duration_seconds")
        published_at = item.get("published_at") or item.get("publish_date") or item.get("published_date") or item.get("upload_date")
        resolution_evidence = clean_text(item.get("resolution_evidence") or item.get("quality_evidence") or "")
        duration_evidence = clean_text(item.get("duration_evidence") or item.get("duration") or "")
        date_evidence = clean_text(item.get("date_evidence") or "")
        commercial_feature_evidence = clean_text(
            item.get("commercial_feature_evidence")
            or item.get("advertisement_evidence")
            or item.get("campaign_evidence")
            or ""
        )
        rows.append(
            {
                "source_platform": "vimeo",
                "canonical_url": url.split("#", 1)[0],
                "video_url": url.split("#", 1)[0],
                "title": title,
                "description": reason,
                "description_snippet": reason[:240],
                "channel_title": clean_text(item.get("channel_title") or item.get("creator") or ""),
                "brand": clean_text(item.get("brand") or ""),
                "category": "campaigns",
                "subcategory": "product",
                "matched_keywords": [clean_text(item.get("query_used") or item.get("query") or "")],
                "query_used": clean_text(item.get("query_used") or item.get("query") or ""),
                "llm_status": "web_search_found",
                "llm_relevant": True,
                "llm_notes": reason,
                "confidence": item.get("confidence"),
                "max_format_height": resolution_height,
                "resolution_height": resolution_height,
                "resolution_evidence": resolution_evidence,
                "duration_seconds": duration_seconds,
                "duration_evidence": duration_evidence,
                "published_at": published_at,
                "date_evidence": date_evidence,
                "commercial_feature_evidence": commercial_feature_evidence,
                "contains_advertisement": _as_bool(item.get("contains_advertisement") or item.get("is_advertisement")),
            }
        )
    return rows


def scout_urls_with_openrouter(user_request: str, *, target_count: int | None = None) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, Any]]:
    cfg = load_app_config()
    web_cfg = cfg.get("web_search") if isinstance(cfg.get("web_search"), dict) else {}
    target = int(target_count or web_cfg.get("target_url_count") or 40)
    max_results = int(web_cfg.get("max_results") or 8)
    max_total = int(web_cfg.get("max_total_results") or 40)
    engine = str(web_cfg.get("engine") or "parallel")
    allowed_domains = VIMEO_ALLOWED_DOMAINS

    client = OpenRouterClient()
    if not client.is_configured():
        raise OpenRouterError("未检测到 OPENROUTER_API_KEY。AI Web Search 寻源需要 OpenRouter API Key。")

    prompt = {
        "user_request": clean_text(user_request),
        "current_date": datetime.now(timezone.utc).date().isoformat(),
        "target_url_count": target,
        "allowed_domains": allowed_domains,
        "hard_constraints": {
            "platform": "vimeo.com only",
            "resolution": "must be explicitly 4K / 2160p / UHD; discard if only 720p/1080p/HD or unknown",
            "duration": "must be 60 seconds or shorter; discard if duration is unknown or longer",
            "published_at": "must be within the last 2 years; discard if publish/upload date is unknown or older",
            "commercial_feature": (
                "must have explicit advertisement/campaign/commercial/product-film evidence, or production credits "
                "such as Agency, Creative Director, Art Director, Director, Production Company, DOP, Editor, Colorist, Post, or VFX"
            ),
        },
        "search_focus": [
            'site:vimeo.com "This video contains an advertisement" "4K"',
            'site:vimeo.com "campaign" "4K" "Agency"',
            'site:vimeo.com "product film" "4K" "Production Company"',
            'site:vimeo.com "commercial" "4K" "Director"',
            'site:vimeo.com "Fall 2025 Campaign" "4K"',
        ],
        "rules": [
            "Use web search. Do not invent URLs.",
            "Return only real Vimeo video page URLs from vimeo.com.",
            "Never return YouTube, youtu.be, Shorts, playlist, channel, search, Google, or non-Vimeo URLs.",
            "Only include candidates with evidence that the page/video is 4K, 60 seconds or shorter, and published/uploaded within the last 2 years.",
            "Only include candidates with commercial advertising evidence: advertisement badge, campaign/commercial/product film wording, or production-credit metadata.",
            "If any of resolution, duration, publish date, or commercial feature evidence cannot be verified from search/page evidence, do not include that URL.",
            "Prefer official brand ads, campaign films, product films, fragrance films, jewelry/watch films, luxury commercials.",
            "Strong positive page-text signals include: Agency:, Creative Director, Art Director, Director:, Production Company:, DOP, Editor:, Colorist, Post:, VFX, Fall/Spring/Summer campaign.",
            "Avoid reviews, unboxing, vlogs, AI generated content, compilations, reels/showreels unless the result page is the actual ad video.",
            "Return JSON only with key candidates.",
        ],
        "candidate_schema": {
            "url": "real Vimeo video URL, for example https://vimeo.com/123456789",
            "title": "page/video title",
            "platform": "vimeo",
            "brand": "brand if inferable",
            "query_used": "search query that found it",
            "reason": "short reason grounded in search result text",
            "resolution_height": "integer height such as 2160, only when verifiable",
            "resolution_evidence": "short text evidence for 4K/2160p/UHD",
            "duration_seconds": "integer duration in seconds, must be <= 60",
            "duration_evidence": "short text evidence for duration",
            "published_at": "YYYY-MM-DD publish/upload date, must be within last 2 years",
            "date_evidence": "short text evidence for publish/upload date",
            "contains_advertisement": "true only if page/search evidence says it contains an advertisement",
            "commercial_feature_evidence": "short evidence for advertisement/campaign/commercial/product-film/production-credit status",
            "confidence": "0-1 if inferable",
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                "You are an advertising video URL scout. Use web search to find real Vimeo video URLs. "
                "Return ONLY JSON, no markdown, no commentary. Never fabricate URLs. "
                "YouTube and all non-Vimeo URLs are forbidden. "
                "Every candidate must satisfy hard constraints: Vimeo only, explicit 4K/2160p/UHD evidence, "
                "duration <= 60 seconds, published within the last 2 years, and explicit commercial advertising evidence."
            ),
        },
        {"role": "user", "content": "WEB_URL_SCOUT_REQUEST:\n```yaml\n" + yaml.safe_dump(prompt, allow_unicode=True, sort_keys=False) + "\n```"},
    ]
    tools = [
        {
            "type": "openrouter:web_search",
            "parameters": {
                "engine": engine,
                "max_results": max_results,
                "max_total_results": max_total,
                "search_context_size": str(web_cfg.get("search_context_size") or "medium"),
                "allowed_domains": allowed_domains,
            },
        }
    ]
    raw = client.chat(messages, tools=tools, temperature=0.1, max_tokens=int(web_cfg.get("max_output_tokens") or 6000))
    rows = _parse_candidates(raw)
    warnings: List[str] = []
    if not rows:
        warnings.append("OpenRouter Web Search 未返回可校验的视频 URL。")
    meta = {
        "engine": engine,
        "max_results": max_results,
        "max_total_results": max_total,
        "allowed_domains": allowed_domains,
        "raw_candidate_count": len(rows),
    }
    return rows[:target], warnings, meta
