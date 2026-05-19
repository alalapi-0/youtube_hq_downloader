from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import review_feedback_analyzer, review_schema, search_strategy_from_feedback, url_analyzer
from .core.config import LABELS_CONFIG_PATH
from .core.pipeline import import_feedback_for_task, run_new_task
from .core.task import PipelineOptions
from .utils import PROJECT_ROOT


def _truthy_flag(val: str | bool | None) -> bool:
    if isinstance(val, bool):
        return val
    return str(val or "").strip().lower() in ("1", "true", "yes", "on", "y")


def _read_search_urls(ns: argparse.Namespace) -> list[str]:
    urls: list[str] = []
    for value in ns.search_url or []:
        if str(value).strip():
            urls.append(str(value).strip())
    if ns.search_url_file:
        path = Path(ns.search_url_file).expanduser().resolve()
        urls.extend(line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return urls


def cmd_collect(ns: argparse.Namespace) -> int:
    urls = _read_search_urls(ns)
    request_text = str(ns.note or "")
    if not urls and not ns.offline_candidates:
        print("[collect] ERROR: 请提供 --search-url 或 --search-url-file", file=sys.stderr)
        return 2
    options = PipelineOptions(
        search_page_urls=urls,
        offline_candidates_path=Path(ns.offline_candidates).resolve() if ns.offline_candidates else None,
        max_entries_per_search_page=int(ns.max_entries) if str(ns.max_entries or "").isdigit() else None,
    )
    result = run_new_task(request_text, options)
    print(f"[collect] 任务完成：{result.task_dir}")
    print(f"[collect] 人工审核表：{result.summary.get('review_sheet_csv')}")
    print(f"[collect] 采集 URL：{result.summary.get('collected_url_count', 0)}")
    print(f"[collect] 通过硬过滤+查重：{result.summary.get('final_count', 0)}")
    for warning in result.warnings:
        print(f"[collect] WARN: {warning}", file=sys.stderr)
    for error in result.errors:
        print(f"[collect] ERROR: {error}", file=sys.stderr)
    return 2 if result.errors and not result.summary.get("final_count") else 0


def cmd_import_task_feedback(ns: argparse.Namespace) -> int:
    task_dir = Path(ns.task_dir).resolve()
    review_csv = Path(ns.review_csv).resolve()
    if not task_dir.exists():
        print(f"[import-task-feedback] ERROR: task dir not found: {task_dir}", file=sys.stderr)
        return 2
    if not review_csv.exists():
        print(f"[import-task-feedback] ERROR: review csv not found: {review_csv}", file=sys.stderr)
        return 2
    result = import_feedback_for_task(task_dir, review_csv)
    print(f"[import-task-feedback] feedback={result['feedback_md']}")
    print(f"[import-task-feedback] next_search_plan={result['next_search_plan']}")
    return 0


def cmd_export_review(ns: argparse.Namespace) -> int:
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
        description="Ad URL Scout：从 YouTube 搜索结果页批量采集视频 URL，用 yt-dlp 读取元数据并本地筛选。"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    collect = sub.add_parser("collect", help="YouTube 搜索结果页 URL → review_sheet.csv")
    collect.add_argument("--search-url", action="append", default=[], help="YouTube 搜索结果页 URL，可重复传入")
    collect.add_argument("--search-url-file", dest="search_url_file", default="", help="包含多个搜索结果页 URL 的文本文件，每行一个")
    collect.add_argument("--max-entries", dest="max_entries", default="", help="每个搜索结果页最多读取多少条")
    collect.add_argument("--note", default="", help="本轮备注，会写入任务目录")
    collect.add_argument("--offline-candidates", dest="offline_candidates", default="", help=argparse.SUPPRESS)
    collect.set_defaults(func=cmd_collect)

    feedback = sub.add_parser("import-task-feedback", help="导入某个 task 的人工审核表并生成反馈策略")
    feedback.add_argument("--task-dir", dest="task_dir", required=True)
    feedback.add_argument("--review-csv", dest="review_csv", required=True)
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
