from __future__ import annotations

from typing import Callable, Iterable, Sequence

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False


def _plain_print(text: str) -> None:
    print(text, flush=True)


def print_info(msg: str, *, use_rich: bool, style: str = "cyan") -> None:
    if use_rich and _HAS_RICH:
        Console().print(f"[{style}]{msg}[/]")
    else:
        _plain_print(msg)


def print_warn(msg: str, *, use_rich: bool) -> None:
    if use_rich and _HAS_RICH:
        Console().print(f"[yellow]{msg}[/]")
    else:
        _plain_print(f"[WARN] {msg}")


def print_err(msg: str, *, use_rich: bool) -> None:
    if use_rich and _HAS_RICH:
        Console().print(f"[red]{msg}[/]")
    else:
        _plain_print(f"[ERROR] {msg}")


def print_panel(title: str, body: str, *, use_rich: bool) -> None:
    if use_rich and _HAS_RICH:
        Console().print(Panel(body.strip(), title=title, expand=False))
    else:
        _plain_print(f"=== {title} ===\n{body.strip()}\n")


def prompt_line(prompt: str, *, default: str | None = None, use_rich: bool) -> str:
    suffix = f" [{default}]" if default is not None else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    if not raw and default is not None:
        return default
    return raw


def prompt_int(
    prompt: str,
    *,
    default: int | None = None,
    min_v: int | None = None,
    max_v: int | None = None,
    use_rich: bool,
) -> int | None:
    while True:
        s = prompt_line(prompt, default=str(default) if default is not None else None, use_rich=use_rich)
        if not s and default is not None:
            return default
        try:
            v = int(s)
        except ValueError:
            print_warn("请输入整数。", use_rich=use_rich)
            continue
        if min_v is not None and v < min_v:
            print_warn(f"需 ≥ {min_v}。", use_rich=use_rich)
            continue
        if max_v is not None and v > max_v:
            print_warn(f"需 ≤ {max_v}。", use_rich=use_rich)
            continue
        return v


def prompt_choice(
    prompt: str,
    choices: Sequence[str],
    *,
    default: str | None = None,
    use_rich: bool,
) -> str | None:
    joined = "/".join(choices)
    while True:
        s = prompt_line(f"{prompt} ({joined})", default=default, use_rich=use_rich).lower()
        if not s and default is not None:
            return default
        if s in tuple(c.lower() for c in choices):
            return s
        print_warn(f"请输入 {joined} 之一。", use_rich=use_rich)


def confirm(msg: str, *, default_no: bool = False, use_rich: bool) -> bool:
    suff = "[y/N]" if default_no else "[Y/n]"
    s = prompt_line(f"{msg} {suff}", default="n" if default_no else "y", use_rich=use_rich).lower()
    if not s:
        return not default_no
    return s in ("y", "yes", "是", "确认", "ok", "1", "true")


def show_main_menu(*, use_rich: bool) -> None:
    lines = [
        "0. 退出",
        "1. 环境检查",
        "2. API 密钥向导",
        "3. 检索任务向导（生成 output/search_plan.yaml）",
        "4. LLM 检索计划（自然语言 → search_plan）",
        "5. 一键流水线（测试/生产）",
        "6. 分步运行（逐步确认路径）",
        "7. 查看规则/LLM 过滤结果",
        "8. 拒收统计（规则 + LLM）",
        "9. 策略优化（strategy-optimize）",
        "10. 打开常用目录（本机文件管理器）",
        "11. 帮助（文档路径）",
    ]
    body = "\n".join(lines)
    print_panel("主菜单 — YouTube URL 控制台", body, use_rich=use_rich)


def show_table(headers: Iterable[str], rows: Iterable[Sequence[str]], *, title: str, use_rich: bool) -> None:
    hs = list(headers)
    rs = list(rows)
    if use_rich and _HAS_RICH:
        t = Table(title=title, show_lines=False)
        for h in hs:
            t.add_column(h)
        for r in rs:
            t.add_row(*[str(x) for x in r])
        Console().print(t)
    else:
        _plain_print(f"=== {title} ===")
        _plain_print("\t".join(hs))
        for r in rs:
            _plain_print("\t".join(str(x) for x in r))


def rich_enabled() -> bool:
    return _HAS_RICH


def make_use_rich_flag() -> bool:
    return _HAS_RICH


def loop_invalid(
    prompt: str,
    *,
    parser: Callable[[str], tuple[bool, str | None]],
    use_rich: bool,
) -> str:
    while True:
        s = input(f"{prompt}: ").strip()
        ok, err = parser(s)
        if ok:
            return s
        if err:
            print_warn(err, use_rich=use_rich)
