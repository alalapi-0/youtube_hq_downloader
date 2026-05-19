from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import yaml

from .. import review_feedback_analyzer, review_schema, search_strategy_from_feedback, url_analyzer
from ..core.dedupe import dedupe_records
from ..core.hard_constraints import apply_hard_constraints, hard_constraints_from_config
from ..llm.feedback_analyzer import analyze_feedback_with_openrouter
from ..llm.web_url_scout import is_vimeo_video_url, scout_urls_with_openrouter
from ..llm.openrouter_client import OpenRouterError
from ..utils import clean_for_serialization, clean_text, coerce_candidate, read_jsonl, write_jsonl
from ..vimeo_oembed import enrich_vimeo_oembed_rows
from .config import LABELS_CONFIG_PATH, load_app_config, openrouter_api_key, url_analysis_compat_config
from .paths import create_task_dir, task_paths, write_latest_task
from .task import PipelineOptions, PipelineResult


def _write_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(clean_for_serialization(data), allow_unicode=True, sort_keys=False), encoding="utf-8")


def _read_rows(path: Path) -> List[Dict[str, Any]]:
    return [coerce_candidate(r) for r in read_jsonl(path)]


def _row_url(row: Dict[str, Any]) -> str:
    return str(row.get("canonical_url") or row.get("video_url") or row.get("url") or "")


