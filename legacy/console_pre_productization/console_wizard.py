from __future__ import annotations

import copy
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .search_plan_builder import build_search_plan_from_tasks, dump_search_plan
from .utils import PROJECT_ROOT


def log_console_event(message: str) -> None:
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "console_runs.log"
    ts = datetime.now(timezone.utc).isoformat()
    safe = (message or "").replace("\n", " ").strip()
    if len(safe) > 2000:
        safe = safe[:2000] + "…"
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{ts} {safe}\n")


def ensure_dotenv_from_example() -> bool:
    """若缺 .env 且存在 .env.example，则复制。返回是否新建。"""
    env_p = PROJECT_ROOT / ".env"
    ex_p = PROJECT_ROOT / ".env.example"
    if env_p.exists():
        return False
    if not ex_p.exists():
        return False
    shutil.copy(ex_p, env_p)
    return True


def _parse_env_lines(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def merge_env_key(key: str, value: str) -> None:
    ensure_dotenv_from_example()
    env_p = PROJECT_ROOT / ".env"
    if not env_p.exists():
        env_p.write_text("", encoding="utf-8")
    cur = env_p.read_text(encoding="utf-8")
    lines = cur.splitlines()
    new_lines: list[str] = []
    found = False
    prefix = f"{key}="
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(prefix) or stripped.startswith(f"{key} ="):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}")
    env_p.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")


def merge_missing_keys_from_example() -> list[str]:
    """把 .env.example 中存在但 .env 缺失的键补上（不覆盖已有值）。"""
    env_p = PROJECT_ROOT / ".env"
    ex_p = PROJECT_ROOT / ".env.example"
    if not ex_p.exists():
        return []
    ensure_dotenv_from_example()
    cur_text = env_p.read_text(encoding="utf-8") if env_p.exists() else ""
    current = _parse_env_lines(cur_text)
    example = _parse_env_lines(ex_p.read_text(encoding="utf-8"))
    added: list[str] = []
    for k, v in example.items():
        if k not in current or not str(current.get(k, "")).strip():
            merge_env_key(k, v)
            added.append(k)
    return added


def apply_max_results_cap(plan: dict[str, Any], cap: int) -> dict[str, Any]:
    p = copy.deepcopy(plan)
    gr = p.get("global_rules") if isinstance(p.get("global_rules"), dict) else {}
    gr = dict(gr)
    gr["max_results_per_keyword"] = int(cap)
    p["global_rules"] = gr
    tasks = p.get("tasks")
    if isinstance(tasks, list):
        for t in tasks:
            if isinstance(t, dict):
                t["max_results_per_keyword"] = int(cap)
    return p


def write_search_tasks_temp(project: dict[str, Any], tasks: list[dict[str, Any]], dest: Path) -> None:
    doc = {"project": project, "tasks": tasks}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")


def build_and_dump_plan_from_tasks_yaml(tasks_yaml: Path, output_plan: Path) -> dict[str, Any]:
    plan = build_search_plan_from_tasks(tasks_yaml.resolve())
    dump_search_plan(output_plan, plan)
    return plan


def interactive_task_document(
    *,
    task_id: str,
    category: str,
    subcategory: str,
    keywords: list[str],
    brands: list[str],
    region_code: str,
    relevance_language: str,
    max_results_per_keyword: int,
    preferred_channels: list[str] | None = None,
) -> dict[str, Any]:
    preferred_channels = preferred_channels or []
    task = {
        "id": task_id,
        "category": category,
        "subcategory": subcategory,
        "keywords": keywords,
        "brands": brands,
        "preferred_channels": preferred_channels,
        "max_results_per_keyword": int(max_results_per_keyword),
        "region_code": region_code,
        "relevance_language": relevance_language,
    }
    project = {"name": "console_wizard"}
    return {"project": project, "tasks": [task]}


def count_plan_stats(plan: dict[str, Any]) -> tuple[int, int]:
    tasks = plan.get("tasks") or []
    if not isinstance(tasks, list):
        return 0, 0
    n_tasks = len([t for t in tasks if isinstance(t, dict)])
    glob = plan.get("global_rules") or {}
    default_cap = int(glob.get("max_results_per_keyword") or 10) if isinstance(glob, dict) else 10
    kw_total = 0
    for t in tasks:
        if not isinstance(t, dict):
            continue
        kws = t.get("keywords") or []
        brands = t.get("brands") or []
        base = len([x for x in kws if str(x).strip()])
        b = len([x for x in brands if str(x).strip()])
        expanded = base * (1 + b) if b else base
        kw_total += expanded
    upper_bound = kw_total * default_cap
    return n_tasks, upper_bound
