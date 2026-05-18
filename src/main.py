from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import review_feedback_analyzer, review_schema, search_strategy_from_feedback, url_analyzer
from .core.config import LABELS_CONFIG_PATH, openrouter_api_key
from .core.pipeline import import_feedback_for_task, run_new_task
from .core.task import PipelineOptions
from .env_loader import load_dotenv
from .utils import PROJECT_ROOT


def _root() -> Path:
    load_dotenv(PROJECT_ROOT / ".env")
    return PROJECT_ROOT


def _truthy_flag(val: str | bool | None) -> bool:
    if isinstance(val, bool):
        return val
    return str(val or "").strip().lower() in ("1", "true", "yes", "on", "y")


def cmd_run_task(ns: argparse.Namespace) -> int:
    _root()
    if ns.request:
        request_text = str(ns.request)
    elif ns.request_file:
        request_text = Path(ns.request_file).read_text(encoding="utf-8")
    else:
        print("[run-task] ERROR: 请提供 --request 或 --request-file", file=sys.stderr)
        return 2

    if not ns.offline_candidates and not openrouter_api_key():
        print("[run-task] ERROR: 未检测到 OPENROUTER_API_KEY。当前版本只通过 OpenRouter Web Search 搜索 URL。", file=sys.stderr)
        return 2

    options = PipelineOptions(
        ai_enabled=True,
        offline_candidates_path=Path(ns.offline_candidates).resolve() if ns.offline_candidates else None,
        max_results_per_query=int(ns.max_results) if str(ns.max_results or "").isdigit() else None,
    )
    result = run_new_task(request_text, options)
    print(f"[run-task] 任务完成：{result.task_dir}")
    print(f"[run-task] 人工审核表：{result.summary.get('review_sheet_csv')}")
    print(f"[run-task] 本地查重后保留：{result.summary.get('final_count', 0)}")
    print(f"[run-task] 重复/无效：{result.summary.get('duplicate_count', 0)}")
    for warning in result.warnings:
        print(f"[run-task] WARN: {warning}", file=sys.stderr)
    for error in result.errors:
        print(f"[run-task] ERROR: {error}", file=sys.stderr)
    return 2 if result.errors and not result.summary.get("final_count") else 0


def cmd_import_task_feedback(ns: argparse.Namespace) -> int:
    _root()
    task_dir = Path(ns.task_dir).resolve()
    review_csv = Path(ns.review_csv).resolve()
    if not task_dir.exists():
        print(f"[import-task-feedback] ERROR: task dir not found: {task_dir}", file=sys.stderr)
        return 2
    if not review_csv.exists():
        print(f"[import-task-feedback] ERROR: review csv not found: {review_csv}", file=sys.stderr)
        return 2
    result = import_feedback_for_task(task_dir, review_csv, use_ai=_truthy_flag(ns.ai))
    print(f"[import-task-feedback] feedback={result['feedback_md']}")
    print(f"[import-task-feedback] next_search_plan={result['next_search_plan']}")
    for warning in result.get("warnings") or []:
        print(f"[import-task-feedback] WARN: {warning}", file=sys.stderr)
    return 0


def cmd_export_review(ns: argparse.Namespace) -> int:
    _root()
    analysis = Path(ns.analysis).resolve()
    if not analysis.exists():
        print(f"[export-review] ERROR: analysis not found: {analysis}", file=sys.stderr)
        return 2
    csv_path = Path(ns.output_csv).resolve()
    md_path = Path(ns.output_md).resolve()
    url_analyzer.export_review_sheet_from_file(
        analysis_path=analysis,
        output_csv=csv_path,
        output_md=md_path,
        include_existing_manual=_truthy_flag(ns.include_existing_manual),
    )
    print(f"[export-review] wrote csv={csv_path} md={md_path}")
    return 0


def cmd_import_review(ns: argparse.Namespace) -> int:
    _root()
    analysis = Path(ns.analysis).resolve()
    review_csv = Path(ns.review_csv).resolve()
    output = Path(ns.output).resolve()
    if not analysis.exists():
        print(f"[import-review] ERROR: analysis not found: {analysis}", file=sys.stderr)
        return 2
    if not review_csv.exists():
        print(f"[import-review] ERROR: review csv not found: {review_csv}", file=sys.stderr)
        return 2
    _rows, summary = review_schema.import_manual_reviews(
        analysis_path=analysis,
        review_csv_path=review_csv,
        output_path=output,
        labels_path=LABELS_CONFIG_PATH,
    )
    print(
        "[import-review] "
        f"updated={summary['review_rows_updated']} unmatched={summary['review_rows_unmatched']} -> {output}"
    )
    if summary.get("unrecognized_labels"):
        print(f"[import-review] WARN: unrecognized_labels={summary['unrecognized_labels']}", file=sys.stderr)
    return 0


