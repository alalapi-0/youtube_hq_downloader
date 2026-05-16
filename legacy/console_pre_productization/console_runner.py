from __future__ import annotations

import getpass
import os
import platform
import subprocess
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from . import console_checks
from . import console_config_editor
from . import console_menu as menus
from . import console_wizard as wiz
from .main import (
    cmd_analyze_feedback,
    cmd_analyze_url,
    cmd_enrich,
    cmd_export,
    cmd_export_review,
    cmd_filter,
    cmd_import_review,
    cmd_llm_analyze_feedback,
    cmd_llm_filter,
    cmd_plan,
    cmd_probe,
    cmd_search,
    cmd_strategy,
    cmd_strategy_from_feedback,
)
from . import review_feedback_analyzer
from .search_plan_builder import dump_search_plan, load_search_plan
from .utils import PROJECT_ROOT, read_jsonl


def demo_cap() -> int:
    raw = (os.environ.get("DEMO_MAX") or "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return 3


def _jsonl_len(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for _ in read_jsonl(path))


def open_native_path(path: Path) -> tuple[bool, str]:
    p = path.resolve()
    if not p.exists():
        p.mkdir(parents=True, exist_ok=True)
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", str(p)], check=False)
        elif system == "Windows":
            subprocess.run(["explorer", str(p)], check=False)
        else:
            subprocess.run(["xdg-open", str(p)], check=False)
        return True, str(p)
    except Exception as exc:
        return False, f"{p} （打开失败: {exc}）"


def run_env_check(*, use_rich: bool) -> None:
    report = console_checks.run_full_env_check()
    body = console_checks.summarize_env_check(report)
    menus.print_panel("环境检查结果", body, use_rich=use_rich)
    wiz.log_console_event("env_check completed")


def run_api_key_wizard(*, use_rich: bool) -> None:
    while True:
        menus.print_panel(
            "API 密钥向导",
            "\n".join(
                [
                    "1. 设置 YOUTUBE_API_KEY",
                    "2. 设置 OPENROUTER_API_KEY",
                    "3. 设置 OPENAI_API_KEY",
                    "4. 从 .env.example 补齐缺失键（不覆盖已有值）",
                    "5. 返回主菜单",
                ]
            ),
            use_rich=use_rich,
        )
        choice = menus.prompt_line("请选择 1-5", default="5", use_rich=use_rich)
        if choice in ("5",):
            break
        if choice == "4":
            created = wiz.ensure_dotenv_from_example()
            added = wiz.merge_missing_keys_from_example()
            if created:
                menus.print_info("已从 .env.example 创建 .env", use_rich=use_rich)
            if added:
                menus.print_info(f"已补齐键：{', '.join(added)}", use_rich=use_rich)
            else:
                menus.print_info("无缺失键或 .env.example 不存在。", use_rich=use_rich)
            gi_ok, gi_p = console_checks.gitignore_has_env()
            menus.print_info(f".gitignore 含 .env: {'是' if gi_ok else '否'} ({gi_p})", use_rich=use_rich)
            wiz.log_console_event("api_wizard merge_missing_from_example")
            continue
        keyname = {
            "1": "YOUTUBE_API_KEY",
            "2": "OPENROUTER_API_KEY",
            "3": "OPENAI_API_KEY",
        }.get(choice)
        if not keyname:
            menus.print_warn("无效选项。", use_rich=use_rich)
            continue
        wiz.ensure_dotenv_from_example()
        secret = getpass.getpass(f"请输入 {keyname}（不回显，留空取消）: ").strip()
        if not secret:
            menus.print_warn("已取消。", use_rich=use_rich)
            continue
        wiz.merge_env_key(keyname, secret)
        menus.print_info(f"已写入 {keyname}，尾号：****{secret[-4:]}", use_rich=use_rich)
        gi_ok, gi_p = console_checks.gitignore_has_env()
        if not gi_ok:
            menus.print_warn("警告：.gitignore 未明确忽略 .env，请手动检查！", use_rich=use_rich)
        else:
            menus.print_info(f".gitignore OK: {gi_p}", use_rich=use_rich)
        wiz.log_console_event(f"api_wizard set {keyname} (masked)")


def run_search_task_wizard(*, use_rich: bool) -> Path | None:
    out_plan = PROJECT_ROOT / "output" / "search_plan.yaml"
    menus.print_panel(
        "检索任务向导",
        "\n".join(
            [
                "1. 从 config/search_tasks.demo.yaml 生成（小流量演示）",
                "2. 从 config/search_tasks.yaml 生成（生产默认）",
                "3. 交互式拼装单任务（品牌品类 + 关键词）",
                "4. 载入自定义 search_tasks*.yaml 并生成",
                "5. 返回主菜单",
            ]
        ),
        use_rich=use_rich,
    )
    choice = menus.prompt_line("请选择 1-5", default="5", use_rich=use_rich)
    if choice == "5":
        return None
    cats = console_checks.brand_categories()

    def finish_from_tasks_yaml(tp: Path) -> Path | None:
        if not tp.exists():
            menus.print_err(f"未找到：{tp}", use_rich=use_rich)
            return None
        plan = wiz.build_and_dump_plan_from_tasks_yaml(tp, out_plan)
        nt, est = wiz.count_plan_stats(plan)
        menus.print_info(f"已写入 {out_plan}（任务数={nt}，粗估检索上限≈{est} 条记录）", use_rich=use_rich)
        wiz.log_console_event(f"search_wizard wrote plan from {tp}")
        return out_plan

    if choice == "1":
        return finish_from_tasks_yaml(PROJECT_ROOT / "config" / "search_tasks.demo.yaml")
    if choice == "2":
        return finish_from_tasks_yaml(PROJECT_ROOT / "config" / "search_tasks.yaml")
    if choice == "4":
        rel = menus.prompt_line("YAML 相对项目根路径", default="config/search_tasks.yaml", use_rich=use_rich)
        return finish_from_tasks_yaml((PROJECT_ROOT / rel).resolve())
    if choice != "3":
        menus.print_warn("无效选项。", use_rich=use_rich)
        return None

    menus.print_info(
        "品牌品类：" + (", ".join(cats) if cats else "（未解析到，可留空）"),
        use_rich=use_rich,
    )
    picked: list[str] = []
    if cats:
        raw_c = menus.prompt_line("输入要启用的品类（逗号分隔，可空）", default="", use_rich=use_rich)
        for part in raw_c.split(","):
            p = part.strip()
            if p in cats:
                picked.append(p)
            elif p:
                menus.print_warn(f"忽略未知品类：{p}", use_rich=use_rich)
    brands: list[str] = []
    for c in picked:
        brands.extend(console_checks.brand_names_for_category(c))
    brands = sorted(set(brands))
    kw_raw = menus.prompt_line("关键词（逗号分隔）", default="luxury commercial cinematic", use_rich=use_rich)
    keywords = [k.strip() for k in kw_raw.split(",") if k.strip()]
    tid = menus.prompt_line("任务 ID", default="console_task", use_rich=use_rich)
    cat = menus.prompt_line("category", default="campaigns", use_rich=use_rich)
    sub = menus.prompt_line("subcategory", default="product", use_rich=use_rich)
    reg = menus.prompt_line("region_code", default="US", use_rich=use_rich)
    lang = menus.prompt_line("relevance_language", default="en", use_rich=use_rich)
    cap = menus.prompt_int("max_results_per_keyword", default=3, min_v=1, max_v=50, use_rich=use_rich)
    if cap is None:
        cap = 3
    tmp = PROJECT_ROOT / "output" / "_console_tasks.generated.yaml"
    doc = wiz.interactive_task_document(
        task_id=tid,
        category=cat,
        subcategory=sub,
        keywords=keywords,
        brands=brands,
        region_code=reg,
        relevance_language=lang,
        max_results_per_keyword=int(cap),
    )
    wiz.write_search_tasks_temp(doc["project"], doc["tasks"], tmp)
    return finish_from_tasks_yaml(tmp)


def run_llm_plan_flow(session: Any, *, use_rich: bool) -> None:
    use_llm = menus.confirm(
        "是否启用 LLM 增强 plan（将调用 API，建议先确认 Key）？",
        default_no=True,
        use_rich=use_rich,
    )
    session.llm_enabled = bool(use_llm)
    out_plan = PROJECT_ROOT / "output" / "search_plan.yaml"
    menus.print_panel(
        "输入来源",
        "1. 直接粘贴/输入自然语言（单段，结束输入单独一行 END）\n"
        "2. 从 examples/user_request.example.txt 载入\n"
        "3. 自行指定 .txt/.yaml 路径",
        use_rich=use_rich,
    )
    mode = menus.prompt_line("选择 1-3", default="2", use_rich=use_rich)
    text = ""
    in_path: Path | None = None
    if mode == "2":
        in_path = PROJECT_ROOT / "examples" / "user_request.example.txt"
    elif mode == "3":
        rel = menus.prompt_line("相对项目根路径", default="examples/user_request.example.txt", use_rich=use_rich)
        in_path = (PROJECT_ROOT / rel).resolve()
    if in_path is not None:
        if not in_path.exists():
            menus.print_err(f"未找到：{in_path}", use_rich=use_rich)
            return
        text = in_path.read_text(encoding="utf-8")
    else:
        menus.print_info("输入自然语言，单独一行 END 结束：", use_rich=use_rich)
        lines: list[str] = []
        while True:
            line = input()
            if line.strip() == "END":
                break
            lines.append(line)
        text = "\n".join(lines).strip()
    if not text and mode != "3":
        menus.print_err("内容为空。", use_rich=use_rich)
        return

    tmp_txt = PROJECT_ROOT / "output" / "_console_user_request.txt"
    tmp_txt.parent.mkdir(parents=True, exist_ok=True)
    tmp_txt.write_text(text, encoding="utf-8")

    ns = SimpleNamespace(
        input=str(tmp_txt),
        output=str(out_plan),
        use_llm="true" if use_llm else "false",
    )
    if use_llm and not menus.confirm("确认发起 LLM plan 调用？", default_no=True, use_rich=use_rich):
        menus.print_warn("已取消。", use_rich=use_rich)
        return
    code = cmd_plan(ns)
    if code != 0:
        menus.print_err(f"plan 失败（exit={code}）。可检查日志或改用机械拼装。", use_rich=use_rich)
        wiz.log_console_event("llm_plan failed")
        return
    menus.print_info(f"已生成：{out_plan}", use_rich=use_rich)
    if out_plan.exists():
        preview = out_plan.read_text(encoding="utf-8")
        head = "\n".join(preview.splitlines()[:40])
        menus.print_panel("预览（前 40 行）", head, use_rich=use_rich)
    after = menus.prompt_line("保存完成。输入 y 打开文件目录，其它返回", default="n", use_rich=use_rich).lower()
    if after in ("y", "yes", "是"):
        ok, msg = open_native_path(out_plan.parent)
        menus.print_info(msg if ok else msg, use_rich=use_rich)
    session.last_search_plan = out_plan
    wiz.log_console_event("llm_plan ok")


def _resolve_plan_for_search(*, test_mode: bool) -> Path:
    base = PROJECT_ROOT / "output" / "search_plan.yaml"
    if not test_mode or not base.exists():
        return base
    plan = load_search_plan(base)
    cap = demo_cap()
    capped = wiz.apply_max_results_cap(plan, cap)
    p = PROJECT_ROOT / "output" / "_console_search_plan.capped.yaml"
    dump_search_plan(p, capped)
    return p


def run_full_pipeline(session: Any, *, use_rich: bool) -> None:
    menus.print_panel(
        "一键流水线",
        "测试模式：自动 cap=max(DEMO_MAX,默认3)；生产模式：使用 output/search_plan.yaml 原始配额。\n"
        "链：search → enrich → probe → filter → llm-filter（可关） → export。",
        use_rich=use_rich,
    )
    test = menus.confirm("启用测试模式（低配额）？", default_no=False, use_rich=use_rich)
    if not test:
        if not menus.confirm("生产模式将按 plan 配额调用 YouTube API，二次确认继续？", default_no=True, use_rich=use_rich):
            menus.print_warn("已取消。", use_rich=use_rich)
            return
        if not menus.confirm("最后确认：生产检索将消耗配额，继续？", default_no=True, use_rich=use_rich):
            menus.print_warn("已取消。", use_rich=use_rich)
            return
    else:
        menus.print_info(f"测试模式 cap={demo_cap()}（可用环境变量 DEMO_MAX 覆盖）", use_rich=use_rich)

    plan_path = _resolve_plan_for_search(test_mode=bool(test))
    if not plan_path.exists():
        menus.print_err(f"缺少检索计划：{plan_path}（请先用菜单 3/4 生成）", use_rich=use_rich)
        return

    use_llm_gate = menus.confirm("是否启用 LLM 语义闸（消耗 LLM API）？", default_no=True, use_rich=use_rich)
    session.llm_enabled = bool(use_llm_gate)
    if use_llm_gate and not menus.confirm("确认调用 LLM 批闸？", default_no=True, use_rich=use_rich):
        use_llm_gate = False

    paths = {
        "raw": PROJECT_ROOT / "data" / "raw" / "candidates.jsonl",
        "enriched": PROJECT_ROOT / "data" / "enriched" / "enriched.jsonl",
        "probed": PROJECT_ROOT / "data" / "enriched" / "probed.jsonl",
        "rule_ok": PROJECT_ROOT / "data" / "filtered" / "rule_filtered.jsonl",
        "rule_rej": PROJECT_ROOT / "data" / "rejected" / "rule_rejected.jsonl",
        "llm_ok": PROJECT_ROOT / "data" / "filtered" / "llm_filtered.jsonl",
        "llm_rej": PROJECT_ROOT / "data" / "rejected" / "llm_rejected.jsonl",
        "export_dir": PROJECT_ROOT / "output",
    }

    def step_log(name: str, ok: bool) -> None:
        wiz.log_console_event(f"pipeline {name} {'ok' if ok else 'fail'}")

    ns = SimpleNamespace(task=str(plan_path), output=str(paths["raw"]))
    if not menus.confirm("开始 YouTube search（API）？", default_no=True, use_rich=use_rich):
        menus.print_warn("在 search 前取消。", use_rich=use_rich)
        return
    rc = cmd_search(ns)
    if rc != 0:
        menus.print_err("search 失败。", use_rich=use_rich)
        step_log("search", False)
        return
    step_log("search", True)
    menus.print_info(f"search 行数={_jsonl_len(paths['raw'])}", use_rich=use_rich)

    rc = cmd_enrich(SimpleNamespace(input=str(paths["raw"]), output=str(paths["enriched"])))
    step_log("enrich", rc == 0)
    menus.print_info(f"enrich 行数={_jsonl_len(paths['enriched'])}", use_rich=use_rich)

    rc = cmd_probe(SimpleNamespace(input=str(paths["enriched"]), output=str(paths["probed"])))
    step_log("probe", rc == 0)
    menus.print_info(f"probe 行数={_jsonl_len(paths['probed'])}", use_rich=use_rich)

    rc = cmd_filter(
        SimpleNamespace(
            input=str(paths["probed"]),
            rules=str(PROJECT_ROOT / "config" / "filter_rules.yaml"),
            output=str(paths["rule_ok"]),
            rejected=str(paths["rule_rej"]),
        )
    )
    step_log("filter", rc == 0)
    menus.print_info(
        f"filter keep={_jsonl_len(paths['rule_ok'])} rej={_jsonl_len(paths['rule_rej'])}",
        use_rich=use_rich,
    )

    rc = cmd_llm_filter(
        SimpleNamespace(
            input=str(paths["rule_ok"]),
            output=str(paths["llm_ok"]),
            rejected=str(paths["llm_rej"]),
            use_llm="true" if use_llm_gate else "false",
        )
    )
    step_log("llm-filter", rc == 0)
    menus.print_info(
        f"llm-filter keep={_jsonl_len(paths['llm_ok'])} rej={_jsonl_len(paths['llm_rej'])}",
        use_rich=use_rich,
    )

    rc = cmd_export(
        SimpleNamespace(
            input=str(paths["llm_ok"]),
            format="all",
            output_dir=str(paths["export_dir"]),
            rejected_rule=str(paths["rule_rej"]),
            rejected_llm=str(paths["llm_rej"]),
        )
    )
    step_log("export", rc == 0)
    session.last_rule_filtered = paths["rule_ok"]
    session.last_llm_filtered = paths["llm_ok"]
    menus.print_info("流水线完成。导出目录：output/{csv,jsonl,markdown}/", use_rich=use_rich)


def _pick_existing(default: Path, label: str, use_rich: bool) -> Path:
    if default.exists():
        return default
    menus.print_warn(f"{label} 默认不存在：{default}", use_rich=use_rich)
    rel = menus.prompt_line("提供替代相对路径或回车跳过", default="", use_rich=use_rich)
    if not rel:
        return default
    return (PROJECT_ROOT / rel).resolve()


def run_step_by_step(session: Any, *, use_rich: bool) -> None:
    menus.print_panel("分步运行", "逐步执行并可自定义路径；缺省会提示回退。", use_rich=use_rich)
    if menus.confirm("是否先编辑 filter_rules / llm_config？", default_no=True, use_rich=use_rich):
        run_config_editor(use_rich=use_rich)

    plan_default = PROJECT_ROOT / "output" / "search_plan.yaml"
    plan = _pick_existing(plan_default, "search_plan.yaml", use_rich)
    raw = _pick_existing(PROJECT_ROOT / "data" / "raw" / "candidates.jsonl", "原始 candidates", use_rich)

    step = menus.prompt_line("起始步骤 search/enrich/probe/filter/llm-filter/export", default="search", use_rich=use_rich).lower()
    cap_prompt = menus.confirm("search 前自动套用 DEMO_MAX 低配额？", default_no=False, use_rich=use_rich)
    plan_for_search = plan
    if cap_prompt and plan.exists():
        plan_for_search = _resolve_plan_for_search(test_mode=True)

    paths = {
        "raw": raw,
        "enriched": PROJECT_ROOT / "data" / "enriched" / "enriched.jsonl",
        "probed": PROJECT_ROOT / "data" / "enriched" / "probed.jsonl",
        "rule_ok": PROJECT_ROOT / "data" / "filtered" / "rule_filtered.jsonl",
        "rule_rej": PROJECT_ROOT / "data" / "rejected" / "rule_rejected.jsonl",
        "llm_ok": PROJECT_ROOT / "data" / "filtered" / "llm_filtered.jsonl",
        "llm_rej": PROJECT_ROOT / "data" / "rejected" / "llm_rejected.jsonl",
        "export_dir": PROJECT_ROOT / "output",
    }

    order = ["search", "enrich", "probe", "filter", "llm-filter", "export"]
    if step not in order:
        menus.print_warn("未知步骤，默认 search。", use_rich=use_rich)
        step = "search"
    i0 = order.index(step)

    for name in order[i0:]:
        if name == "search":
            if not plan_for_search.exists():
                menus.print_err("缺少 search_plan，终止。", use_rich=use_rich)
                return
            if not menus.confirm("执行 search（YouTube API）？", default_no=True, use_rich=use_rich):
                menus.print_warn("跳过 search。", use_rich=use_rich)
                continue
            rc = cmd_search(SimpleNamespace(task=str(plan_for_search), output=str(paths["raw"])))
            menus.print_info(f"search rc={rc} rows={_jsonl_len(paths['raw'])}", use_rich=use_rich)
            wiz.log_console_event(f"step search rc={rc}")
        elif name == "enrich":
            inp = _pick_existing(paths["raw"], "enrich 输入", use_rich)
            rc = cmd_enrich(SimpleNamespace(input=str(inp), output=str(paths["enriched"])))
            menus.print_info(f"enrich rc={rc} rows={_jsonl_len(paths['enriched'])}", use_rich=use_rich)
            wiz.log_console_event(f"step enrich rc={rc}")
        elif name == "probe":
            inp = _pick_existing(paths["enriched"], "probe 输入", use_rich)
            rc = cmd_probe(SimpleNamespace(input=str(inp), output=str(paths["probed"])))
            menus.print_info(f"probe rc={rc} rows={_jsonl_len(paths['probed'])}", use_rich=use_rich)
            wiz.log_console_event(f"step probe rc={rc}")
        elif name == "filter":
            inp = _pick_existing(paths["probed"], "filter 输入", use_rich)
            rc = cmd_filter(
                SimpleNamespace(
                    input=str(inp),
                    rules=str(PROJECT_ROOT / "config" / "filter_rules.yaml"),
                    output=str(paths["rule_ok"]),
                    rejected=str(paths["rule_rej"]),
                )
            )
            menus.print_info(
                f"filter rc={rc} keep={_jsonl_len(paths['rule_ok'])} rej={_jsonl_len(paths['rule_rej'])}",
                use_rich=use_rich,
            )
            wiz.log_console_event(f"step filter rc={rc}")
        elif name == "llm-filter":
            use_llm = menus.confirm("llm-filter 启用真实 LLM？", default_no=True, use_rich=use_rich)
            inp = _pick_existing(paths["rule_ok"], "llm-filter 输入", use_rich)
            rc = cmd_llm_filter(
                SimpleNamespace(
                    input=str(inp),
                    output=str(paths["llm_ok"]),
                    rejected=str(paths["llm_rej"]),
                    use_llm="true" if use_llm else "false",
                )
            )
            menus.print_info(
                f"llm-filter rc={rc} keep={_jsonl_len(paths['llm_ok'])} rej={_jsonl_len(paths['llm_rej'])}",
                use_rich=use_rich,
            )
            wiz.log_console_event(f"step llm-filter rc={rc}")
        elif name == "export":
            inp = _pick_existing(paths["llm_ok"], "export 输入", use_rich)
            rc = cmd_export(
                SimpleNamespace(
                    input=str(inp),
                    format="all",
                    output_dir=str(paths["export_dir"]),
                    rejected_rule=str(paths["rule_rej"]),
                    rejected_llm=str(paths["llm_rej"]),
                )
            )
            menus.print_info(f"export rc={rc}", use_rich=use_rich)
            wiz.log_console_event(f"step export rc={rc}")

    session.last_rule_filtered = paths["rule_ok"]
    session.last_llm_filtered = paths["llm_ok"]


def _preview_jsonl(path: Path, *, n: int = 10, use_rich: bool) -> None:
    if not path.exists():
        menus.print_err(f"不存在：{path}", use_rich=use_rich)
        return
    lines: list[str] = []
    for i, row in enumerate(read_jsonl(path)):
        if i >= n:
            break
        lines.append(str(row))
    menus.print_panel(f"前 {n} 行 JSON", "\n".join(lines) if lines else "（空）", use_rich=use_rich)
    try:
        import pandas as pd  # type: ignore

        df = pd.read_json(path, lines=True)
        menus.print_info(f"pandas 行数={len(df)} 列数={len(df.columns)}", use_rich=use_rich)
        menus.print_panel("pandas 列预览", df.head(5).to_string(), use_rich=use_rich)
    except Exception:
        menus.print_info("pandas 不可用或解析失败，已跳过表格预览。", use_rich=use_rich)


def run_view_filtered(*, use_rich: bool) -> None:
    rule = PROJECT_ROOT / "data" / "filtered" / "rule_filtered.jsonl"
    llm = PROJECT_ROOT / "data" / "filtered" / "llm_filtered.jsonl"
    menus.print_panel(
        "选择预览",
        "1 rule_filtered.jsonl\n2 llm_filtered.jsonl\n3 两者",
        use_rich=use_rich,
    )
    c = menus.prompt_line("1-3", default="3", use_rich=use_rich)
    if c in ("1", "3"):
        menus.print_info(str(rule), use_rich=use_rich)
        _preview_jsonl(rule, use_rich=use_rich)
    if c in ("2", "3"):
        menus.print_info(str(llm), use_rich=use_rich)
        _preview_jsonl(llm, use_rich=use_rich)


def _aggregate_rejections(paths: list[Path]) -> Counter[str]:
    ctr: Counter[str] = Counter()
    for p in paths:
        for row in read_jsonl(p):
            codes = row.get("rejection_codes") or []
            if isinstance(codes, list) and codes:
                for code in codes:
                    ctr[str(code)] += 1
            else:
                ctr["(no_code)"] += 1
    return ctr


def run_rejected_stats(*, use_rich: bool) -> None:
    rr = PROJECT_ROOT / "data" / "rejected" / "rule_rejected.jsonl"
    lr = PROJECT_ROOT / "data" / "rejected" / "llm_rejected.jsonl"
    rows = [
        ("rule_rejected", str(rr), _jsonl_len(rr)),
        ("llm_rejected", str(lr), _jsonl_len(lr)),
    ]
    menus.show_table(["阶段", "路径", "行数"], rows, title="拒收体积", use_rich=use_rich)
    ctr = _aggregate_rejections([rr, lr])
    top = ctr.most_common(25)
    menus.show_table(["rejection_code", "count"], top, title="合并拒收代码 Top 25", use_rich=use_rich)
    if menus.confirm("导出 output/markdown/rejected_summary.md？", default_no=True, use_rich=use_rich):
        md_dir = PROJECT_ROOT / "output" / "markdown"
        md_dir.mkdir(parents=True, exist_ok=True)
        out = md_dir / "rejected_summary.md"
        lines = ["# Rejected summary", "", "## 体积", ""]
        for name, p, n in rows:
            lines.append(f"- **{name}**: `{p}` → {n} 行")
        lines.extend(["", "## 代码分布", ""])
        for k, v in ctr.most_common():
            lines.append(f"- `{k}`: **{v}**")
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        menus.print_info(f"已写入 {out}", use_rich=use_rich)
        wiz.log_console_event("rejected_summary written")


def run_strategy_flow(session: Any, *, use_rich: bool) -> None:
    use_llm = menus.confirm("strategy-optimize 使用 LLM？", default_no=not session.llm_enabled, use_rich=use_rich)
    if use_llm and not menus.confirm("将调用 LLM，确认？", default_no=True, use_rich=use_rich):
        use_llm = False
    session.llm_enabled = bool(use_llm)

    rr = PROJECT_ROOT / "data" / "rejected" / "rule_rejected.jsonl"
    lr = PROJECT_ROOT / "data" / "rejected" / "llm_rejected.jsonl"
    cur = PROJECT_ROOT / "output" / "search_plan.yaml"
    out_md = PROJECT_ROOT / "docs" / "strategy_notes.md"
    out_yaml = PROJECT_ROOT / "output" / "search_plan.next.yaml"

    ns = SimpleNamespace(
        rule_rejected=str(rr),
        llm_rejected=str(lr),
        current_plan=str(cur) if cur.exists() else "",
        output_md=str(out_md),
        output_yaml=str(out_yaml),
        use_llm="true" if use_llm else "false",
    )
    rc = cmd_strategy(ns)
    menus.print_info(f"strategy-optimize rc={rc} md={out_md} yaml={out_yaml}", use_rich=use_rich)
    wiz.log_console_event(f"strategy rc={rc} use_llm={use_llm}")


def _prompt_project_path(prompt: str, default: str, *, use_rich: bool) -> Path:
    raw = menus.prompt_line(prompt, default=default, use_rich=use_rich).strip()
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()


def _preview_text_file(path: Path, *, title: str, use_rich: bool, max_lines: int = 80) -> None:
    if not path.exists():
        menus.print_warn(f"文件不存在：{path}", use_rich=use_rich)
        return
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[:max_lines]
    menus.print_panel(title, "\n".join(lines) if lines else "（空）", use_rich=use_rich)


def _default_feedback_paths() -> dict[str, Path]:
    return {
        "analysis": PROJECT_ROOT / "data" / "url_analysis" / "url_analysis.jsonl",
        "review_csv": PROJECT_ROOT / "output" / "review" / "review_sheet.csv",
        "filled_csv": PROJECT_ROOT / "output" / "review" / "review_sheet_filled.csv",
        "manual": PROJECT_ROOT / "data" / "manual_reviews" / "manual_reviewed.jsonl",
        "feedback_md": PROJECT_ROOT / "output" / "strategy" / "feedback_analysis.md",
        "feedback_json": PROJECT_ROOT / "data" / "feedback_analysis" / "feedback_analysis.json",
        "rule_md": PROJECT_ROOT / "output" / "strategy" / "rule_based_next_search_strategy.md",
        "rule_yaml": PROJECT_ROOT / "output" / "strategy" / "rule_based_next_search_plan.yaml",
        "llm_md": PROJECT_ROOT / "output" / "strategy" / "llm_feedback_strategy.md",
        "llm_yaml": PROJECT_ROOT / "output" / "strategy" / "llm_next_search_plan.yaml",
    }


def run_url_feedback_loop(session: Any, *, use_rich: bool) -> None:
    paths = _default_feedback_paths()
    while True:
        menus.print_panel(
            "URL 分析与人工反馈闭环",
            "\n".join(
                [
                    "1. 分析一批 URL 页面元数据",
                    "2. 导出人工审核表",
                    "3. 导入人工审核结果",
                    "4. 查看人工审核通过率",
                    "5. 分析通过/不通过特征",
                    "6. 使用 LLM 分析反馈并生成下一轮搜索计划",
                    "7. 查看下一轮搜索策略文件",
                    "0. 返回主菜单",
                ]
            ),
            use_rich=use_rich,
        )
        choice = menus.prompt_line("请选择 0-7", default="0", use_rich=use_rich).strip()
        if choice == "0":
            return
        if choice == "1":
            inp = _prompt_project_path("输入 URL/CSV/JSONL", "examples/candidates.example.jsonl", use_rich=use_rich)
            out = _prompt_project_path("输出 analysis JSONL", str(paths["analysis"].relative_to(PROJECT_ROOT)), use_rich=use_rich)
            offline = menus.confirm("仅使用已有字段（不访问 API/yt-dlp/网页）？", default_no=False, use_rich=use_rich)
            cookie_file = ""
            cookies_browser = ""
            if not offline and menus.confirm("是否显式使用 cookie.txt 文件？", default_no=True, use_rich=use_rich):
                cookie_file = str(_prompt_project_path("cookie.txt 路径", "private/cookies.txt", use_rich=use_rich))
            elif not offline and menus.confirm("是否显式使用 yt-dlp cookies-from-browser？", default_no=True, use_rich=use_rich):
                menus.print_warn(
                    "cookies-from-browser 只用于你自己浏览器已可访问的页面信息，不用于绕过权限或下载受限内容。",
                    use_rich=use_rich,
                )
                cookies_browser = menus.prompt_line("browser", default="chrome", use_rich=use_rich)
            rc = cmd_analyze_url(
                SimpleNamespace(
                    input=str(inp),
                    output=str(out),
                    review_csv=str(paths["review_csv"]),
                    review_md=str(PROJECT_ROOT / "output" / "review" / "review_sheet.md"),
                    cookie_file=cookie_file,
                    cookies_from_browser=cookies_browser,
                    offline="true" if offline else "false",
                    no_review_export="false",
                )
            )
            menus.print_info(f"analyze-url rc={rc}", use_rich=use_rich)
            wiz.log_console_event(f"url_feedback analyze rc={rc}")
        elif choice == "2":
            analysis = _prompt_project_path("analysis JSONL", str(paths["analysis"].relative_to(PROJECT_ROOT)), use_rich=use_rich)
            csv_out = _prompt_project_path("审核 CSV 输出", str(paths["review_csv"].relative_to(PROJECT_ROOT)), use_rich=use_rich)
            md_out = _prompt_project_path("审核 Markdown 输出", "output/review/review_sheet.md", use_rich=use_rich)
            rc = cmd_export_review(
                SimpleNamespace(
                    analysis=str(analysis),
                    output_csv=str(csv_out),
                    output_md=str(md_out),
                    include_existing_manual="false",
                )
            )
            menus.print_info(f"export-review rc={rc}", use_rich=use_rich)
        elif choice == "3":
            filled = _prompt_project_path("已填写审核 CSV", str(paths["filled_csv"].relative_to(PROJECT_ROOT)), use_rich=use_rich)
            if not filled.exists():
                menus.print_warn(
                    "请先打开 output/review/review_sheet.csv，填写 manual_status、manual_passed、"
                    "manual_reject_reasons、manual_notes 后再导入。",
                    use_rich=use_rich,
                )
                continue
            analysis = _prompt_project_path("analysis JSONL", str(paths["analysis"].relative_to(PROJECT_ROOT)), use_rich=use_rich)
            out = _prompt_project_path("manual reviewed JSONL 输出", str(paths["manual"].relative_to(PROJECT_ROOT)), use_rich=use_rich)
            rc = cmd_import_review(SimpleNamespace(analysis=str(analysis), review_csv=str(filled), output=str(out)))
            menus.print_info(f"import-review rc={rc}", use_rich=use_rich)
        elif choice == "4":
            manual = _prompt_project_path("manual reviewed JSONL", str(paths["manual"].relative_to(PROJECT_ROOT)), use_rich=use_rich)
            if not manual.exists():
                menus.print_warn("还没有 manual_reviewed.jsonl，请先导入人工审核结果。", use_rich=use_rich)
                continue
            stats = review_feedback_analyzer.analyze_feedback_records(list(read_jsonl(manual)))
            s = stats.get("summary") or {}
            rows = [
                ("总审核数", str(s.get("total_reviewed", 0))),
                ("通过", str(s.get("passed", 0))),
                ("不通过", str(s.get("rejected", 0))),
                ("通过率", f"{float(s.get('pass_rate') or 0) * 100:.1f}%"),
                ("sample_size_too_small", str(bool(s.get("sample_size_too_small")))),
            ]
            menus.show_table(["指标", "值"], rows, title="人工审核通过率", use_rich=use_rich)
        elif choice == "5":
            manual = _prompt_project_path("manual reviewed JSONL", str(paths["manual"].relative_to(PROJECT_ROOT)), use_rich=use_rich)
            rc = cmd_analyze_feedback(
                SimpleNamespace(input=str(manual), output_md=str(paths["feedback_md"]), output_json=str(paths["feedback_json"]))
            )
            if rc == 0:
                rc2 = cmd_strategy_from_feedback(
                    SimpleNamespace(
                        feedback_json=str(paths["feedback_json"]),
                        reviewed_jsonl=str(manual),
                        output_md=str(paths["rule_md"]),
                        output_yaml=str(paths["rule_yaml"]),
                    )
                )
                menus.print_info(f"analyze-feedback rc={rc}; strategy-from-feedback rc={rc2}", use_rich=use_rich)
            else:
                menus.print_err(f"analyze-feedback rc={rc}", use_rich=use_rich)
        elif choice == "6":
            manual = _prompt_project_path("manual reviewed JSONL", str(paths["manual"].relative_to(PROJECT_ROOT)), use_rich=use_rich)
            stats = _prompt_project_path("feedback stats JSON", str(paths["feedback_json"].relative_to(PROJECT_ROOT)), use_rich=use_rich)
            use_llm = menus.confirm("确认调用 LLM 做反馈分析？", default_no=True, use_rich=use_rich)
            rc = cmd_llm_analyze_feedback(
                SimpleNamespace(
                    input=str(manual),
                    stats=str(stats),
                    output_md=str(paths["llm_md"]),
                    output_yaml=str(paths["llm_yaml"]),
                    use_llm="true" if use_llm else "false",
                )
            )
            menus.print_info(f"llm-analyze-feedback rc={rc}", use_rich=use_rich)
        elif choice == "7":
            _preview_text_file(paths["rule_md"], title="规则策略 Markdown", use_rich=use_rich)
            _preview_text_file(paths["rule_yaml"], title="规则策略 YAML", use_rich=use_rich)
            _preview_text_file(paths["llm_md"], title="LLM 策略 Markdown", use_rich=use_rich)
            _preview_text_file(paths["llm_yaml"], title="LLM 策略 YAML", use_rich=use_rich)
        else:
            menus.print_warn("无效选项。", use_rich=use_rich)


def run_open_dirs(*, use_rich: bool) -> None:
    menus.print_panel(
        "打开目录",
        "1 output/\n2 data/\n3 config/\n4 docs/\n5 logs/\n6 自定义相对路径",
        use_rich=use_rich,
    )
    c = menus.prompt_line("选择", default="1", use_rich=use_rich)
    mapping = {
        "1": PROJECT_ROOT / "output",
        "2": PROJECT_ROOT / "data",
        "3": PROJECT_ROOT / "config",
        "4": PROJECT_ROOT / "docs",
        "5": PROJECT_ROOT / "logs",
    }
    path = mapping.get(c)
    if path is None:
        rel = menus.prompt_line("相对路径", default="output", use_rich=use_rich)
        path = (PROJECT_ROOT / rel).resolve()
    ok, msg = open_native_path(path)
    menus.print_info(msg, use_rich=use_rich)
    if not ok:
        menus.print_warn("若无法打开，请手动在文件管理器中粘贴路径。", use_rich=use_rich)


def doc_paths() -> list[Path]:
    return [
        PROJECT_ROOT / "docs" / "console_guide.md",
        PROJECT_ROOT / "docs" / "workflow.md",
        PROJECT_ROOT / "docs" / "filtering_rules.md",
        PROJECT_ROOT / "docs" / "llm_layer.md",
        PROJECT_ROOT / "docs" / "manual_review_guide.md",
        PROJECT_ROOT / "docs" / "url_analysis_module.md",
        PROJECT_ROOT / "docs" / "cookie_usage_guide.md",
        PROJECT_ROOT / "docs" / "review_feedback_loop.md",
        PROJECT_ROOT / "README.md",
    ]


def run_help(*, use_rich: bool) -> None:
    lines = [str(p) for p in doc_paths()]
    menus.print_panel("文档路径", "\n".join(lines), use_rich=use_rich)


def run_config_editor(*, use_rich: bool) -> None:
    known = console_config_editor.known_editable_configs()
    body = "\n".join([f"{i}. {label}" for i, (label, _) in enumerate(known, start=1)])
    menus.print_panel("YAML 配置编辑器", body + "\n0. 返回", use_rich=use_rich)
    choice = menus.prompt_line("选择", default="0", use_rich=use_rich)
    if choice == "0":
        return
    try:
        idx = int(choice) - 1
    except ValueError:
        menus.print_warn("无效。", use_rich=use_rich)
        return
    if idx < 0 or idx >= len(known):
        menus.print_warn("无效。", use_rich=use_rich)
        return
    _label, path = known[idx]

    def _p(msg: str) -> None:
        menus.print_info(msg, use_rich=use_rich)

    ok = console_config_editor.edit_yaml_file_interactive(path, _p)
    wiz.log_console_event(f"config_editor {path.name} ok={ok}")
