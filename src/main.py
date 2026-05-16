from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import exporters
from . import filters as filters_mod
from . import format_probe
from . import review_feedback_analyzer
from . import review_schema
from . import search_strategy_from_feedback
from . import url_analyzer
from . import llm_strategy_optimizer as strat
from . import metadata_enrich
from . import youtube_search
from .cookie_loader import load_cookie_settings
from .core.config import FILTERS_CONFIG_PATH, LABELS_CONFIG_PATH, openrouter_api_key, youtube_api_key
from .core.pipeline import import_feedback_for_task, run_new_task
from .core.task import PipelineOptions
from .llm.planner import fallback_search_plan, generate_search_plan
from .llm.semantic_filter import semantic_filter_candidates
from .search_plan_builder import build_search_plan_from_tasks, dump_search_plan
from .utils import PROJECT_ROOT, coerce_candidate, load_yaml_mapping, read_jsonl, write_jsonl


def _root() -> Path:
    load_dotenv(PROJECT_ROOT / ".env")
    return PROJECT_ROOT


def _truthy_flag(val: str | bool | None) -> bool:
    if isinstance(val, bool):
        return val
    return str(val or "").strip().lower() in ("1", "true", "yes", "on")


def _prompt_version() -> str:
    cfg = load_yaml_mapping(PROJECT_ROOT / "config" / "app.yaml")
    return str(((cfg.get("llm") or {}).get("prompt_version")) or "ad-url-scout-v1")


def cmd_plan(ns: argparse.Namespace) -> int:
    _root()
    inp = Path(ns.input).resolve()
    outp = Path(ns.output).resolve()
    want_llm = _truthy_flag(ns.use_llm)

    if not inp.exists():
        print(f"[plan] ERROR: input not found: {inp}", file=sys.stderr)
        return 2

    mechanical: dict | None = None

    lowered = inp.name.lower()
    if lowered.endswith((".yaml", ".yml")):
        mechanical = build_search_plan_from_tasks(inp)

    blob: dict | None = None

    if want_llm:
        txt = inp.read_text(encoding="utf-8")
        if not openrouter_api_key():
            print("[plan] WARN: 未检测到 OPENROUTER_API_KEY，使用规则模式生成计划", file=sys.stderr)
            blob = fallback_search_plan(txt, warning="missing_openrouter_key")
        else:
            blob, warnings = generate_search_plan(txt, use_ai=True)
            for w in warnings:
                print(f"[plan] WARN: {w}", file=sys.stderr)

    if blob and isinstance(blob.get("tasks"), list):
        dump_search_plan(outp, blob)
        print(f"[plan] llm-enhanced wrote -> {outp}")
        return 0

    if mechanical is not None:
        dump_search_plan(outp, mechanical)
        print(f"[plan] mechanical wrote -> {outp}")
        return 0

    if lowered.endswith((".txt", ".md")):
        blob = fallback_search_plan(inp.read_text(encoding="utf-8"), warning="rule_mode")
        dump_search_plan(outp, blob)
        print(f"[plan] rule-mode wrote -> {outp}")
        return 0

    print(
        "[plan] ERROR: 无法拼装 search_plan.yaml：请提供 YAML，或传入自然语言文本并启用 OpenRouter/规则 planner",
        file=sys.stderr,
    )
    return 2


def cmd_search(ns: argparse.Namespace) -> int:
    _root()
    key = youtube_api_key()
    if not key:
        print("[search] WARN: 未检测到 YOUTUBE_API_KEY，无法自动按关键词搜索；写出空候选文件。", file=sys.stderr)
        write_jsonl(Path(ns.output).resolve(), [])
        return 0
    task_path = Path(ns.task).resolve()
    outp = Path(ns.output).resolve()
    rows = youtube_search.run_search_plan(task_path, key)
    normalized = [coerce_candidate(r) for r in rows]
    write_jsonl(outp, normalized)
    print(f"[search] wrote {len(normalized)} rows -> {outp}")
    return 0


def cmd_enrich(ns: argparse.Namespace) -> int:
    _root()
    inp = Path(ns.input).resolve()
    outp = Path(ns.output).resolve()
    rows = [coerce_candidate(r) for r in read_jsonl(inp)]
    key = youtube_api_key()

    if not key:
        print(
            "[enrich] WARN: missing YOUTUBE_API_KEY — passthrough without videos.list refresh",
            file=sys.stderr,
        )
        write_jsonl(outp, rows)
        print(f"[enrich] wrote {len(rows)} rows (passthrough) -> {outp}")
        return 0

    enriched = metadata_enrich.enrich_records(rows, key)
    enriched = [coerce_candidate(r) for r in enriched]
    write_jsonl(outp, enriched)
    print(f"[enrich] enriched {len(enriched)} rows -> {outp}")
    return 0


