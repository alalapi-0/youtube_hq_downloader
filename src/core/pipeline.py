from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .. import review_feedback_analyzer, review_schema, search_strategy_from_feedback, url_analyzer
from ..core.dedupe import dedupe_records
from ..core.hard_constraints import apply_hard_constraints, hard_constraints_from_config
from ..utils import clean_for_serialization, clean_text, coerce_candidate, read_jsonl, write_jsonl
from ..youtube_collect import collect_search_page_urls, enrich_video_metadata, ytdlp_available
from .config import LABELS_CONFIG_PATH, load_app_config, url_analysis_compat_config
from .paths import create_task_dir, task_paths, write_latest_task
from .task import PipelineOptions, PipelineResult


def _read_rows(path: Path) -> List[Dict[str, Any]]:
    return [coerce_candidate(r) for r in read_jsonl(path)]


def _summary_markdown(summary: Dict[str, Any]) -> str:
    lines = [
        "# 任务摘要",
        "",
        f"- 任务 ID：`{summary['task_id']}`",
        f"- 创建时间：{summary['created_at']}",
        f"- 搜索结果页：{summary['search_page_count']}",
        f"- 采集到视频 URL：{summary['collected_url_count']}",
        f"- 元数据读取成功：{summary['metadata_success_count']}",
        f"- 硬性条件丢弃：{summary['hard_constraint_rejected_count']}",
        f"- 本地查重后保留：{summary['final_count']}",
        f"- 本地重复/无效：{summary['duplicate_count']}",
        f"- 需要人工审核：{summary['final_count']}",
        "",
        "## 输出文件",
        f"- 人工审核表：`{summary['review_sheet_csv']}`",
        f"- Markdown 预览：`{summary['review_sheet_md']}`",
        f"- 采集到的原始 URL：`{summary['collected_urls_path']}`",
        f"- 结构化数据：`{summary['final_candidates_path']}`",
        f"- 拒绝明细：`{summary['rejected_path']}`",
        "",
        "## 下一步",
    ]
    lines.extend(f"- {x}" for x in summary.get("next_steps") or [])
    warnings = summary.get("warnings") or []
    errors = summary.get("errors") or []
    if warnings:
        lines.extend(["", "## 提醒"])
        lines.extend(f"- {x}" for x in warnings)
    if errors:
        lines.extend(["", "## 错误"])
        lines.extend(f"- {x}" for x in errors)
    lines.append("")
    return "\n".join(lines)


