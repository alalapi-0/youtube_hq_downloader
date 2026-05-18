from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..utils import PROJECT_ROOT
from .config import load_app_config


def output_root() -> Path:
    rel = str(((load_app_config().get("tasks") or {}).get("output_root")) or "output/tasks")
    p = Path(rel)
    return p if p.is_absolute() else PROJECT_ROOT / p


def next_task_id(now: datetime | None = None) -> str:
    now = now or datetime.now()
    prefix = f"task_{now.strftime('%Y%m%d')}"
    root = output_root()
    root.mkdir(parents=True, exist_ok=True)
    nums = []
    for child in root.glob(prefix + "_*"):
        tail = child.name.rsplit("_", 1)[-1]
        if tail.isdigit():
            nums.append(int(tail))
    return f"{prefix}_{(max(nums) + 1 if nums else 1):03d}"


def create_task_dir(task_id: str | None = None) -> Path:
    tid = task_id or next_task_id()
    path = output_root() / tid
    path.mkdir(parents=True, exist_ok=True)
    return path


def latest_task_dir() -> Path | None:
    root = output_root()
    if not root.exists():
        return None
    candidates = [p for p in root.iterdir() if p.is_dir() and (p / "run_summary.json").exists()]
    if not candidates:
        return None
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]


def write_latest_task(task_dir: Path) -> None:
    marker = output_root() / ".last_task.json"
    marker.write_text(json.dumps({"task_dir": str(task_dir)}, ensure_ascii=False, indent=2), encoding="utf-8")


def task_paths(task_dir: Path) -> dict[str, Path]:
    return {
        "user_request": task_dir / "user_request.txt",
        "search_plan": task_dir / "search_plan.yaml",
        "candidates_raw": task_dir / "candidates_raw.jsonl",
        "url_analysis": task_dir / "url_analysis.jsonl",
        "rule_filtered": task_dir / "rule_filtered.jsonl",
        "llm_filtered": task_dir / "llm_filtered.jsonl",
        "final_candidates": task_dir / "final_candidates.jsonl",
        "rejected": task_dir / "rejected.jsonl",
        "review_sheet_csv": task_dir / "review_sheet.csv",
        "review_sheet_md": task_dir / "review_sheet.md",
        "search_seed_links_csv": task_dir / "search_seed_links.csv",
        "search_seed_links_md": task_dir / "search_seed_links.md",
        "manual_reviewed": task_dir / "manual_reviewed.jsonl",
        "feedback_md": task_dir / "feedback_analysis.md",
        "feedback_json": task_dir / "feedback_analysis.json",
        "next_search_plan": task_dir / "next_search_plan.yaml",
        "run_summary_json": task_dir / "run_summary.json",
        "run_summary_md": task_dir / "run_summary.md",
    }
