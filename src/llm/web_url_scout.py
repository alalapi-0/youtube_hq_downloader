from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

import yaml

from ..core.config import load_app_config
from ..utils import clean_text
from .openrouter_client import OpenRouterClient, OpenRouterError


VIDEO_URL_RE = re.compile(
    r"^https?://(?:www\.)?(?:vimeo\.com/(?:[^/?#]+/)*\d{6,}|youtube\.com/watch\?[^#\s]*v=[\w-]{11}(?:[&#?].*)?|youtu\.be/[\w-]{11}(?:[?#].*)?)",
    re.I,
)


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


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
        if not VIDEO_URL_RE.search(url):
            continue
        platform = "vimeo" if "vimeo.com" in url.lower() else "youtube"
        title = clean_text(item.get("title") or "")
        reason = clean_text(item.get("reason") or item.get("evidence") or "")
        rows.append(
            {
                "source_platform": platform,
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
            }
        )
    return rows


def scout_urls_with_openrouter(user_request: str, *, target_count: int | None = None) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, Any]]:
    cfg = load_app_config()
    web_cfg = cfg.get("web_search") if isinstance(cfg.get("web_search"), dict) else {}
    target = int(target_count or web_cfg.get("target_url_count") or 40)
    max_results = int(web_cfg.get("max_results") or 8)
    max_total = int(web_cfg.get("max_total_results") or 40)
    engine = str(web_cfg.get("engine") or "exa")
    allowed_domains = web_cfg.get("allowed_domains") or ["vimeo.com", "youtube.com", "youtu.be"]

    client = OpenRouterClient()
    if not client.is_configured():
        raise OpenRouterError("未检测到 OPENROUTER_API_KEY。AI Web Search 寻源需要 OpenRouter API Key。")

    prompt = {
        "user_request": clean_text(user_request),
        "target_url_count": target,
        "allowed_domains": allowed_domains,
        "rules": [
            "Use web search. Do not invent URLs.",
            "Return only real video page URLs from Vimeo or YouTube.",
            "Prefer official brand ads, campaign films, product films, fragrance films, jewelry/watch films, luxury commercials.",
            "Avoid reviews, unboxing, vlogs, AI generated content, compilations, reels/showreels unless the result page is the actual ad video.",
            "Return JSON only with key candidates.",
        ],
        "candidate_schema": {
            "url": "real Vimeo or YouTube video URL",
            "title": "page/video title",
            "platform": "vimeo or youtube",
            "brand": "brand if inferable",
            "query_used": "search query that found it",
            "reason": "short reason grounded in search result text",
            "confidence": "0-1 if inferable",
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                "You are an advertising video URL scout. Use web search to find real video URLs. "
                "Return ONLY JSON, no markdown, no commentary. Never fabricate URLs."
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
