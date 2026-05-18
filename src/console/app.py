from __future__ import annotations

import getpass
from pathlib import Path
from typing import List

import yaml

from ..core.config import APP_CONFIG_PATH, load_app_config, openrouter_api_key, product_status
from ..core.paths import latest_task_dir, task_paths
from ..core.pipeline import import_feedback_for_task, run_new_task
from ..core.task import PipelineOptions
from ..env_loader import load_dotenv
from ..utils import PROJECT_ROOT, clean_text


def _print(text: str = "") -> None:
    print(text, flush=True)


def _prompt(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    return raw or default


def _confirm(prompt: str, default_yes: bool = True) -> bool:
    default = "Y/n" if default_yes else "y/N"
    raw = _prompt(f"{prompt} ({default})", "y" if default_yes else "n").lower()
    return raw in ("y", "yes", "1", "true", "是", "确认")


def _ensure_env_file() -> Path:
    env = PROJECT_ROOT / ".env"
    if not env.exists():
        example = PROJECT_ROOT / ".env.example"
        env.write_text(example.read_text(encoding="utf-8") if example.exists() else "", encoding="utf-8")
    return env


def _set_env_key(key: str, value: str) -> None:
    env = _ensure_env_file()
    lines = env.read_text(encoding="utf-8").splitlines()
    out: List[str] = []
    seen = False
    for line in lines:
        if line.startswith(f"{key}="):
            out.append(f"{key}={value}")
            seen = True
        else:
            out.append(line)
    if not seen:
        out.append(f"{key}={value}")
    env.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    load_dotenv(env, override=True)


def show_header(current_task: Path | None = None) -> None:
    status = product_status()
    latest = current_task or latest_task_dir()
    last_result = str((latest / "review_sheet.csv")) if latest and (latest / "review_sheet.csv").exists() else "无"
    _print("=" * 40)
    _print("Ad URL Scout")
    _print("AI 增强广告视频 URL 寻源工具")
    _print("=" * 40)
    _print("")
    _print("当前状态：")
    _print(f"- OpenRouter: {'已配置' if status['openrouter_configured'] else '未配置'}")
    _print("- 搜索方式: OpenRouter Web Search")
    _print(f"- 当前任务: {latest.name if latest else '无'}")
    _print(f"- 上次结果: {last_result}")
    _print("")


def show_main_menu() -> None:
    _print("主菜单：")
    _print("1. 开始新的寻源任务")
    _print("2. 查看上次任务结果")
    _print("3. 导入人工审核反馈")
    _print("4. 分析反馈并生成下一轮搜索策略")
    _print("5. 设置 API Key 和运行参数")
    _print("6. 高级功能")
    _print("0. 退出")


def _read_user_request() -> str:
    _print("请用自然语言描述你要找什么视频。")
    _print("例如：我要找 Vimeo 上的高端奢侈品官方广告，要求 4K，60 秒以内，发布时间两年内，页面最好有 advertisement、campaign、Agency、Production Company、Director、DOP、Post/VFX 等广告制作信息，排除 AI、review、unboxing、vlog。")
    _print("输入完成后按 Enter；如果要多行输入，最后单独输入 END。")
    first = input("> ").rstrip()
    if first.strip().upper() != "END":
        lines = [first]
    else:
        lines = []
    if first.strip().upper() == "END":
        return ""
    while True:
        line = input()
        if line.strip().upper() == "END":
            break
        if not line.strip():
            break
        lines.append(line.rstrip())
    return clean_text("\n".join(lines)).strip()


def start_new_task() -> Path | None:
    user_request = _read_user_request()
    if not user_request:
        _print("需求为空，已取消。")
        return None
    if not openrouter_api_key():
        _print("")
        _print("未检测到 OPENROUTER_API_KEY。")
        _print("当前版本只通过 OpenRouter Web Search 搜索 URL，需要 OpenRouter API Key。")
        _print("你可以：")
        _print("1. 现在配置")
        _print("0. 返回")
        c = _prompt("选择", "1")
        if c == "1":
            configure_keys(openrouter_only=True)
        if c == "0" or not openrouter_api_key():
            return None

    default_count = str((load_app_config().get("web_search") or {}).get("target_url_count") or 40)
    target_raw = _prompt("希望本轮最多保留多少个去重 URL", default_count)
    target = int(target_raw) if target_raw.isdigit() else int(default_count)
    _print("")
    _print("即将通过 OpenRouter Web Search 只搜索 Vimeo 视频 URL，并做本地查重。")
    _print("硬性条件：Vimeo、4K/2160p/UHD、60 秒以内、两年内、广告/商业片特征。")
    result = run_new_task(
        user_request,
        PipelineOptions(ai_enabled=True, max_results_per_query=target),
    )
    _print("")
    _print("任务完成：")
    _print(f"AI 找到 URL：{result.summary['total_candidates']}")
    _print(f"硬性条件丢弃：{result.summary.get('hard_constraint_rejected_count', 0)}")
    _print(f"本地查重保留：{result.summary['final_count']}")
    _print(f"重复/无效 URL：{result.summary.get('duplicate_count', 0)}")
    _print(f"需要人工审核：{result.summary['final_count']}")
    _print("")
    _print("请打开：")
    _print(result.summary["review_sheet_csv"])
    return result.task_dir


def view_last_task() -> None:
    task = latest_task_dir()
    if not task:
        _print("暂无历史任务。")
        return
    summary = task / "run_summary.md"
    if summary.exists():
        _print(summary.read_text(encoding="utf-8"))
    else:
        _print(f"最近任务目录：{task}")


def import_feedback() -> None:
    task = latest_task_dir()
    if not task:
        _print("暂无任务，请先开始一次新的寻源任务。")
        return
    default_csv = str(task / "review_sheet.csv")
    review_csv = Path(_prompt("请选择已填写的 review_sheet.csv", default_csv)).expanduser()
    if not review_csv.exists():
        _print("未找到审核表。请先填写 manual_status、manual_reject_reasons、manual_notes 后再导入。")
        return
    result = import_feedback_for_task(task, review_csv, use_ai=bool(openrouter_api_key()))
    _print("反馈导入完成。")
    _print(f"反馈分析：{result['feedback_md']}")
    _print(f"下一轮搜索计划：{result['next_search_plan']}")
    for warning in result.get("warnings") or []:
        _print(f"[提示] {warning}")
    if _confirm("是否基于下一轮计划立即开始下一轮？", default_yes=False):
        req = (task / "user_request.txt").read_text(encoding="utf-8") if (task / "user_request.txt").exists() else "根据人工反馈继续优化搜索"
        plan_text = Path(result["next_search_plan"]).read_text(encoding="utf-8") if Path(result["next_search_plan"]).exists() else ""
        next_req = clean_text(req + "\n\n请结合以下人工反馈策略继续寻找新的 URL，避免重复上一轮结果：\n" + plan_text)
        run_new_task(next_req, PipelineOptions(ai_enabled=True))


def analyze_feedback_only() -> None:
    import_feedback()


def configure_keys(*, openrouter_only: bool = False) -> None:
    while True:
        _print("")
        _print("设置：")
        _print("1. 设置 OPENROUTER_API_KEY")
        if not openrouter_only:
            _print("2. 修改 OpenRouter 模型")
            _print("3. 修改默认 URL 数量")
        _print("0. 返回")
        c = _prompt("选择", "0")
        if c == "0":
            return
        if c == "1":
            secret = getpass.getpass("请输入 OPENROUTER_API_KEY（不回显）: ").strip()
            if secret:
                _set_env_key("OPENROUTER_API_KEY", secret)
                _print("已写入 OPENROUTER_API_KEY。")
        elif c == "2" and not openrouter_only:
            cfg = load_app_config()
            model = _prompt("OpenRouter 模型", str((cfg.get("llm") or {}).get("model") or "google/gemini-2.5-flash"))
            cfg.setdefault("llm", {})["model"] = model
            APP_CONFIG_PATH.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
            _print("模型已更新。")
        elif c == "3" and not openrouter_only:
            cfg = load_app_config()
            current = str((cfg.get("web_search") or {}).get("target_url_count") or 40)
            count = _prompt("默认最多保留 URL 数量", current)
            if count.isdigit():
                cfg.setdefault("web_search", {})["target_url_count"] = int(count)
            APP_CONFIG_PATH.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
            _print("默认 URL 数量已更新。")


def advanced_menu() -> None:
    _print("高级 CLI：")
    _print("- python3 -m src.main run-task")
    _print("")
    _print("详细说明见 docs/advanced_cli.md")


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    current_task: Path | None = None
    while True:
        show_header(current_task)
        show_main_menu()
        choice = _prompt("请选择", "0")
        if choice == "0":
            _print("再见。")
            return 0
        if choice == "1":
            current_task = start_new_task() or current_task
        elif choice == "2":
            view_last_task()
        elif choice == "3":
            import_feedback()
        elif choice == "4":
            analyze_feedback_only()
        elif choice == "5":
            configure_keys()
        elif choice == "6":
            advanced_menu()
        else:
            _print("无效选项，请重试。")
