from __future__ import annotations

import getpass
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

import yaml

from ..core.config import APP_CONFIG_PATH, load_app_config, openrouter_api_key, product_status, youtube_api_key
from ..core.paths import latest_task_dir, task_paths
from ..core.pipeline import import_feedback_for_task, run_new_task
from ..core.task import PipelineOptions
from ..env_loader import load_dotenv
from ..llm.planner import generate_search_plan
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
    _print(f"- YouTube API: {'已配置' if status['youtube_api_configured'] else '未配置，可选'}")
    _print(f"- yt-dlp: {'可用' if status['ytdlp_available'] else '不可用，可选'}")
    cookie = "关闭" if status.get("cookie_mode") == "off" else f"{status.get('cookie_mode')} {status.get('cookie_browser') or ''}".strip()
    _print(f"- Cookie: {cookie}")
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
    _print("例如：我要找高端奢侈品官方广告，优先 Dior、Prada、Chanel、Gucci，要求 4K，排除 AI、review、unboxing、vlog，时长 20 到 180 秒。")
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


def _plan_summary(plan: Dict[str, Any]) -> str:
    tasks = [t for t in (plan.get("tasks") or []) if isinstance(t, dict)]
    brands: List[str] = []
    keywords: List[str] = []
    for task in tasks:
        brands.extend(str(x) for x in (task.get("brands") or []) if str(x).strip())
        keywords.extend(str(x) for x in (task.get("keywords") or []) if str(x).strip())
    neg = ((plan.get("positive_negative_keywords") or {}).get("suggested_negative_keywords") or [])
    dur = plan.get("duration") or {}
    res = plan.get("resolution") or {}
    cap = int((plan.get("global_rules") or {}).get("max_results_per_keyword") or 10)
    estimate = max(1, len(keywords)) * max(1, cap) * max(1, len(brands) or 1)
    return "\n".join(
        [
            "AI 已生成搜索计划：",
            "",
            f"目标类别：{', '.join(str(t.get('category') or '') for t in tasks) or 'campaigns'}",
            f"品牌：{', '.join(dict.fromkeys(brands)) or '未限定'}",
            f"关键词数量：{len(dict.fromkeys(keywords))}",
            f"排除内容：{', '.join(str(x) for x in neg[:12]) or '使用默认排除词'}",
            f"时长范围：{dur.get('min_seconds', '')}-{dur.get('max_seconds', '')} 秒",
            f"清晰度：{'优先 2160p / 4K' if res.get('require_4k') else '不强制 4K'}",
            f"预计搜索候选数：约 {estimate} 条",
        ]
    )


def _edit_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    tasks = [t for t in (plan.get("tasks") or []) if isinstance(t, dict)]
    if not tasks:
        return plan
    while True:
        _print("")
        _print("请选择：")
        _print("1. 继续执行")
        _print("2. 编辑关键词")
        _print("3. 编辑品牌")
        _print("4. 编辑过滤规则")
        _print("0. 取消")
        choice = _prompt("选择", "1")
        if choice == "1":
            return plan
        if choice == "0":
            return {}
        if choice == "2":
            raw = _prompt("关键词，用逗号分隔", ", ".join(tasks[0].get("keywords") or []))
            tasks[0]["keywords"] = [x.strip() for x in raw.split(",") if x.strip()]
        elif choice == "3":
            raw = _prompt("品牌，用逗号分隔", ", ".join(tasks[0].get("brands") or []))
            tasks[0]["brands"] = [x.strip() for x in raw.split(",") if x.strip()]
        elif choice == "4":
            min_s = _prompt("最短秒数", str((plan.get("duration") or {}).get("min_seconds") or 20))
            max_s = _prompt("最长秒数", str((plan.get("duration") or {}).get("max_seconds") or 180))
            require_4k = _confirm("是否要求/优先 4K？", default_yes=True)
            plan.setdefault("duration", {})["min_seconds"] = int(min_s) if min_s.isdigit() else 20
            plan.setdefault("duration", {})["max_seconds"] = int(max_s) if max_s.isdigit() else 180
            plan.setdefault("resolution", {})["require_4k"] = require_4k
            plan.setdefault("resolution", {})["min_height"] = 2160 if require_4k else None


