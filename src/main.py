from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import exporters
from . import filters as filters_mod
from . import format_probe
from . import llm_candidate_filter as llm_gate
from . import llm_query_planner as llm_plan
from . import llm_strategy_optimizer as strat
from . import metadata_enrich
from . import youtube_search
from .llm_client import GrokUnsupportedError
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
    cfg = load_yaml_mapping(PROJECT_ROOT / "config" / "llm_config.yaml")
    return str((((cfg.get("cache") or {}) or {}).get("prompt_version")) or "v1")


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
    cfg_path = PROJECT_ROOT / "config" / "llm_config.yaml"
    prompts_path = PROJECT_ROOT / "config" / "llm_prompts.yaml"

    if want_llm:
        txt = inp.read_text(encoding="utf-8")
        cfg = load_yaml_mapping(cfg_path)

        lp = str(cfg.get("provider") or "").strip().lower()
        keys_ok = bool(os.environ.get("OPENROUTER_API_KEY", "").strip() or os.environ.get("OPENAI_API_KEY", "").strip())

        attempt_llm = want_llm
        if lp in ("grok", "xai", "x.ai"):
            print("[plan] WARN: Grok 尚未接入客户端 —详见 README", file=sys.stderr)
            attempt_llm = False
        elif not keys_ok:
            print("[plan] WARN: missing OPENROUTER/OPENAI Key —跳过 LLM planner", file=sys.stderr)
            attempt_llm = False

        if attempt_llm:
            try:
                blob = llm_plan.plan_with_llm(
                    user_text=txt,
                    llm_config_path=cfg_path,
                    prompts_path=prompts_path,
                    skill_prompt_version=_prompt_version(),
                )
            except (GrokUnsupportedError, RuntimeError, Exception) as exc:
                print(f"[plan] WARN: planner failed ({exc}) —fallback mechanical compose", file=sys.stderr)
                blob = None

    if blob and isinstance(blob.get("tasks"), list):
        dump_search_plan(outp, blob)
        print(f"[plan] llm-enhanced wrote -> {outp}")
        return 0

    if mechanical is not None:
        dump_search_plan(outp, mechanical)
        print(f"[plan] mechanical wrote -> {outp}")
        return 0

    print(
        "[plan] ERROR: 无法拼装 search_plan.yaml：需要提供 tasks YAML（search_tasks*.yaml），"
        "或启用 LLM 且配置 Key 以编译自然语言需求",
        file=sys.stderr,
    )
    return 2


def cmd_search(ns: argparse.Namespace) -> int:
    _root()
    key = youtube_search.ensure_api_key()
    if not key:
        print("[search] ERROR: YOUTUBE_API_KEY not set (.env)", file=sys.stderr)
        return 2
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
    key = metadata_enrich.youtube_api_key()

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
        gated = llm_gate.llm_semantic_gate_copy_skipped_defaults(rows)
        kept = [coerce_candidate(r) for r in gated]
        write_jsonl(outp, kept)
        write_jsonl(out_rej, [])
        print(f"[llm-filter] skipped LLM semantic gate ({len(kept)}) -> {outp}")
        return 0

    cfg_path = PROJECT_ROOT / "config" / "llm_config.yaml"
    prompts_path = PROJECT_ROOT / "config" / "llm_prompts.yaml"

    gated = llm_gate.annotate_candidates_llm(
        rows,
        llm_config_path=cfg_path,
        prompts_path=prompts_path,
        prompt_version=_prompt_version(),
    )

    kept: list[dict] = []
    rejected: list[dict] = []
    for r in gated:
        rr = coerce_candidate(dict(r))

        relevant = rr.get("llm_relevant")
        if relevant is False:
            codes = list(rr.get("rejection_codes") or [])
            if "llm_not_relevant" not in codes:
                codes.append("llm_not_relevant")
            rr["rejection_codes"] = codes
            rr["rejection_reason"] = (((rr.get("rejection_reason") or "") + "; ") if rr.get("rejection_reason") else "") + "LLM flagged not relevant"
            rr["rejection_stage"] = "llm"
            rr["hard_filter_pass"] = False
            rejected.append(rr)
        else:
            kept.append(rr)

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

    fallback_tasks = PROJECT_ROOT / "config" / "search_tasks.demo.yaml"

    llm_paths = PROJECT_ROOT / "config" / "llm_config.yaml"
    prompts = PROJECT_ROOT / "config" / "llm_prompts.yaml"

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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="YouTube URL sourcing / metadata / LLM filtering pipeline（无下载）")
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("plan", help="search_tasks.yaml|.txt → output/search_plan.yaml")
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
    pf.add_argument("--rules", default=str(PROJECT_ROOT / "config" / "filter_rules.yaml"))
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

    return p


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