def cmd_probe(ns: argparse.Namespace) -> int:
    _root()
    inp = Path(ns.input).resolve()
    outp = Path(ns.output).resolve()
    rows = [coerce_candidate(r) for r in read_jsonl(inp)]
    probed = format_probe.probe_records(rows)
    probed = [coerce_candidate(r) for r in probed]
    write_jsonl(outp, probed)
    print(f"[probe-format] wrote {len(probed)} rows -> {outp}")
    return 0


def cmd_filter(ns: argparse.Namespace) -> int:
    root = _root()
    inp = Path(ns.input).resolve()
    rules_path = Path(ns.rules).resolve()
    out_ok = Path(ns.output).resolve()
    out_bad = Path(ns.rejected).resolve()
    rows = [coerce_candidate(r) for r in read_jsonl(inp)]
    keep, rej = filters_mod.apply_filters(rows, rules_path, root)
    keep = [coerce_candidate(r) for r in keep]
    rej = [coerce_candidate(r) for r in rej]
    write_jsonl(out_ok, keep)
    write_jsonl(out_bad, rej)
    print(f"[filter] keep={len(keep)} rej={len(rej)} ok->{out_ok} rej->{out_bad}")
    return 0


def cmd_llm_filter(ns: argparse.Namespace) -> int:
    _root()
    inp = Path(ns.input).resolve()
    outp = Path(ns.output).resolve()
    out_rej = Path(ns.rejected).resolve()
    use_llm = _truthy_flag(ns.use_llm)

    rows = [coerce_candidate(r) for r in read_jsonl(inp)]

    if not use_llm:
        kept, rejected, warnings = semantic_filter_candidates(rows, use_ai=False)
        write_jsonl(outp, kept)
        write_jsonl(out_rej, rejected)
        for w in warnings:
            print(f"[llm-filter] WARN: {w}", file=sys.stderr)
        print(f"[llm-filter] skipped LLM semantic gate ({len(kept)}) -> {outp}")
        return 0
    kept, rejected, warnings = semantic_filter_candidates(rows, use_ai=True)
    for w in warnings:
        print(f"[llm-filter] WARN: {w}", file=sys.stderr)

    write_jsonl(outp, kept)
    write_jsonl(out_rej, rejected)
    print(f"[llm-filter] keep={len(kept)} rej={len(rejected)} ok->{outp} rej->{out_rej}")
    return 0