def cmd_analyze_feedback(ns: argparse.Namespace) -> int:
    _root()
    inp = Path(ns.input).resolve()
    if not inp.exists():
        print(f"[analyze-feedback] ERROR: input not found: {inp}", file=sys.stderr)
        return 2
    stats = review_feedback_analyzer.analyze_feedback_file(
        input_path=inp,
        output_md=Path(ns.output_md).resolve(),
        output_json=Path(ns.output_json).resolve(),
    )
    summary = stats.get("summary") or {}
    print(
        "[analyze-feedback] "
        f"reviewed={summary.get('total_reviewed', 0)} pass_rate={summary.get('pass_rate', 0)} "
        f"md={Path(ns.output_md).resolve()} json={Path(ns.output_json).resolve()}"
    )
    return 0


def cmd_strategy_from_feedback(ns: argparse.Namespace) -> int:
    _root()
    feedback = Path(ns.feedback_json).resolve()
    reviewed = Path(ns.reviewed_jsonl).resolve()
    if not feedback.exists():
        print(f"[strategy-from-feedback] ERROR: feedback json not found: {feedback}", file=sys.stderr)
        return 2
    if not reviewed.exists():
        print(f"[strategy-from-feedback] ERROR: reviewed jsonl not found: {reviewed}", file=sys.stderr)
        return 2
    search_strategy_from_feedback.generate_rule_based_strategy(
        feedback_json_path=feedback,
        reviewed_jsonl_path=reviewed,
        output_md=Path(ns.output_md).resolve(),
        output_yaml=Path(ns.output_yaml).resolve(),
    )
    print(f"[strategy-from-feedback] wrote md={Path(ns.output_md).resolve()} yaml={Path(ns.output_yaml).resolve()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ad URL Scout：通过 OpenRouter Web Search 寻找广告/商品/品牌视频 URL，并做本地查重。"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run-task", help="自然语言需求 → OpenRouter Web Search → 本地查重 → review_sheet.csv")
    run.add_argument("--request", default="", help="自然语言寻源需求")
    run.add_argument("--request-file", dest="request_file", default="", help="从文本文件读取寻源需求")
    run.add_argument("--max-results", dest="max_results", default="", help="本轮最多保留多少个去重 URL")
    run.add_argument("--offline-candidates", dest="offline_candidates", default="", help=argparse.SUPPRESS)
    run.set_defaults(func=cmd_run_task)

    feedback = sub.add_parser("import-task-feedback", help="导入某个 task 的人工审核表并生成反馈策略")
    feedback.add_argument("--task-dir", dest="task_dir", required=True)
    feedback.add_argument("--review-csv", dest="review_csv", required=True)
    feedback.add_argument("--ai", default="true", help="是否使用 OpenRouter 总结反馈")
    feedback.set_defaults(func=cmd_import_task_feedback)

    export_review = sub.add_parser("export-review", help="从结构化结果重新导出人工审核表")
    export_review.add_argument("--analysis", required=True)
    export_review.add_argument("--output-csv", dest="output_csv", default=str(PROJECT_ROOT / "output" / "review" / "review_sheet.csv"))
    export_review.add_argument("--output-md", dest="output_md", default=str(PROJECT_ROOT / "output" / "review" / "review_sheet.md"))
    export_review.add_argument("--include-existing-manual", dest="include_existing_manual", default="false")
    export_review.set_defaults(func=cmd_export_review)

    import_review = sub.add_parser("import-review", help="filled review CSV → manual_review JSONL")
    import_review.add_argument("--analysis", required=True)
    import_review.add_argument("--review-csv", dest="review_csv", required=True)
    import_review.add_argument("--output", required=True)
    import_review.set_defaults(func=cmd_import_review)

    analyze = sub.add_parser("analyze-feedback", help="manual_reviewed JSONL → 反馈统计")
    analyze.add_argument("--input", required=True)
    analyze.add_argument("--output-md", dest="output_md", required=True)
    analyze.add_argument("--output-json", dest="output_json", required=True)
    analyze.set_defaults(func=cmd_analyze_feedback)

    strategy = sub.add_parser("strategy-from-feedback", help="反馈统计 → 下一轮搜索策略")
    strategy.add_argument("--feedback-json", dest="feedback_json", required=True)
    strategy.add_argument("--reviewed-jsonl", dest="reviewed_jsonl", required=True)
    strategy.add_argument("--output-md", dest="output_md", default=str(PROJECT_ROOT / "output" / "strategy" / "rule_based_next_search_strategy.md"))
    strategy.add_argument("--output-yaml", dest="output_yaml", default=str(PROJECT_ROOT / "output" / "strategy" / "rule_based_next_search_plan.yaml"))
    strategy.set_defaults(func=cmd_strategy_from_feedback)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