def _write_summary(paths: Dict[str, Path], summary: Dict[str, Any]) -> None:
    clean_summary = clean_for_serialization(summary)
    paths["run_summary_json"].write_text(json.dumps(clean_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths["run_summary_md"].write_text(clean_text(_summary_markdown(clean_summary)), encoding="utf-8")


def run_new_task(user_request: str = "", options: PipelineOptions | None = None) -> PipelineResult:
    options = options or PipelineOptions()
    app_config = load_app_config()
    youtube_cfg = app_config.get("youtube") if isinstance(app_config.get("youtube"), dict) else {}
    filters = hard_constraints_from_config(app_config)
    task_dir = create_task_dir(options.task_id)
    paths = task_paths(task_dir)
    warnings: List[str] = []
    errors: List[str] = []
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    task_id = task_dir.name

    user_request = clean_text(user_request).strip()
    search_urls = [clean_text(x).strip() for x in options.search_page_urls if clean_text(x).strip()]
    paths["user_request"].write_text(user_request + "\n", encoding="utf-8")
    paths["search_pages"].write_text("\n".join(search_urls) + ("\n" if search_urls else ""), encoding="utf-8")

    missing_ytdlp = not ytdlp_available() and not options.offline_candidates_path
    if missing_ytdlp:
        errors.append("未检测到 yt-dlp。请先执行：python3 -m pip install -r requirements.txt")

    collected_rows: List[Dict[str, Any]] = []
    collect_stats: Dict[str, int] = {"search_pages": len(search_urls), "entries_seen": 0, "video_urls": 0, "failed_pages": 0}
    metadata_stats: Dict[str, int] = {"total": 0, "ok": 0, "failed": 0}
    max_entries = int(options.max_entries_per_search_page or youtube_cfg.get("max_entries_per_search_page") or 80)

    if options.offline_candidates_path:
        collected_rows = _read_rows(Path(options.offline_candidates_path))
        collect_stats = {"search_pages": 0, "entries_seen": len(collected_rows), "video_urls": len(collected_rows), "failed_pages": 0}
        metadata_rows = collected_rows
        metadata_stats = {"total": len(collected_rows), "ok": len(collected_rows), "failed": 0}
        warnings.append(f"离线模式：使用示例候选数据 {options.offline_candidates_path}")
    elif missing_ytdlp:
        metadata_rows = []
    elif not search_urls:
        metadata_rows = []
        errors.append("没有提供 YouTube 搜索结果页 URL。")
    else:
        collected_rows, collect_warnings, collect_stats = collect_search_page_urls(
            search_urls,
            youtube_cfg=youtube_cfg,
            max_entries_per_page=max_entries,
        )
        warnings.extend(collect_warnings)
        metadata_rows, metadata_warnings, metadata_stats = enrich_video_metadata(collected_rows, youtube_cfg=youtube_cfg)
        warnings.extend(metadata_warnings[:20])
        if len(metadata_warnings) > 20:
            warnings.append(f"还有 {len(metadata_warnings) - 20} 条元数据读取失败已省略显示。")
        if metadata_stats.get("failed", 0) and not youtube_cfg.get("cookies_enabled", False):
            warnings.append("如果失败原因包含 not a bot / Sign in，可在控制台启用 Chrome Cookie 或 cookies.txt 后重试。")

    collected_rows = [coerce_candidate(r) for r in collected_rows]
    metadata_rows = [coerce_candidate(r) for r in metadata_rows]
    write_jsonl(paths["collected_urls"], collected_rows)

    constrained_rows, hard_rejected_rows, hard_stats = apply_hard_constraints(metadata_rows, filters)
    if hard_rejected_rows:
        warnings.append(
            "已按硬性条件丢弃 "
            f"{len(hard_rejected_rows)} 条：必须 4K/2160p、{filters.get('max_duration_seconds', 60)} 秒以内、"
            f"发布时间 {filters.get('published_within_days', 730)} 天内，且标题/描述不含负面词。"
        )

    unique_rows, duplicate_rows, dedupe_stats = dedupe_records(constrained_rows, exclude_task_dir=task_dir)
    write_jsonl(paths["candidates_raw"], unique_rows)
    write_jsonl(paths["duplicates"], duplicate_rows)
    paths["dedupe_report"].write_text(json.dumps(dedupe_stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    analysis_rows = url_analyzer.analyze_url_records(
        unique_rows,
        cfg=url_analysis_compat_config(),
        offline=True,
    )
    write_jsonl(paths["url_analysis"], analysis_rows)
    write_jsonl(paths["rule_filtered"], analysis_rows)
    write_jsonl(paths["filtered"], analysis_rows)
    write_jsonl(paths["rejected"], [*hard_rejected_rows, *duplicate_rows])
    write_jsonl(paths["final_candidates"], analysis_rows)

    url_analyzer.export_review_sheet(
        analysis_rows,
        output_csv=paths["review_sheet_csv"],
        output_md=paths["review_sheet_md"],
    )

    summary = {
        "task_id": task_id,
        "created_at": created_at,
        "user_request": user_request,
        "search_page_count": len(search_urls),
        "search_pages_path": str(paths["search_pages"]),
        "collected_urls_path": str(paths["collected_urls"]),
        "collected_url_count": len(collected_rows),
        "collection_stats": collect_stats,
        "metadata_stats": metadata_stats,
        "metadata_success_count": metadata_stats.get("ok", 0),
        "hard_constraint_rejected_count": len(hard_rejected_rows),
        "hard_constraint_reject_stats": hard_stats,
        "rule_pass_count": len(unique_rows),
        "final_count": len(unique_rows),
        "duplicate_count": len(duplicate_rows),
        "rejected_count": len(hard_rejected_rows) + len(duplicate_rows),
        "review_sheet_csv": str(paths["review_sheet_csv"]),
        "review_sheet_md": str(paths["review_sheet_md"]),
        "final_candidates_path": str(paths["final_candidates"]),
        "rejected_path": str(paths["rejected"]),
        "duplicates_path": str(paths["duplicates"]),
        "dedupe_report_path": str(paths["dedupe_report"]),
        "errors": errors,
        "warnings": warnings,
        "next_steps": [
            "请打开 review_sheet.csv，人工查看候选视频。",
            "填写 manual_status、manual_reject_reasons、manual_notes 后，可回到控制台导入反馈。",
        ],
    }
    _write_summary(paths, summary)
    write_latest_task(task_dir)
    return PipelineResult(task_id=task_id, task_dir=task_dir, summary=summary, warnings=warnings, errors=errors)


def import_feedback_for_task(task_dir: Path, review_csv: Path) -> Dict[str, Any]:
    paths = task_paths(task_dir)
    rows, import_summary = review_schema.import_manual_reviews(
        analysis_path=paths["url_analysis"],
        review_csv_path=review_csv,
        output_path=paths["manual_reviewed"],
        labels_path=LABELS_CONFIG_PATH,
    )
    stats = review_feedback_analyzer.analyze_feedback_file(
        input_path=paths["manual_reviewed"],
        output_md=paths["feedback_md"],
        output_json=paths["feedback_json"],
    )
    search_strategy_from_feedback.generate_rule_based_strategy(
        feedback_json_path=paths["feedback_json"],
        reviewed_jsonl_path=paths["manual_reviewed"],
        output_md=task_dir / "rule_based_feedback_strategy.md",
        output_yaml=paths["next_search_plan"],
    )
    result = {
        "import_summary": import_summary,
        "feedback_summary": stats.get("summary") or {},
        "next_search_plan": str(paths["next_search_plan"]),
        "feedback_md": str(paths["feedback_md"]),
        "warnings": [],
        "reviewed_rows": len(rows),
    }
    (task_dir / "feedback_import_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
