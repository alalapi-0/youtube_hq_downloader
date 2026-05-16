from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

from ..utils import PROJECT_ROOT, load_yaml_mapping


APP_CONFIG_PATH = PROJECT_ROOT / "config" / "app.yaml"
FILTERS_CONFIG_PATH = PROJECT_ROOT / "config" / "filters.yaml"
BRANDS_CONFIG_PATH = PROJECT_ROOT / "config" / "brands.yaml"
LABELS_CONFIG_PATH = PROJECT_ROOT / "config" / "labels.yaml"


def load_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env")


def load_app_config(path: Path | str = APP_CONFIG_PATH) -> Dict[str, Any]:
    data = load_yaml_mapping(path) if Path(path).exists() else {}
    data.setdefault("app", {})
    data.setdefault("llm", {})
    data.setdefault("youtube", {})
    data.setdefault("tasks", {})
    data.setdefault("review", {})
    data.setdefault("advanced", {})
    return data


def openrouter_api_key() -> str:
    load_env()
    env_name = str((load_app_config().get("llm") or {}).get("api_key_env") or "OPENROUTER_API_KEY")
    return os.environ.get(env_name, "").strip()


def youtube_api_key() -> str:
    load_env()
    env_name = str((load_app_config().get("youtube") or {}).get("api_key_env") or "YOUTUBE_API_KEY")
    return os.environ.get(env_name, "").strip()


def openrouter_config() -> Dict[str, Any]:
    cfg = load_app_config()
    llm = dict(cfg.get("llm") or {})
    llm.setdefault("provider", "openrouter")
    llm.setdefault("model", "google/gemini-2.5-flash")
    llm.setdefault("base_url", "https://openrouter.ai/api/v1")
    llm.setdefault("api_key_env", "OPENROUTER_API_KEY")
    llm.setdefault("temperature", 0.2)
    llm.setdefault("max_output_tokens", 4096)
    llm.setdefault("cache_enabled", True)
    llm.setdefault("cache_dir", "cache/llm")
    llm.setdefault("prompt_version", "ad-url-scout-v1")
    llm.setdefault("max_items_per_batch", 20)
    return llm


def ai_enabled_by_default() -> bool:
    cfg = load_app_config()
    return bool((cfg.get("llm") or {}).get("enabled", True))


def llm_compat_config() -> Dict[str, Any]:
    llm = openrouter_config()
    return {
        "provider": "openrouter",
        "model": llm["model"],
        "temperature": llm["temperature"],
        "max_output_tokens": llm["max_output_tokens"],
        "env": {
            "openrouter_api_key": llm.get("api_key_env", "OPENROUTER_API_KEY"),
            "openrouter_base_url": "OPENROUTER_BASE_URL",
        },
        "defaults": {"openrouter_base_url": llm.get("base_url", "https://openrouter.ai/api/v1")},
        "cache": {
            "directory": llm.get("cache_dir", "cache/llm"),
            "prompt_version": llm.get("prompt_version", "ad-url-scout-v1"),
        },
    }


def url_analysis_compat_config() -> Dict[str, Any]:
    app = load_app_config()
    yt = app.get("youtube") or {}
    review = app.get("review") or {}
    return {
        "url_analysis": {
            "use_youtube_api": bool(yt.get("use_youtube_api", True)),
            "use_ytdlp_metadata": bool(yt.get("use_ytdlp_metadata", True)),
            "use_webpage_metadata": bool(yt.get("use_webpage_metadata", True)),
            "use_cookie": False,
            "max_description_chars": 1500,
            "include_thumbnails": True,
            "include_tags": True,
            "include_format_info": bool(yt.get("use_format_probe", True)),
            "skip_unavailable": False,
        },
        "review_export": {
            "output_csv": "output/review/review_sheet.csv",
            "output_md": "output/review/review_sheet.md",
            "include_llm_reason": True,
            "include_quality_score": True,
        },
        "feedback_analysis": {
            "min_sample_size_for_strategy": int(review.get("min_sample_size_for_strategy") or 20),
            "high_pass_rate_threshold": float(review.get("high_pass_rate_threshold") or 0.4),
            "low_pass_rate_threshold": float(review.get("low_pass_rate_threshold") or 0.1),
            "min_count_for_keyword_stats": int(review.get("min_count_for_keyword_stats") or 3),
        },
    }


def product_status() -> Dict[str, Any]:
    import shutil

    return {
        "openrouter_configured": bool(openrouter_api_key()),
        "youtube_api_configured": bool(youtube_api_key()),
        "ytdlp_available": bool(shutil.which("yt-dlp")),
        "app": load_app_config().get("app") or {},
    }
