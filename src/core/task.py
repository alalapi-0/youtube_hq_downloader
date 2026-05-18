from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class PipelineOptions:
    ai_enabled: bool = True
    use_network: bool = True
    offline_candidates_path: Path | None = None
    task_id: str | None = None
    max_results_per_query: int | None = None


@dataclass
class PipelineResult:
    task_id: str
    task_dir: Path
    summary: Dict[str, Any]
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
