from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import yaml

from .. import filters, format_probe, metadata_enrich, review_feedback_analyzer, review_schema, search_strategy_from_feedback, url_analyzer, youtube_search
from ..cookie_loader import load_cookie_settings
from ..llm.feedback_analyzer import analyze_feedback_with_openrouter
from ..llm.planner import generate_search_plan
from ..llm.semantic_filter import semantic_filter_candidates
from ..utils import PROJECT_ROOT, clean_for_serialization, clean_text, coerce_candidate, read_jsonl, write_jsonl
from .config import FILTERS_CONFIG_PATH, LABELS_CONFIG_PATH, load_app_config, openrouter_api_key, url_analysis_compat_config, youtube_api_key
from .paths import create_task_dir, task_paths, write_latest_task
from .task import PipelineOptions, PipelineResult


def _write_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(clean_for_serialization(data), allow_unicode=True, sort_keys=False), encoding="utf-8")


def _read_rows(path: Path) -> List[Dict[str, Any]]:
    return [coerce_candidate(r) for r in read_jsonl(path)]


def _skip_probe_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        r = dict(row)
        r["format_probe_status"] = r.get("format_probe_status") or "skipped"
        r.setdefault("probe_max_height", None)
        r.setdefault("probe_confirmed_4k", False)
        r.setdefault("available_format_heights", [])
        out.append(r)
    return out


def _analysis_to_filter_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        source = row.get("source_context") if isinstance(row.get("source_context"), dict) else {}
        fmt = row.get("format_info") if isinstance(row.get("format_info"), dict) else {}
        r = coerce_candidate(
            {
                "video_id": row.get("video_id") or "",
                "canonical_url": row.get("video_url") or "",
                "title": row.get("title") or "",
                "description": row.get("description") or "",
                "description_snippet": row.get("description_snippet") or "",
                "channel_id": row.get("channel_id") or "",
                "channel_title": row.get("channel_title") or "",
                "published_at": row.get("published_at") or "",
                "category": row.get("category") or source.get("category") or "",
                "subcategory": row.get("subcategory") or source.get("subcategory") or "",
                "brand": row.get("brand") or source.get("brand") or "",
                "search_task_id": source.get("search_task_id") or "",
                "matched_keywords": [source.get("query_used")] if source.get("query_used") else [],
                "duration_seconds": row.get("duration_seconds"),
                "view_count": row.get("view_count"),
                "like_count": row.get("like_count"),
                "comment_count": row.get("comment_count"),
                "thumbnail_best_url": (row.get("thumbnail_urls") or [""])[0] if isinstance(row.get("thumbnail_urls"), list) else "",
                "tags": row.get("tags") or [],
                "format_probe_status": fmt.get("format_probe_status") or "pending",
                "probe_max_height": fmt.get("max_format_height"),
                "probe_confirmed_4k": bool(fmt.get("has_2160p_format")),
                "available_format_heights": fmt.get("available_format_heights") or [],
            }
        )
        out.append(r)
    return out


