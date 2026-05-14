from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import exporters
from . import filters as filters_mod
from . import format_probe
from . import metadata_enrich
from . import youtube_search
from .utils import PROJECT_ROOT, read_jsonl, write_jsonl


def _root() -> Path:
    load_dotenv(PROJECT_ROOT / ".env")
    return PROJECT_ROOT


def cmd_search(ns: argparse.Namespace) -> int:
    _root()
    key = youtube_search.ensure_api_key()
    if not key:
        print("[search] ERROR: YOUTUBE_API_KEY not set (.env)", file=sys.stderr)
        return 2
    task_path = Path(ns.task).resolve()
    outp = Path(ns.output).resolve()
    rows = youtube_search.run_search_tasks(task_path, key)
    write_jsonl(outp, rows)
    print(f"[search] wrote {len(rows)} rows -> {outp}")
    return 0


def cmd_enrich(ns: argparse.Namespace) -> int:
    _root()
    inp = Path(ns.input).resolve()
    outp = Path(ns.output).resolve()
    rows = list(read_jsonl(inp))
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
    write_jsonl(outp, enriched)
    print(f"[enrich] enriched {len(enriched)} rows -> {outp}")
    return 0


def cmd_probe(ns: argparse.Namespace) -> int:
    _root()
    inp = Path(ns.input).resolve()
    outp = Path(ns.output).resolve()
    rows = list(read_jsonl(inp))
    probed = format_probe.probe_records(rows)
    write_jsonl(outp, probed)
    print(f"[probe-format] wrote {len(probed)} rows -> {outp}")
    return 0


def cmd_filter(ns: argparse.Namespace) -> int:
    root = _root()
    inp = Path(ns.input).resolve()
    rules_path = Path(ns.rules).resolve()
    out_ok = Path(ns.output).resolve()
    out_bad = Path(ns.rejected).resolve()
    rows = list(read_jsonl(inp))
    keep, rej = filters_mod.apply_filters(rows, rules_path, root)
    write_jsonl(out_ok, keep)
    write_jsonl(out_bad, rej)
    print(f"[filter] keep={len(keep)} rej={len(rej)} ok->{out_ok} rej->{out_bad}")
    return 0


def cmd_export(ns: argparse.Namespace) -> int:
    _root()
    outp = Path(ns.output_dir).resolve()
    inp = Path(ns.input).resolve()
    rows = list(read_jsonl(inp))

    fmt = (ns.format or "all").lower()

    rej_candidates: list[Path] = []
    if inp.parent.name == "filtered":
        rej_candidates.append(inp.parent.parent / "rejected" / "rejected.jsonl")
    rej_candidates.append(PROJECT_ROOT / "data" / "rejected" / "rejected.jsonl")

    rej_rows: list = []
    for rp in rej_candidates:
        if rp.exists():
            rej_rows = list(read_jsonl(rp))
            break

    if fmt == "all":
        exporters.export_all(rows, outp, rejected=rej_rows)
    elif fmt == "csv":
        exporters.export_csv(rows, outp / "csv" / "filtered_urls.csv")
    elif fmt == "jsonl":
        exporters.export_jsonl(rows, outp / "jsonl" / "filtered_urls.jsonl")
    elif fmt == "markdown":
        exporters.export_markdown(rows, outp / "markdown" / "filtered_urls.md", rejected=rej_rows)
    else:
        print(f"[export] unknown format: {fmt}", file=sys.stderr)
        return 2

    print(f"[export] done -> {outp}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="YouTube URL sourcing / metadata / filtering (no downloads)")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("search", help="search_tasks.yaml → candidates jsonl")
    ps.add_argument("--task", required=True)
    ps.add_argument("--output", required=True)
    ps.set_defaults(func=cmd_search)

    pe = sub.add_parser("enrich", help="videos.list enrichment")
    pe.add_argument("--input", required=True)
    pe.add_argument("--output", required=True)
    pe.set_defaults(func=cmd_enrich)

    pp = sub.add_parser("probe-format", help="yt-dlp probe (optional)")
    pp.add_argument("--input", required=True)
    pp.add_argument("--output", required=True)
    pp.set_defaults(func=cmd_probe)

    pf = sub.add_parser("filter", help="Apply filter rules")
    pf.add_argument("--input", required=True)
    pf.add_argument("--rules", required=True)
    pf.add_argument("--output", required=True)
    pf.add_argument("--rejected", required=True)
    pf.set_defaults(func=cmd_filter)

    px = sub.add_parser("export", help="Export filtered URLs")
    px.add_argument("--input", required=True)
    px.add_argument("--format", default="all", choices=["all", "csv", "jsonl", "markdown"])
    px.add_argument("--output-dir", required=True)
    px.set_defaults(func=cmd_export)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