def start_new_task() -> Path | None:
    user_request = _read_user_request()
    if not user_request:
        _print("需求为空，已取消。")
        return None
    if not openrouter_api_key():
        _print("")
        _print("未检测到 OPENROUTER_API_KEY。")
        _print("AI 搜索计划和语义筛选需要 OpenRouter API Key。")
        _print("你可以：")
        _print("1. 现在配置")
        _print("2. 使用规则模式继续，效果较弱")
        _print("0. 返回")
        c = _prompt("选择", "1")
        if c == "1":
            configure_keys(openrouter_only=True)
        elif c == "0":
            return None

    use_ai = bool(openrouter_api_key())
    plan, warnings = generate_search_plan(user_request, use_ai=use_ai)
    for warning in warnings:
        _print(f"[提示] {warning}")
    _print("")
    _print(_plan_summary(plan))
    plan = _edit_plan(plan)
    if not plan:
        _print("已取消任务。")
        return None

    if not youtube_api_key():
        _print("")
        _print("未检测到 YOUTUBE_API_KEY。")
        _print("系统会改用 yt-dlp 搜索降级模式，不下载视频。")
        _print("如需读取你本机 Chrome 已可访问的页面信息，可在设置中启用 Chrome Cookie。")
        if not _confirm("仍然继续创建任务？", default_yes=True):
            return None
    result = run_new_task(
        user_request,
        PipelineOptions(ai_enabled=use_ai, search_plan_override=plan),
    )
    _print("")
    _print("任务完成：")
    _print(f"候选 URL：{result.summary['total_candidates']}")
    _print(f"元数据读取成功：{result.summary['metadata_success_count']}")
    _print(f"规则过滤通过：{result.summary['rule_pass_count']}")
    _print(f"AI 复筛通过：{result.summary['llm_pass_count']}")
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
        plan = yaml.safe_load(Path(result["next_search_plan"]).read_text(encoding="utf-8"))
        run_new_task(req, PipelineOptions(ai_enabled=bool(openrouter_api_key()), search_plan_override=plan if isinstance(plan, dict) else None))


def analyze_feedback_only() -> None:
    import_feedback()


def configure_keys(*, openrouter_only: bool = False) -> None:
    while True:
        _print("")
        _print("设置：")
        _print("1. 设置 OPENROUTER_API_KEY")
        if not openrouter_only:
            _print("2. 设置 YOUTUBE_API_KEY（可选）")
            _print("3. 修改 OpenRouter 模型")
            _print("4. 启用 Chrome Cookie 辅助 yt-dlp（高级，可选）")
            _print("5. 关闭 Cookie")
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
            secret = getpass.getpass("请输入 YOUTUBE_API_KEY（可选，不回显）: ").strip()
            if secret:
                _set_env_key("YOUTUBE_API_KEY", secret)
                _print("已写入 YOUTUBE_API_KEY。")
        elif c == "3" and not openrouter_only:
            cfg = load_app_config()
            model = _prompt("OpenRouter 模型", str((cfg.get("llm") or {}).get("model") or "google/gemini-2.5-flash"))
            cfg.setdefault("llm", {})["model"] = model
            APP_CONFIG_PATH.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
            _print("模型已更新。")
        elif c == "4" and not openrouter_only:
            _print("Cookie 只会交给 yt-dlp 读取你本机浏览器已可访问的页面信息；不会下载视频，不会绕过权限。")
            if _confirm("确认启用 Chrome Cookie？", default_yes=False):
                cfg = load_app_config()
                cfg.setdefault("advanced", {})["use_cookie"] = True
                cfg.setdefault("advanced", {})["cookies_from_browser"] = "chrome"
                cfg.setdefault("advanced", {})["cookie_file"] = ""
                APP_CONFIG_PATH.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
                _print("已启用 Chrome Cookie 辅助 yt-dlp。")
        elif c == "5" and not openrouter_only:
            cfg = load_app_config()
            cfg.setdefault("advanced", {})["use_cookie"] = False
            cfg.setdefault("advanced", {})["cookies_from_browser"] = ""
            cfg.setdefault("advanced", {})["cookie_file"] = ""
            APP_CONFIG_PATH.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
            _print("已关闭 Cookie。")


def advanced_menu() -> None:
    _print("高级 CLI：")
    _print("- python3 -m src.main plan")
    _print("- python3 -m src.main search")
    _print("- python3 -m src.main analyze-url")
    _print("- python3 -m src.main filter")
    _print("- python3 -m src.main export")
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