def _summary_markdown(summary: Dict[str, Any]) -> str:
    lines = [
        "# 任务摘要",
        "",
        f"- 任务 ID：`{summary['task_id']}`",
        f"- 创建时间：{summary['created_at']}",
        f"- 候选 URL：{summary['total_candidates']}",
        f"- 元数据读取成功：{summary['metadata_success_count']}",
        f"- 规则过滤通过：{summary['rule_pass_count']}",
        f"- AI 复筛通过：{summary['llm_pass_count']}",
        f"- 需要人工审核：{summary['final_count']}",
        f"- 拒绝明细：{summary['rejected_count']}",
        "",
        "## 输出文件",
        f"- 人工审核表：`{summary['review_sheet_csv']}`",
        f"- Markdown 预览：`{summary['review_sheet_md']}`",
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


def run_new_task(user_request: str, options: PipelineOptions | None = None) -> PipelineResult:
    user_request = clean_text(user_request).strip()
    options = options or PipelineOptions()
    task_dir = create_task_dir(options.task_id)
    paths = task_paths(task_dir)
    warnings: List[str] = []
    errors: List[str] = []
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    task_id = task_dir.name
    cookie_settings = load_cookie_settings(config_path=PROJECT_ROOT / "config" / "app.yaml")
    if cookie_settings.enabled and cookie_settings.warning:
        warnings.append(cookie_settings.warning)

    paths["user_request"].write_text(user_request + "\n", encoding="utf-8")

    ai_requested = options.ai_enabled and bool((load_app_config().get("llm") or {}).get("enabled", True))
    if ai_requested and not openrouter_api_key():
        warnings.append(
            "未检测到 OPENROUTER_API_KEY。AI 搜索计划和语义筛选不可用，已使用规则模式继续。"
        )

    if options.search_plan_override:
        search_plan = options.search_plan_override
        plan_warnings = []
    else:
        search_plan, plan_warnings = generate_search_plan(user_request, use_ai=ai_requested)
        warnings.extend(plan_warnings)
    if options.max_results_per_query:
        search_plan.setdefault("global_rules", {})["max_results_per_keyword"] = int(options.max_results_per_query)
        for task in search_plan.get("tasks") or []:
            if isinstance(task, dict):
                task["max_results_per_keyword"] = int(options.max_results_per_query)
    _write_yaml(paths["search_plan"], search_plan)

    raw_rows: List[Dict[str, Any]] = []
    offline = bool(options.offline_candidates_path)
    if options.offline_candidates_path:
        raw_rows = _read_rows(Path(options.offline_candidates_path))
        warnings.append(f"离线模式：使用示例候选数据 {options.offline_candidates_path}")
    elif not options.use_network:
        warnings.append("当前设置为离线模式，未执行 YouTube 搜索。")
    elif youtube_api_key():
        try:
            raw_rows = [coerce_candidate(r) for r in youtube_search.run_search_plan(paths["search_plan"], youtube_api_key())]
        except Exception as exc:
            errors.append(f"YouTube 搜索失败：{exc}")
    else:
        warnings.append("未检测到 YOUTUBE_API_KEY。已改用 yt-dlp 搜索降级模式，不下载视频。")
        try:
            rows, ytdlp_warnings = youtube_search.run_search_plan_ytdlp(paths["search_plan"], cookie_settings=cookie_settings)
            raw_rows = [coerce_candidate(r) for r in rows]
            warnings.extend(ytdlp_warnings)
        except Exception as exc:
            errors.append(f"yt-dlp 搜索降级失败：{exc}")
    write_jsonl(paths["candidates_raw"], raw_rows)

    analysis_rows = url_analyzer.analyze_url_records(
        raw_rows,
        cfg=url_analysis_compat_config(),
        cookie_settings=cookie_settings,
        offline=offline or not options.use_network,
    )
    write_jsonl(paths["url_analysis"], analysis_rows)

    enriched_rows = _analysis_to_filter_rows(analysis_rows) if analysis_rows else raw_rows
    if raw_rows and youtube_api_key() and not offline and options.use_network:
        try:
            enriched_rows = metadata_enrich.enrich_records(raw_rows, youtube_api_key())
        except Exception as exc:
            warnings.append(f"YouTube 元数据补全失败，已使用已有字段继续：{exc}")

    analysis_has_format = any(
        isinstance(r.get("format_info"), dict) and (r.get("format_info") or {}).get("format_probe_status") == "ok"
        for r in analysis_rows
    )
    if raw_rows and not analysis_has_format and not options.skip_format_probe and not offline and options.use_network and bool((load_app_config().get("youtube") or {}).get("use_format_probe", True)):
        probed_rows = format_probe.probe_records(enriched_rows)
    else:
        probed_rows = _skip_probe_rows(enriched_rows)

    if probed_rows:
        rule_ok, rule_rej = filters.apply_filters(probed_rows, FILTERS_CONFIG_PATH, PROJECT_ROOT)
    else:
        rule_ok, rule_rej = [], []
    write_jsonl(paths["rule_filtered"], rule_ok)

    llm_ok, llm_rej, llm_warnings = semantic_filter_candidates(rule_ok, use_ai=ai_requested)
    warnings.extend(llm_warnings)
    write_jsonl(paths["llm_filtered"], llm_ok)

    rejected_rows = [*rule_rej, *llm_rej]
    write_jsonl(paths["rejected"], rejected_rows)
    write_jsonl(paths["final_candidates"], llm_ok)

    final_analysis_rows = url_analyzer.analyze_url_records(
        llm_ok,
        cfg=url_analysis_compat_config(),
        cookie_settings=cookie_settings,
        offline=True,
    )
    url_analyzer.export_review_sheet(
        final_analysis_rows,
        output_csv=paths["review_sheet_csv"],
        output_md=paths["review_sheet_md"],
    )

    metadata_success = sum(1 for r in analysis_rows if r.get("video_id") and (r.get("title") or r.get("channel_title")))
    summary = {
        "task_id": task_id,
        "created_at": created_at,
        "user_request": user_request.strip(),
        "search_plan_path": str(paths["search_plan"]),
        "total_candidates": len(raw_rows),
        "metadata_success_count": metadata_success,
        "rule_pass_count": len(rule_ok),
        "llm_pass_count": len(llm_ok),
        "final_count": len(llm_ok),
        "rejected_count": len(rejected_rows),
        "review_sheet_csv": str(paths["review_sheet_csv"]),
        "review_sheet_md": str(paths["review_sheet_md"]),
        "final_candidates_path": str(paths["final_candidates"]),
        "rejected_path": str(paths["rejected"]),
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
        warnings.append("未检测到 OPENROUTER_API_KEY，反馈策略使用规则模式。")

    result = {
        "import_summary": import_summary,
        "feedback_summary": stats.get("summary") or {},
        "next_search_plan": str(paths["next_search_plan"]),
        "feedback_md": str(paths["feedback_md"]),
        "warnings": warnings,
    }
    (task_dir / "feedback_import_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
