from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from . import console_menu as menus
from . import console_runner as runner
from . import console_wizard as wiz
from .utils import PROJECT_ROOT


@dataclass
class ConsoleSession:
    """控制台会话偏好（仅内存，不落盘敏感信息）。"""

    llm_enabled: bool = False
    last_search_plan: Path | None = None
    last_rule_filtered: Path | None = None
    last_llm_filtered: Path | None = None
    notes: list[str] = field(default_factory=list)


def _bootstrap_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    _ = argv  # 预留：将来支持一次性子命令
    _bootstrap_env()
    use_rich = menus.make_use_rich_flag()
    if not menus.rich_enabled():
        print("[INFO] 未安装 rich，使用纯文本菜单。可执行: pip install rich", flush=True)

    session = ConsoleSession()
    wiz.log_console_event("console startup")

    while True:
        menus.show_main_menu(use_rich=use_rich)
        choice = menus.prompt_line("请选择 0-12", default="0", use_rich=use_rich).strip().lower()

        try:
            if choice in ("0", "q", "quit", "exit"):
                menus.print_info("再见。", use_rich=use_rich)
                wiz.log_console_event("console exit")
                return 0
            if choice == "1":
                runner.run_env_check(use_rich=use_rich)
            elif choice == "2":
                runner.run_api_key_wizard(use_rich=use_rich)
            elif choice == "3":
                p = runner.run_search_task_wizard(use_rich=use_rich)
                if p:
                    session.last_search_plan = p
            elif choice == "4":
                runner.run_llm_plan_flow(session, use_rich=use_rich)
            elif choice == "5":
                runner.run_full_pipeline(session, use_rich=use_rich)
            elif choice == "6":
                runner.run_step_by_step(session, use_rich=use_rich)
            elif choice == "7":
                runner.run_view_filtered(use_rich=use_rich)
            elif choice == "8":
                runner.run_rejected_stats(use_rich=use_rich)
            elif choice == "9":
                runner.run_strategy_flow(session, use_rich=use_rich)
            elif choice == "10":
                runner.run_open_dirs(use_rich=use_rich)
            elif choice == "11":
                runner.run_help(use_rich=use_rich)
            elif choice == "12":
                runner.run_url_feedback_loop(session, use_rich=use_rich)
            else:
                menus.print_warn("无效选项，请重试。", use_rich=use_rich)
        except KeyboardInterrupt:
            menus.print_warn("\n已取消当前操作（Ctrl+C）。返回主菜单。", use_rich=use_rich)
            wiz.log_console_event("keyboard interrupt -> main menu")
            continue
        except EOFError:
            menus.print_info("EOF，退出。", use_rich=use_rich)
            return 0
        except Exception as exc:
            menus.print_err(f"未捕获异常：{exc}", use_rich=use_rich)
            wiz.log_console_event(f"console error {type(exc).__name__}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
