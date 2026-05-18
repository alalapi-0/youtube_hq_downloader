from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

import yaml

from ..core.config import load_app_config
from ..utils import PROJECT_ROOT, clean_text, load_yaml_mapping
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


def _as_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, tuple):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        raw = value.replace("，", ",").replace("、", ",").replace(";", ",").replace("\n", ",")
        return [x.strip() for x in raw.split(",") if x.strip()]
    return []


def _to_int(value: Any, default: int) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(str(value)))
        except (TypeError, ValueError):
            return default


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y", "是", "需要", "require", "required")


def _duration_from_text(value: Any, fallback: Dict[str, Any]) -> Dict[str, int]:
    text = clean_text(value)
    m = re.search(r"(\d+)\s*(?:-|到|至|~|～)\s*(\d+)", text)
    if not m:
        return {
            "min_seconds": _to_int(fallback.get("min_seconds"), 20),
            "max_seconds": _to_int(fallback.get("max_seconds"), 180),
        }
    return {"min_seconds": int(m.group(1)), "max_seconds": int(m.group(2))}


def normalize_search_plan(plan: Dict[str, Any], user_request: str = "") -> Dict[str, Any]:
    fallback = fallback_search_plan(user_request, warning="normalized_fallback")
    src = plan if isinstance(plan, dict) else {}
    out: Dict[str, Any] = dict(src)

    if not isinstance(out.get("project"), dict):
        out["project"] = fallback["project"]

    glob = out.get("global_rules") if isinstance(out.get("global_rules"), dict) else {}
    fb_glob = fallback["global_rules"]
    out["global_rules"] = {
        "max_results_per_keyword": _to_int(glob.get("max_results_per_keyword"), int(fb_glob["max_results_per_keyword"])),
        "default_region_code": str(glob.get("default_region_code") or fb_glob["default_region_code"]),
        "default_relevance_language": str(glob.get("default_relevance_language") or fb_glob["default_relevance_language"]),
    }

    duration = out.get("duration")
    fb_dur = fallback["duration"]
    if isinstance(duration, dict):
        out["duration"] = {
            "min_seconds": _to_int(duration.get("min_seconds"), int(fb_dur["min_seconds"])),
            "max_seconds": _to_int(duration.get("max_seconds"), int(fb_dur["max_seconds"])),
        }
    else:
        out["duration"] = _duration_from_text(duration or user_request, fb_dur)

    resolution = out.get("resolution")
    fb_res = fallback["resolution"]
    if isinstance(resolution, dict):
        require_4k = resolution.get("require_4k")
        if require_4k is None:
            require_4k = "4k" in clean_text(resolution).lower() or "2160" in clean_text(resolution).lower()
        else:
            require_4k = _to_bool(require_4k)
        out["resolution"] = {
            "require_4k": bool(require_4k),
            "min_height": _to_int(resolution.get("min_height"), 2160 if require_4k else 0) or None,
            "allow_text_evidence_when_format_unknown": bool(resolution.get("allow_text_evidence_when_format_unknown", True)),
            "allow_format_probe": bool(resolution.get("allow_format_probe", True)),
        }
    else:
        text = clean_text(resolution or user_request).lower()
        require_4k = any(x in text for x in ("4k", "2160", "uhd", "ultra hd"))
        out["resolution"] = {
            "require_4k": require_4k or bool(fb_res.get("require_4k")),
            "min_height": 2160 if (require_4k or fb_res.get("require_4k")) else None,
            "allow_text_evidence_when_format_unknown": True,
            "allow_format_probe": True,
        }

    pn = out.get("positive_negative_keywords")
    fb_pn = fallback["positive_negative_keywords"]
    if isinstance(pn, dict):
        suggested = _as_list(pn.get("suggested_negative_keywords"))
        out["positive_negative_keywords"] = {
            "negative_keywords_file": str(pn.get("negative_keywords_file") or fb_pn["negative_keywords_file"]),
            "brand_positive_keywords_file": str(pn.get("brand_positive_keywords_file") or fb_pn["brand_positive_keywords_file"]),
            "suggested_negative_keywords": suggested or list(fb_pn["suggested_negative_keywords"]),
        }
    else:
        suggested = _as_list(pn)
        out["positive_negative_keywords"] = dict(fb_pn)
        if suggested:
            out["positive_negative_keywords"]["suggested_negative_keywords"] = suggested

    tasks_out: List[Dict[str, Any]] = []
    tasks_raw = out.get("tasks") if isinstance(out.get("tasks"), list) else []
    fb_task = fallback["tasks"][0]
    for idx, task in enumerate(tasks_raw):
        if not isinstance(task, dict):
            continue
        keywords = _as_list(task.get("keywords")) or list(fb_task["keywords"])
        brands = _as_list(task.get("brands"))
        preferred = _as_list(task.get("preferred_channels"))
        tasks_out.append(
            {
                "id": str(task.get("id") or f"task_{idx}"),
                "category": str(task.get("category") or fb_task["category"]),
                "subcategory": str(task.get("subcategory") or fb_task["subcategory"]),
                "keywords": list(dict.fromkeys(keywords)),
                "brands": list(dict.fromkeys(brands)),
                "preferred_channels": list(dict.fromkeys(preferred)),
                "max_results_per_keyword": _to_int(
                    task.get("max_results_per_keyword"),
                    int(out["global_rules"]["max_results_per_keyword"]),
                ),
                "region_code": str(task.get("region_code") or out["global_rules"]["default_region_code"]),
                "relevance_language": str(task.get("relevance_language") or out["global_rules"]["default_relevance_language"]),
            }
        )
    out["tasks"] = tasks_out or fallback["tasks"]
    return out


def fallback_search_plan(user_request: str, *, warning: str = "") -> Dict[str, Any]:
    user_request = clean_text(user_request)
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
    user_request = clean_text(user_request)
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
            return normalize_search_plan(parsed, user_request), warnings
        warnings.append("OpenRouter 返回的搜索计划结构不完整，已使用规则模式。")
    except (OpenRouterError, Exception) as exc:
        warnings.append(f"OpenRouter 搜索计划生成失败，已使用规则模式：{exc}")
    return fallback_search_plan(user_request, warning="openrouter_failed"), warnings
