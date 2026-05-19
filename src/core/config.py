from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ..utils import PROJECT_ROOT, load_yaml_mapping


APP_CONFIG_PATH = PROJECT_ROOT / "config" / "app.yaml"
LABELS_CONFIG_PATH = PROJECT_ROOT / "config" / "labels.yaml"


def load_app_config(path: Path | str = APP_CONFIG_PATH) -> Dict[str, Any]:
    data = load_yaml_mapping(path) if Path(path).exists() else {}
    data.setdefault("app", {})
    data.setdefault("youtube", {})
    data.setdefault("filters", {})
    data.setdefault("tasks", {})
    data.setdefault("review", {})
    return data


def url_analysis_compat_config() -> Dict[str, Any]:
    review = load_app_config().get("review") or {}
    return {
        "url_analysis": {
            "max_description_chars": 1500,
            "include_thumbnails": True,
            "include_tags": True,
            "include_format_info": True,
            "skip_unavailable": False,
        },
        "feedback_analysis": {
            "min_sample_size_for_strategy": int(review.get("min_sample_size_for_strategy") or 20),
            "high_pass_rate_threshold": float(review.get("high_pass_rate_threshold") or 0.4),
            "low_pass_rate_threshold": float(review.get("low_pass_rate_threshold") or 0.1),
            "min_count_for_keyword_stats": int(review.get("min_count_for_keyword_stats") or 3),
        },
    }


def product_status() -> Dict[str, Any]:
    cfg = load_app_config()
    return {
        "app": cfg.get("app") or {},
        "youtube": cfg.get("youtube") or {},
        "filters": cfg.get("filters") or {},
    }
