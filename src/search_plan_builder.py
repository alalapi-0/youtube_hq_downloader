from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml

from .utils import PROJECT_ROOT, load_yaml_mapping


def _safe_tasks_from_search_tasks_yaml(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    tasks_raw = data.get("tasks") or []
    if not isinstance(tasks_raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for i, t in enumerate(tasks_raw):
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id") or f"task_{i}")
        item = dict(t)
        item["id"] = tid
        item.setdefault("brands", [])
        item.setdefault("preferred_channels", [])
        item.setdefault("keywords", [])
        if not isinstance(item["keywords"], list):
            item["keywords"] = []
        if not isinstance(item["brands"], list):
            item["brands"] = []
        if not isinstance(item["preferred_channels"], list):
            item["preferred_channels"] = []
        out.append(item)
    return out


def build_search_plan_from_tasks(
    tasks_yaml: Path | str,
    *,
    filter_rules_yaml: Path | str | None = None,
    negative_keywords_yaml: Path | str | None = None,
    brand_whitelist_yaml: Path | str | None = None,
) -> Dict[str, Any]:
    """
    Mechanical merge:`search_tasks*.yaml`（扁平 tasks）→ 完整 `search_plan` 文档树。
    """
    tp = Path(tasks_yaml).resolve()
    base = load_yaml_mapping(tp)

    proj = base.get("project") if isinstance(base.get("project"), dict) else {}
    project_block = proj if proj else {}
    proj_name = str(project_block.get("name") or "youtube_url_sourcing")

    tasks = _safe_tasks_from_search_tasks_yaml(base)

    inferred_global_cap: int | None = None
    for t in tasks:
        mr = t.get("max_results_per_keyword")
        try:
            v = int(mr) if mr not in (None, "") else None
        except (TypeError, ValueError):
            v = None
        if v is None:
            continue
        inferred_global_cap = v if inferred_global_cap is None else max(inferred_global_cap, v)

    dur = {}
    res = {}
    nk_ref: Dict[str, Any] = {
        "negative_keywords_file": "config/negative_keywords.yaml",
        "brand_positive_keywords_file": "config/brand_whitelist.yaml",
        "embedded_hint": [],
    }

    fr_path = Path(filter_rules_yaml).resolve() if filter_rules_yaml else PROJECT_ROOT / "config" / "filter_rules.yaml"
    if fr_path.exists():
        fr = load_yaml_mapping(fr_path)
        dur = fr.get("duration") or {}
        res = fr.get("resolution") or {}
        nk = fr.get("negative_keyword_sources") or {}
        nk_ref["negative_keywords_file"] = str(nk.get("negative_keywords_file") or nk_ref["negative_keywords_file"])
        nk_ref["brand_positive_keywords_file"] = str(
            fr.get("brand_positive_keywords_file") or nk_ref["brand_positive_keywords_file"]
        )

    if negative_keywords_yaml and Path(negative_keywords_yaml).exists():
        nk_data = load_yaml_mapping(Path(negative_keywords_yaml))
        nk_ref["embedded_hint"] = [
            f"ai_content_terms≈{len(nk_data.get('ai_content') or [])}",
            f"low_value_terms≈{len(nk_data.get('low_value_content') or [])}",
            f"high_risk_terms≈{len(nk_data.get('high_risk') or [])}",
        ]

    if brand_whitelist_yaml and Path(brand_whitelist_yaml).exists():
        bk = load_yaml_mapping(Path(brand_whitelist_yaml))
        cats = [k for k, v in bk.items() if isinstance(v, dict) and k != "positive_keywords"]
        if cats:
            nk_ref["brand_categories"] = sorted(set(cats))

    plan: Dict[str, Any] = {
        "project": {"name": proj_name},
        "global_rules": {
            "max_results_per_keyword": int(inferred_global_cap or 10),
            "default_region_code": str((tasks[0] or {}).get("region_code") or "US") if tasks else "US",
            "default_relevance_language": str((tasks[0] or {}).get("relevance_language") or "en") if tasks else "en",
        },
        "duration": dur,
        "resolution": res,
        "positive_negative_keywords": nk_ref,
        "tasks": tasks,
    }
    return plan


def dump_search_plan(path: Path | str, plan: Dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(plan, allow_unicode=True, sort_keys=False)
    p.write_text(text, encoding="utf-8")


def load_search_plan(path: Path | str) -> Dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}