def cmd_strategy(ns: argparse.Namespace) -> int:
    _root()
    rule_path = Path(ns.rule_rejected).resolve()
    llm_path = Path(ns.llm_rejected).resolve()

    cp = getattr(ns, "current_plan", "") or ""
    current_plan = Path(cp).resolve() if cp else None

    out_md = Path(ns.output_md).resolve()
    out_yaml = Path(ns.output_yaml).resolve()

    fallback_tasks = PROJECT_ROOT / "examples" / "search_tasks.demo.yaml"

    llm_paths = PROJECT_ROOT / "config" / "app.yaml"
    prompts = PROJECT_ROOT / "config" / "app.yaml"

    use_llm = _truthy_flag(ns.use_llm)

    plan: dict = {}

    if use_llm:
        plan, md = strat.strategy_optimize_llm_bundle(
            rule_rejected_path=rule_path,
            llm_rejected_path=llm_path,
            search_tasks_fallback=fallback_tasks,
            current_plan_path=current_plan,
            llm_config_path=llm_paths,
            prompts_path=prompts,
            prompt_version=_prompt_version(),
        )
    else:
        plan, md = strat.strategy_optimize_heuristic_bundle(
            rule_rejected_path=rule_path,
            llm_rejected_path=llm_path,
            search_tasks_fallback=fallback_tasks,
            current_plan_path=current_plan,
        )

    import yaml as _yaml

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_yaml.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md, encoding="utf-8")

    out_yaml.write_text(_yaml.safe_dump(plan, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"[strategy-optimize] wrote md={out_md} yaml={out_yaml}")
    return 0


def cmd_export(ns: argparse.Namespace) -> int:
    _root()
    outp = Path(ns.output_dir).resolve()
    inp = Path(ns.input).resolve()
    rows_in = read_jsonl(inp)
    rows = exporters.normalize_records_for_export(rows_in)

    fmt = (ns.format or "all").lower()

    rr = Path(ns.rejected_rule).resolve() if ns.rejected_rule else PROJECT_ROOT / "data" / "rejected" / "rule_rejected.jsonl"
    lr = Path(ns.rejected_llm).resolve() if ns.rejected_llm else PROJECT_ROOT / "data" / "rejected" / "llm_rejected.jsonl"

    rej_rule_rows = list(read_jsonl(rr)) if rr.exists() else []
    rej_llm_rows = list(read_jsonl(lr)) if lr.exists() else []

    stage_paths = {
        "raw_search": PROJECT_ROOT / "data" / "raw" / "candidates.jsonl",
        "enriched": PROJECT_ROOT / "data" / "enriched" / "enriched.jsonl",
        "probed": PROJECT_ROOT / "data" / "enriched" / "probed.jsonl",
        "rule_filtered": PROJECT_ROOT / "data" / "filtered" / "rule_filtered.jsonl",
        "llm_filtered": PROJECT_ROOT / "data" / "filtered" / "llm_filtered.jsonl",
    }

    if fmt == "all":
        exporters.export_all(
            rows,
            outp,
            rejected_rule_rows=rej_rule_rows,
            rejected_llm_rows=rej_llm_rows,
            stage_paths=stage_paths,
        )
    elif fmt == "csv":
        exporters.export_csv(rows, outp / "csv" / "filtered_urls.csv")
    elif fmt == "jsonl":
        exporters.export_jsonl(rows, outp / "jsonl" / "filtered_urls.jsonl")
    elif fmt == "markdown":
        exporters.export_markdown(
            rows,
            outp / "markdown" / "filtered_urls.md",
            rejected_rule_rows=rej_rule_rows,
            rejected_llm_rows=rej_llm_rows,
            stage_paths=stage_paths,
        )
    else:
        print(f"[export] unknown format: {fmt}", file=sys.stderr)
        return 2

    print(f"[export] done -> {outp}")
    return 0


def cmd_analyze_url(ns: argparse.Namespace) -> int:
    _root()
    inp = Path(ns.input).resolve()
    outp = Path(ns.output).resolve()
    if not inp.exists():
        print(f"[analyze-url] ERROR: input not found: {inp}", file=sys.stderr)
        return 2

    cookie_settings = load_cookie_settings(
        cookie_file=ns.cookie_file or None,
        cookies_from_browser=ns.cookies_from_browser or None,
        enable_cookie=bool(ns.cookie_file or ns.cookies_from_browser) or None,
    )
    if cookie_settings.warning:
        print(f"[analyze-url] COOKIE NOTICE: {cookie_settings.warning}", file=sys.stderr)
    if ns.cookies_from_browser:
        print(
            "[analyze-url] COOKIE NOTICE: cookies-from-browser 只用于读取你本机浏览器已可访问的页面元数据，"
            "不会绕过权限，也不会下载受限内容。",
            file=sys.stderr,
        )

    offline = _truthy_flag(ns.offline)
    records = url_analyzer.analyze_url_file(
        input_path=inp,
        output_path=outp,
        cookie_settings=cookie_settings,
        offline=offline,
    )

    if not _truthy_flag(ns.no_review_export):
        cfg = url_analyzer.load_url_analysis_config()
        review_cfg = cfg.get("review_export") or {}
        csv_path = Path(ns.review_csv or review_cfg.get("output_csv") or "output/review/review_sheet.csv")
        md_path = Path(ns.review_md or review_cfg.get("output_md") or "output/review/review_sheet.md")
        if not csv_path.is_absolute():
            csv_path = PROJECT_ROOT / csv_path
        if not md_path.is_absolute():
            md_path = PROJECT_ROOT / md_path
        url_analyzer.export_review_sheet(records, output_csv=csv_path, output_md=md_path)
        print(f"[analyze-url] review sheet csv={csv_path} md={md_path}")

    print(f"[analyze-url] wrote {len(records)} rows -> {outp}")
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
    search_strategy_from_feedback.generate_rule_based_strategy(
        feedback_json_path=feedback,
        reviewed_jsonl_path=reviewed,
        output_md=Path(ns.output_md).resolve(),
        output_yaml=Path(ns.output_yaml).resolve(),
    )
    print(f"[strategy-from-feedback] wrote md={Path(ns.output_md).resolve()} yaml={Path(ns.output_yaml).resolve()}")
    return 0


def cmd_llm_analyze_feedback(ns: argparse.Namespace) -> int:
    _root()
    inp = Path(ns.input).resolve()
    stats = Path(ns.stats).resolve()
    if not inp.exists():
        print(f"[llm-analyze-feedback] ERROR: input not found: {inp}", file=sys.stderr)
        return 2
    if not stats.exists():
        print(f"[llm-analyze-feedback] ERROR: stats not found: {stats}", file=sys.stderr)
        return 2
    review_feedback_analyzer.llm_analyze_feedback_file(
        input_path=inp,
        stats_path=stats,
        output_md=Path(ns.output_md).resolve(),
        output_yaml=Path(ns.output_yaml).resolve(),
        use_llm=_truthy_flag(ns.use_llm),
    )
    print(f"[llm-analyze-feedback] wrote md={Path(ns.output_md).resolve()} yaml={Path(ns.output_yaml).resolve()}")
    return 0


def cmd_run_task(ns: argparse.Namespace) -> int:
    _root()
    request_text = ""
    if ns.request:
        request_text = str(ns.request)
    elif ns.request_file:
        request_text = Path(ns.request_file).read_text(encoding="utf-8")
    else:
        print("[run-task] ERROR: 请提供 --request 或 --request-file", file=sys.stderr)
        return 2
    options = PipelineOptions(
        ai_enabled=_truthy_flag(ns.ai),
        use_network=not _truthy_flag(ns.offline),
        offline_candidates_path=Path(ns.offline_candidates).resolve() if ns.offline_candidates else None,
        skip_format_probe=_truthy_flag(ns.skip_format_probe),
        max_results_per_query=int(ns.max_results) if str(ns.max_results or "").isdigit() else None,
    )
    result = run_new_task(request_text, options)
    print(f"[run-task] 任务完成：{result.task_dir}")
    print(f"[run-task] 人工审核表：{result.summary.get('review_sheet_csv')}")
    if result.warnings:
        for w in result.warnings:
            print(f"[run-task] WARN: {w}", file=sys.stderr)
    if result.errors:
        for e in result.errors:
            print(f"[run-task] ERROR: {e}", file=sys.stderr)
    return 0


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
    for w in result.get("warnings") or []:
        print(f"[import-task-feedback] WARN: {w}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Ad URL Scout：AI 增强广告视频 URL 寻源工具（默认不下载视频）")
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("plan", help="自然语言需求或 YAML → search_plan.yaml")
    pp.add_argument("--input", required=True)
    pp.add_argument("--output", required=True)
    pp.add_argument("--use-llm", default="false")
    pp.set_defaults(func=cmd_plan)

    ps = sub.add_parser("search", help="search_plan.yaml → candidates jsonl（需 Data API Key）")
    ps.add_argument("--task", required=True)
    ps.add_argument("--output", required=True)
    ps.set_defaults(func=cmd_search)

    pe = sub.add_parser("enrich", help="videos.list enrichment")
    pe.add_argument("--input", required=True)
    pe.add_argument("--output", required=True)
    pe.set_defaults(func=cmd_enrich)

    pr = sub.add_parser("probe-format", help="可选 yt-dlp 格式探测")
    pr.add_argument("--input", required=True)
    pr.add_argument("--output", required=True)
    pr.set_defaults(func=cmd_probe)

    pf = sub.add_parser("filter", help="YAML 规则闸门（硬阈值 + 配额）")
    pf.add_argument("--input", required=True)
    pf.add_argument("--rules", default=str(FILTERS_CONFIG_PATH))
    pf.add_argument("--output", required=True)
    pf.add_argument("--rejected", required=True)
    pf.set_defaults(func=cmd_filter)

    pllm = sub.add_parser("llm-filter", help="语义批闸（批量 ≤20）")
    pllm.add_argument("--input", required=True)
    pllm.add_argument("--output", required=True)
    pllm.add_argument("--rejected", required=True)
    pllm.add_argument("--use-llm", default="true")
    pllm.set_defaults(func=cmd_llm_filter)

    pst = sub.add_parser("strategy-optimize", help="拒收聚合 → Markdown + mutated search_plan")
    pst.add_argument("--rule-rejected", dest="rule_rejected", required=True)
    pst.add_argument("--llm-rejected", dest="llm_rejected", required=True)
    pst.add_argument("--current-plan", dest="current_plan", default="")
    pst.add_argument("--output-md", dest="output_md", required=True)
    pst.add_argument("--output-yaml", dest="output_yaml", required=True)
    pst.add_argument("--use-llm", dest="use_llm", default="false")
    pst.set_defaults(func=cmd_strategy)

    px = sub.add_parser("export", help="Markdown + CSV + jsonl exporters")
    px.add_argument("--input", required=True)
    px.add_argument("--format", default="all", choices=["all", "csv", "jsonl", "markdown"])
    px.add_argument("--output-dir", required=True)
    px.add_argument("--rejected-rule", dest="rejected_rule", default="")
    px.add_argument("--rejected-llm", dest="rejected_llm", default="")
    px.set_defaults(func=cmd_export)

    pau = sub.add_parser("analyze-url", help="URL/JSONL/CSV → structured URL analysis JSONL + review sheet")
    pau.add_argument("--input", required=True)
    pau.add_argument("--output", required=True)
    pau.add_argument("--review-csv", dest="review_csv", default="")
    pau.add_argument("--review-md", dest="review_md", default="")
    pau.add_argument("--cookie-file", dest="cookie_file", default="")
    pau.add_argument("--cookies-from-browser", dest="cookies_from_browser", default="")
    pau.add_argument("--offline", default="false", help="true 时只使用输入中已有字段，不访问 API/yt-dlp/网页")
    pau.add_argument("--no-review-export", dest="no_review_export", default="false")
    pau.set_defaults(func=cmd_analyze_url)

    per = sub.add_parser("export-review", help="analysis JSONL → manual review CSV/Markdown")
    per.add_argument("--analysis", required=True)
    per.add_argument("--output-csv", dest="output_csv", default=str(PROJECT_ROOT / "output" / "review" / "review_sheet.csv"))
    per.add_argument("--output-md", dest="output_md", default=str(PROJECT_ROOT / "output" / "review" / "review_sheet.md"))
    per.add_argument("--include-existing-manual", dest="include_existing_manual", default="false")
    per.set_defaults(func=cmd_export_review)

    pir = sub.add_parser("import-review", help="filled review CSV → merge manual_review into analysis JSONL")
    pir.add_argument("--analysis", required=True)
    pir.add_argument("--review-csv", dest="review_csv", required=True)
    pir.add_argument("--output", required=True)
    pir.set_defaults(func=cmd_import_review)

    paf = sub.add_parser("analyze-feedback", help="manual reviewed JSONL → feedback statistics")
    paf.add_argument("--input", required=True)
    paf.add_argument("--output-md", dest="output_md", required=True)
    paf.add_argument("--output-json", dest="output_json", required=True)
    paf.set_defaults(func=cmd_analyze_feedback)

    psf = sub.add_parser("strategy-from-feedback", help="feedback stats → rule-based next search strategy")
    psf.add_argument("--feedback-json", dest="feedback_json", required=True)
    psf.add_argument("--reviewed-jsonl", dest="reviewed_jsonl", required=True)
    psf.add_argument("--output-md", dest="output_md", default=str(PROJECT_ROOT / "output" / "strategy" / "rule_based_next_search_strategy.md"))
    psf.add_argument("--output-yaml", dest="output_yaml", default=str(PROJECT_ROOT / "output" / "strategy" / "rule_based_next_search_plan.yaml"))
    psf.set_defaults(func=cmd_strategy_from_feedback)

    plfb = sub.add_parser("llm-analyze-feedback", help="manual reviewed JSONL + stats → optional LLM next search plan")
    plfb.add_argument("--input", required=True)
    plfb.add_argument("--stats", required=True)
    plfb.add_argument("--output-md", dest="output_md", required=True)
    plfb.add_argument("--output-yaml", dest="output_yaml", required=True)
    plfb.add_argument("--use-llm", dest="use_llm", default="true")
    plfb.set_defaults(func=cmd_llm_analyze_feedback)

    prun = sub.add_parser("run-task", help="普通用户主流程：自然语言需求 → 任务目录 → review_sheet.csv")
    prun.add_argument("--request", default="")
    prun.add_argument("--request-file", dest="request_file", default="")
    prun.add_argument("--offline", default="false")
    prun.add_argument("--offline-candidates", dest="offline_candidates", default="")
    prun.add_argument("--skip-format-probe", dest="skip_format_probe", default="false")
    prun.add_argument("--ai", default="true")
    prun.add_argument("--max-results", dest="max_results", default="")
    prun.set_defaults(func=cmd_run_task)

    pitf = sub.add_parser("import-task-feedback", help="导入某个 output/tasks/task_* 的人工审核反馈")
    pitf.add_argument("--task-dir", dest="task_dir", required=True)
    pitf.add_argument("--review-csv", dest="review_csv", required=True)
    pitf.add_argument("--ai", default="true")
    pitf.set_defaults(func=cmd_import_task_feedback)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