def _keep_vimeo_only(rows: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
    kept: List[Dict[str, Any]] = []
    dropped = 0
    for row in rows:
        if is_vimeo_video_url(_row_url(row)):
            kept.append(row)
        else:
            dropped += 1
    return kept, dropped


def _summary_markdown(summary: Dict[str, Any]) -> str:
    lines = [
        "# 任务摘要",
        "",
        f"- 任务 ID：`{summary['task_id']}`",
        f"- 创建时间：{summary['created_at']}",
        f"- AI Web Search 找到 URL：{summary['total_candidates']}",
        f"- 硬性条件丢弃：{summary.get('hard_constraint_rejected_count', 0)}",
        f"- 本地查重后保留：{summary['final_count']}",
        f"- 本地重复/无效：{summary.get('duplicate_count', 0)}",
        f"- 需要人工审核：{summary['final_count']}",
        "",
        "## 输出文件",
        f"- 人工审核表：`{summary['review_sheet_csv']}`",
        f"- Markdown 预览：`{summary['review_sheet_md']}`",
        f"- AI 找到的原始 URL：`{summary.get('llm_found_urls_path', '')}`",
        f"- Web Search 原始回复：`{summary.get('web_search_raw_path', '')}`",
        f"- 结构化数据：`{summary['final_candidates_path']}`",
        f"- 重复 URL：`{summary.get('duplicates_path', '')}`",
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


def run_new_task(user_request: str, options: PipelineOptions | None = None) -> PipelineResult:
    user_request = clean_text(user_request).strip()
    options = options or PipelineOptions()
    app_config = load_app_config()
    hard_constraints = hard_constraints_from_config(app_config)
    task_dir = create_task_dir(options.task_id)
    paths = task_paths(task_dir)
    warnings: List[str] = []
    errors: List[str] = []
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    task_id = task_dir.name

    paths["user_request"].write_text(user_request + "\n", encoding="utf-8")

    search_plan = {
        "project": {"name": "ad-url-scout"},
        "mode": "openrouter_web_search_only",
        "user_request": user_request,
        "web_search": app_config.get("web_search") or {},
        "hard_constraints": hard_constraints,
    }
    if options.max_results_per_query:
        search_plan.setdefault("web_search", {})["target_url_count"] = int(options.max_results_per_query)
    _write_yaml(paths["search_plan"], search_plan)

    found_rows: List[Dict[str, Any]] = []
    search_meta: Dict[str, Any] = {}
    if options.offline_candidates_path:
        found_rows = _read_rows(Path(options.offline_candidates_path))
        warnings.append(f"离线模式：使用示例候选数据 {options.offline_candidates_path}")
    elif not openrouter_api_key():
        errors.append("未检测到 OPENROUTER_API_KEY。当前版本只支持 OpenRouter Web Search 寻源。")
    else:
        try:
            found_rows, scout_warnings, search_meta = scout_urls_with_openrouter(
                user_request,
                target_count=(options.max_results_per_query or None),
            )
            warnings.extend(scout_warnings)
        except OpenRouterError as exc:
            errors.append(str(exc))
        except Exception as exc:
            errors.append(f"OpenRouter Web Search 寻源失败：{type(exc).__name__}: {exc}")

    found_rows = [coerce_candidate(r) for r in found_rows]
    raw_responses = search_meta.pop("raw_responses", []) if isinstance(search_meta.get("raw_responses"), list) else []
    if raw_responses:
        raw_lines: List[str] = []
        for item in raw_responses:
            if not isinstance(item, dict):
                continue
            raw_lines.append(f"## {item.get('mode') or 'response'}")
            raw_lines.append("")
            raw_lines.append(str(item.get("raw") or ""))
            raw_lines.append("")
        paths["web_search_raw"].write_text(clean_text("\n".join(raw_lines)), encoding="utf-8")
    found_rows, non_vimeo_dropped = _keep_vimeo_only(found_rows)
    if non_vimeo_dropped:
        warnings.append(f"已丢弃 {non_vimeo_dropped} 条非 Vimeo URL。当前版本只保留 vimeo.com 视频页。")
    vimeo_cfg = app_config.get("vimeo") if isinstance(app_config.get("vimeo"), dict) else {}
    oembed_stats: Dict[str, int] = {"total": len(found_rows), "ok": 0, "failed": 0, "skipped": len(found_rows)}
    if options.use_network and not options.offline_candidates_path and vimeo_cfg.get("use_oembed_metadata", True):
        found_rows, oembed_stats, oembed_warnings = enrich_vimeo_oembed_rows(
            found_rows,
            enabled=True,
            timeout_seconds=int(vimeo_cfg.get("oembed_timeout_seconds") or 10),
        )
        if oembed_warnings:
            warnings.extend(oembed_warnings[:10])
            if len(oembed_warnings) > 10:
                warnings.append(f"还有 {len(oembed_warnings) - 10} 条 Vimeo oEmbed 读取失败已省略显示。")
    write_jsonl(paths["llm_found_urls"], found_rows)

    constrained_rows, hard_rejected_rows, hard_stats = apply_hard_constraints(
        found_rows,
        hard_constraints,
    )
    if hard_rejected_rows:
        warnings.append(
            "已按硬性条件丢弃 "
            f"{len(hard_rejected_rows)} 条：必须 Vimeo、4K/2160p/UHD、60 秒以内、发布时间两年内，且有广告/商业片特征。"
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
    write_jsonl(paths["llm_filtered"], analysis_rows)
    write_jsonl(paths["rejected"], [*hard_rejected_rows, *duplicate_rows])
    write_jsonl(paths["final_candidates"], analysis_rows)

    url_analyzer.export_review_sheet(
        analysis_rows,
        output_csv=paths["review_sheet_csv"],
        output_md=paths["review_sheet_md"],
    )

    metadata_success = sum(1 for r in analysis_rows if r.get("title") or r.get("video_url"))
    summary = {
        "task_id": task_id,
        "created_at": created_at,
        "user_request": user_request.strip(),
        "search_plan_path": str(paths["search_plan"]),
        "web_search_raw_path": str(paths["web_search_raw"]) if paths["web_search_raw"].exists() else "",
        "llm_found_urls_path": str(paths["llm_found_urls"]),
        "total_candidates": len(found_rows),
        "metadata_success_count": metadata_success,
        "rule_pass_count": len(unique_rows),
        "llm_pass_count": len(unique_rows),
        "final_count": len(unique_rows),
        "duplicate_count": len(duplicate_rows),
        "non_vimeo_dropped": non_vimeo_dropped,
        "hard_constraint_rejected_count": len(hard_rejected_rows),
        "hard_constraint_reject_stats": hard_stats,
        "vimeo_oembed": oembed_stats,
        "rejected_count": len(hard_rejected_rows) + len(duplicate_rows),
        "review_sheet_csv": str(paths["review_sheet_csv"]),
        "review_sheet_md": str(paths["review_sheet_md"]),
        "final_candidates_path": str(paths["final_candidates"]),
        "rejected_path": str(paths["rejected"]),
        "duplicates_path": str(paths["duplicates"]),
        "dedupe_report_path": str(paths["dedupe_report"]),
        "web_search": search_meta,
        "errors": errors,
        "warnings": warnings,
        "next_steps": [
            "请打开 review_sheet.csv，填写 manual_status、manual_reject_reasons、manual_notes。",
            "填写后回到控制台选择“导入人工审核反馈”。",
        ],
    }
    _write_summary(paths, summary)
    write_latest_task(task_dir)
    return PipelineResult(task_id=task_id, task_dir=task_dir, summary=summary, warnings=warnings, errors=errors)


def import_feedback_for_task(task_dir: Path, review_csv: Path, *, use_ai: bool = True) -> Dict[str, Any]:
    paths = task_paths(task_dir)
    warnings: List[str] = []
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
    _md, rule_plan = search_strategy_from_feedback.generate_rule_based_strategy(
        feedback_json_path=paths["feedback_json"],
        reviewed_jsonl_path=paths["manual_reviewed"],
        output_md=task_dir / "rule_based_feedback_strategy.md",
        output_yaml=paths["next_search_plan"],
    )

    if use_ai and openrouter_api_key():
        examples = []
        for row in rows[:80]:
            manual = row.get("manual_review") if isinstance(row.get("manual_review"), dict) else {}
            examples.append(
                {
                    "video_id": row.get("video_id"),
                    "title": row.get("title"),
                    "channel_title": row.get("channel_title"),
                    "query_used": (row.get("source_context") or {}).get("query_used") if isinstance(row.get("source_context"), dict) else "",
                    "manual_review": manual,
                }
            )
        md, plan, ai_warnings = analyze_feedback_with_openrouter(stats, examples)
        warnings.extend(ai_warnings)
        if md:
            paths["feedback_md"].write_text(md if md.endswith("\n") else md + "\n", encoding="utf-8")
        if plan:
            _write_yaml(paths["next_search_plan"], plan)
    elif use_ai:
        warnings.append("未检测到 OPENROUTER_API_KEY，反馈策略使用基础统计。")

    result = {
        "import_summary": import_summary,
        "feedback_summary": stats.get("summary") or {},
        "next_search_plan": str(paths["next_search_plan"]),
        "feedback_md": str(paths["feedback_md"]),
        "warnings": warnings,
    }
    (task_dir / "feedback_import_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
