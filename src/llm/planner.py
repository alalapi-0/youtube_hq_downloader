from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

import yaml

from ..core.config import load_app_config
from ..utils import PROJECT_ROOT, load_yaml_mapping
from .openrouter_client import OpenRouterClient, OpenRouterError
from .prompts import PLANNER_SYSTEM


def _parse_yaml(raw: str) -> Dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:yaml)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("LLM did not return a YAML mapping")
    return data


def _brand_names() -> List[str]:
    brands = load_yaml_mapping(PROJECT_ROOT / "config" / "brands.yaml")
    out: List[str] = []
    for val in brands.values():
        if isinstance(val, dict):
            out.extend(str(x) for x in (val.get("brand_names") or []) if str(x).strip())
    return out


def fallback_search_plan(user_request: str, *, warning: str = "") -> Dict[str, Any]:
    app = load_app_config()
    yt = app.get("youtube") or {}
    tasks = app.get("tasks") or {}
    text = user_request.lower()
    picked = [b for b in _brand_names() if b.lower() in text]
    if not picked:
        picked = []

    keywords = [
        "official commercial",
        "campaign film",
        "product film",
        "brand film",
        "studio lighting",
        "macro product film",
    ]
    if "perfume" in text or "香水" in text:
        keywords.extend(["perfume commercial", "fragrance campaign film"])
    if "luxury" in text or "奢侈" in text or "高端" in text:
        keywords.extend(["luxury campaign film", "luxury product commercial"])

    min_sec = 20
    max_sec = 180
    m = re.search(r"(\d+)\s*(?:-|到|至)\s*(\d+)\s*秒", user_request)
    if m:
        min_sec = int(m.group(1))
        max_sec = int(m.group(2))

    plan = {
        "project": {"name": "ad-url-scout"},
        "global_rules": {
            "max_results_per_keyword": int(yt.get("default_max_results_per_query") or 10),
            "default_region_code": str(yt.get("default_region_code") or "US"),
            "default_relevance_language": str(yt.get("default_relevance_language") or "en"),
        },
        "duration": {"min_seconds": min_sec, "max_seconds": max_sec},
        "resolution": {
            "require_4k": "4k" in text or "2160" in text,
            "min_height": 2160 if ("4k" in text or "2160" in text) else None,
            "allow_text_evidence_when_format_unknown": True,
            "allow_format_probe": True,
        },
        "positive_negative_keywords": {
            "negative_keywords_file": "config/filters.yaml",
            "brand_positive_keywords_file": "config/brands.yaml",
            "suggested_negative_keywords": ["ai generated", "review", "unboxing", "vlog", "compilation", "reupload"],
        },
        "tasks": [
            {
                "id": "main_request",
                "category": str(tasks.get("default_category") or "campaigns"),
                "subcategory": str(tasks.get("default_subcategory") or "product"),
                "keywords": list(dict.fromkeys(keywords)),
                "brands": picked,
                "preferred_channels": [],
                "max_results_per_keyword": int(yt.get("default_max_results_per_query") or 10),
                "region_code": str(yt.get("default_region_code") or "US"),
                "relevance_language": str(yt.get("default_relevance_language") or "en"),
            }
        ],
    }
    if warning:
        plan["_planner_warning"] = warning
    return plan


def generate_search_plan(user_request: str, *, use_ai: bool = True) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    client = OpenRouterClient()
    if not use_ai:
        return fallback_search_plan(user_request, warning="rule_mode"), ["AI 增强已关闭，使用规则模式生成搜索计划。"]
    if not client.is_configured():
        msg = "未检测到 OPENROUTER_API_KEY，使用规则模式生成搜索计划，命中率可能较低。"
        return fallback_search_plan(user_request, warning="missing_openrouter_key"), [msg]

    brand_hint = yaml.safe_dump(load_yaml_mapping(PROJECT_ROOT / "config" / "brands.yaml"), allow_unicode=True, sort_keys=False)
    input_text = yaml.safe_dump(
        {
            "user_request": user_request,
            "available_brand_config": brand_hint[:4000],
            "default_app_config": load_app_config(),
        },
        allow_unicode=True,
        sort_keys=False,
    )
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM},
        {"role": "user", "content": "USER_REQUEST_AND_CONFIG:\n```yaml\n" + input_text + "\n```"},
    ]
    try:
        parsed, _raw, _cached = client.chat_cached(
            skill_name="query_planner",
            input_text=input_text,
            messages=messages,
            parser=_parse_yaml,
        )
        if isinstance(parsed, dict) and isinstance(parsed.get("tasks"), list):
            return parsed, warnings
        warnings.append("OpenRouter 返回的搜索计划结构不完整，已使用规则模式。")
    except (OpenRouterError, Exception) as exc:
        warnings.append(f"OpenRouter 搜索计划生成失败，已使用规则模式：{exc}")
    return fallback_search_plan(user_request, warning="openrouter_failed"), warnings
