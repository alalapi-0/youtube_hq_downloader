from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import yaml

from .llm_cache import CacheParams, cache_fingerprint, read_cache, write_cache
from .llm_client import ChatMessage, GrokUnsupportedError, openai_compatible_chat_completion, require_non_empty_api_key
from .search_plan_builder import build_search_plan_from_tasks
from .utils import PROJECT_ROOT, load_yaml_mapping, read_jsonl


def _cache_dir(llm_cfg: Dict[str, Any]) -> Path:
    rel = (((llm_cfg or {}).get("cache") or {}) or {}).get("directory") or "cache"
    p = Path(rel)
    return p if p.is_absolute() else PROJECT_ROOT / p


def _gather_rejection_stats(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    codes: Counter[str] = Counter()
    n = 0
    for r in rows:
        n += 1
        for c in r.get("rejection_codes") or []:
            codes[str(c)] += 1
    return {"top_rejection_codes": codes.most_common(25), "rows": n}


def heuristic_mutate_plan(plan: Dict[str, Any], stats_rule: Dict[str, Any], stats_llm: Dict[str, Any]) -> Dict[str, Any]:
    mutated: Dict[str, Any] = json.loads(json.dumps(plan, ensure_ascii=False))
    glob = mutated.setdefault("global_rules", {})

    mr = int(glob.get("max_results_per_keyword") or 10)

    dup_hits = 0
    for code, count in stats_rule.get("top_rejection_codes") or []:
        if code == "dedupe_video_id":
            dup_hits += int(count)

    notes = list(mutated.get("_heuristic_notes") or [])
    if dup_hits >= 50 and mr > 3:
        glob["max_results_per_keyword"] = max(3, mr - 3)
        notes.append(f"reduced_cap_due_to_dedupe_hits≈{dup_hits}")

    if int(stats_llm.get("rows") or 0) >= 40:
        notes.append("high_llm_reject_volume_review_keywords")

    if notes:
        mutated["_heuristic_notes"] = notes
    return mutated


def strategy_optimize_heuristic_bundle(
    *,
    rule_rejected_path: Path,
    llm_rejected_path: Path,
    search_tasks_fallback: Path,
    current_plan_path: Path | None,
) -> Tuple[Dict[str, Any], str]:
    rej_rule = list(read_jsonl(rule_rejected_path))
    rej_llm = list(read_jsonl(llm_rejected_path)) if llm_rejected_path.exists() else []
    sr = _gather_rejection_stats(rej_rule)
    sl = _gather_rejection_stats(rej_llm)

    if current_plan_path and current_plan_path.exists():
        base_plan = yaml.safe_load(current_plan_path.read_text(encoding="utf-8"))
        if not isinstance(base_plan, dict):
            base_plan = {}
    else:
        base_plan = build_search_plan_from_tasks(search_tasks_fallback)

    plan2 = heuristic_mutate_plan(base_plan, sr, sl)

    md_lines = [
        "# Strategy optimization (heuristic)",
        "",
        "## Rule rejects",
        f"- rows: **{sr['rows']}**",
        "",
        "```json",
        json.dumps(sr["top_rejection_codes"][:15], ensure_ascii=False, indent=2),
        "```",
        "",
        "## LLM rejects",
        f"- rows: **{sl['rows']}**",
        "",
        "```json",
        json.dumps(sl["top_rejection_codes"][:15], ensure_ascii=False, indent=2),
        "```",
        "",
        "Mutated YAML 内嵌 `_heuristic_notes`。",
        "",
    ]
    md = "\n".join(md_lines)
    return plan2, md


def strategy_optimize_llm_bundle(
    *,
    rule_rejected_path: Path,
    llm_rejected_path: Path,
    search_tasks_fallback: Path,
    current_plan_path: Path | None,
    llm_config_path: Path,
    prompts_path: Path,
    prompt_version: str,
) -> Tuple[Dict[str, Any], str]:
    prompts = load_yaml_mapping(prompts_path)
    cfg = load_yaml_mapping(llm_config_path)
    provider = str(cfg.get("provider") or "openrouter")
    model = str(cfg.get("model") or "gpt-4o-mini")

    rej_rule = list(read_jsonl(rule_rejected_path))
    rej_llm = list(read_jsonl(llm_rejected_path)) if llm_rejected_path.exists() else []
    sr = _gather_rejection_stats(rej_rule)
    sl = _gather_rejection_stats(rej_llm)

    if current_plan_path and current_plan_path.exists():
        cur_txt = current_plan_path.read_text(encoding="utf-8")
    else:
        cur_txt = yaml.safe_dump(
            build_search_plan_from_tasks(search_tasks_fallback),
            allow_unicode=True,
            sort_keys=False,
        )

    fused = {"rule_stats": sr, "llm_stats": sl}
    inp = yaml.safe_dump(
        {"statistics": fused, "current_plan_yaml": cur_txt},
        allow_unicode=True,
        sort_keys=False,
    )

    fingerprint = cache_fingerprint(
        CacheParams(
            provider=provider,
            model=model,
            skill_name="strategy_optimizer",
            prompt_version=prompt_version,
            input_text=inp,
        )
    )
    cdir = _cache_dir(cfg)

    cached = read_cache(cdir, fingerprint)
    if cached and isinstance(cached["parsed"], dict) and cached["parsed"].get("plan_yaml_text"):
        text = str(cached["parsed"]["plan_yaml_text"])
        plan = yaml.safe_load(text)
        md_cached = str(cached["parsed"].get("markdown") or "# Strategy optimization (cached)\n")
        return (plan if isinstance(plan, dict) else {}), md_cached

    sys_msg = str(prompts.get("strategy_optimizer_system") or "").strip()

    try:
        base, api_key = require_non_empty_api_key(provider, cfg)
        raw = openai_compatible_chat_completion(
            base_url=base,
            api_key=api_key,
            model=model,
            messages=[
                ChatMessage("system", sys_msg),
                ChatMessage(
                    "user",
                    "STATISTICS_AND_PLAN:\n```yaml\n" + inp + "\n```\nReturn ONLY YAML for full search_plan.\n",
                ),
            ],
            temperature=float(cfg.get("temperature") or 0.2),
            max_tokens=int(((cfg.get("max_output_tokens") or 4096))),
        )
        parsed_plan = yaml.safe_load(raw)
        if not isinstance(parsed_plan, dict):
            raise ValueError("LLM YAML not mapping")
        md_out = "## LLM mutated plan\n\n```yaml\n" + raw.strip() + "\n```\n"
        meta = {"provider": provider, "model": model, "skill": "strategy_optimizer"}
        write_cache(cdir, fingerprint, meta=meta, raw_text=raw, parsed={"plan_yaml_text": raw, "markdown": md_out})
        return parsed_plan, md_out
    except (GrokUnsupportedError, RuntimeError, ValueError):
        pass
    except Exception:
        pass

    return strategy_optimize_heuristic_bundle(
        rule_rejected_path=rule_rejected_path,
        llm_rejected_path=llm_rejected_path,
        search_tasks_fallback=search_tasks_fallback,
        current_plan_path=current_plan_path,
    )
