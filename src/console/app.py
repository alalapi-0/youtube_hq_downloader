from __future__ import annotations

from pathlib import Path
from typing import List

import yaml

from ..core.config import APP_CONFIG_PATH, load_app_config, product_status
from ..core.paths import latest_task_dir
from ..core.pipeline import import_feedback_for_task, run_new_task
from ..core.task import PipelineOptions
from ..utils import clean_text
from ..youtube_collect import ytdlp_available


def _print(text: str = "") -> None:
    print(text, flush=True)


def _prompt(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    return raw or default


def show_header(current_task: Path | None = None) -> None:
    status = product_status()
    youtube = status.get("youtube") or {}
    latest = current_task or latest_task_dir()
    last_result = str((latest / "review_sheet.csv")) if latest and (latest / "review_sheet.csv").exists() else "无"
    if youtube.get("cookies_enabled") and youtube.get("cookie_file"):
        cookie_status = "cookies.txt"
    elif youtube.get("cookies_enabled") and youtube.get("cookies_from_browser"):
        cookie_status = f"浏览器 {youtube.get('cookies_from_browser')}"
    else:
        cookie_status = "关闭"
    _print("=" * 44)
    _print("Ad URL Scout")
    _print("YouTube 搜索结果页 URL 采集与 4K 筛选工具")
    _print("=" * 44)
    _print("")
    _print("当前状态：")
    _print(f"- yt-dlp: {'可用' if ytdlp_available() else '不可用'}")
    _print("- API Key: 不需要")
    _print(f"- Cookie: {cookie_status}")
    _print(f"- 每个搜索页默认读取: {(status.get('youtube') or {}).get('max_entries_per_search_page', 80)} 条")
    _print(f"- 当前任务: {latest.name if latest else '无'}")
    _print(f"- 上次结果: {last_result}")
    _print("")


def show_main_menu() -> None:
    _print("主菜单：")
    _print("1. 从 YouTube 搜索结果页采集 URL")
    _print("2. 查看上次任务结果")
    _print("3. 导入人工审核反馈")
    _print("4. 设置 Cookie（可选，用于 YouTube 验证）")
    _print("5. 高级 CLI 用法")
    _print("0. 退出")


def _read_search_urls() -> List[str]:
    _print("请把 YouTube 搜索结果页 URL 粘贴进来，每行一个。")
    _print("操作方式：你在 YouTube 手动搜索并设置过滤器后，复制浏览器地址栏里的 results?search_query=... 链接。")
    _print("输入完成后单独输入 END。")
    urls: List[str] = []
    while True:
        line = input("> ").strip()
        if line.upper() == "END":
            break
        if line:
            urls.append(clean_text(line))
    return urls


def start_new_task() -> Path | None:
    if not ytdlp_available():
        _print("未检测到 yt-dlp。请先运行：")
        _print("python3 -m pip install -r requirements.txt")
        return None

    urls = _read_search_urls()
    if not urls:
        _print("没有输入搜索结果页 URL，已取消。")
        return None
    cfg = load_app_config()
    default_entries = str((cfg.get("youtube") or {}).get("max_entries_per_search_page") or 80)
    raw = _prompt("每个搜索结果页最多读取多少条视频", default_entries)
    max_entries = int(raw) if raw.isdigit() else int(default_entries)
    note = _prompt("本轮备注，可留空", "")

    _print("")
    _print("开始采集：读取搜索结果页、批量获取元数据、探测 2160p 格式，并做本地过滤。")
    _print("过程不下载视频文件。YouTube 搜索页较慢时请稍等。")
    result = run_new_task(
        note,
        PipelineOptions(search_page_urls=urls, max_entries_per_search_page=max_entries),
    )

    _print("")
    _print("任务完成：")
    _print(f"采集到视频 URL：{result.summary.get('collected_url_count', 0)}")
    _print(f"元数据读取成功：{result.summary.get('metadata_success_count', 0)}")
    _print(f"硬性条件丢弃：{result.summary.get('hard_constraint_rejected_count', 0)}")
    _print(f"本地查重保留：{result.summary.get('final_count', 0)}")
    _print(f"重复/无效 URL：{result.summary.get('duplicate_count', 0)}")
    _print("")
    _print("请打开：")
    _print(result.summary["review_sheet_csv"])
    for warning in result.warnings[:10]:
        _print(f"[提示] {warning}")
    if len(result.warnings) > 10:
        _print(f"[提示] 还有 {len(result.warnings) - 10} 条提醒，详见 run_summary.md")
    for error in result.errors:
        _print(f"[错误] {error}")
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
        _print("暂无任务，请先采集一次 URL。")
        return
    default_csv = str(task / "review_sheet.csv")
    review_csv = Path(_prompt("请选择已填写的 review_sheet.csv", default_csv)).expanduser()
    if not review_csv.exists():
        _print("未找到审核表。请先填写 manual_status、manual_reject_reasons、manual_notes 后再导入。")
        return
    result = import_feedback_for_task(task, review_csv)
    _print("反馈导入完成。")
    _print(f"反馈分析：{result['feedback_md']}")
    _print(f"下一轮搜索建议：{result['next_search_plan']}")


def configure_cookies() -> None:
    cfg = load_app_config()
    youtube = cfg.setdefault("youtube", {})
    _print("Cookie 是可选功能，只用于让 yt-dlp 读取你浏览器中已经可访问的公开视频信息。")
    _print("不会下载视频，也不会把 Cookie 内容写入日志。")
    _print("1. 关闭 Cookie")
    _print("2. 使用 Chrome cookies-from-browser")
    _print("3. 使用手动导出的 cookies.txt")
    _print("0. 返回")
    choice = _prompt("选择", "0")
    if choice == "0":
        return
    if choice == "1":
        youtube["cookies_enabled"] = False
        youtube["cookie_file"] = ""
        youtube["cookies_from_browser"] = ""
    elif choice == "2":
        youtube["cookies_enabled"] = True
        youtube["cookie_file"] = ""
        youtube["cookies_from_browser"] = "chrome"
    elif choice == "3":
        path = _prompt("cookies.txt 路径", "")
        if not path:
            _print("路径为空，已取消。")
            return
        youtube["cookies_enabled"] = True
        youtube["cookie_file"] = path
        youtube["cookies_from_browser"] = ""
    else:
        _print("无效选项。")
        return
    APP_CONFIG_PATH.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    _print("Cookie 设置已更新。")


def advanced_menu() -> None:
    _print("高级 CLI：")
    _print('python3 -m src.main collect --search-url "https://www.youtube.com/results?search_query=..." --max-entries 80')
    _print("python3 -m src.main collect --search-url-file examples/search_pages.example.txt")
    _print("详细说明见 docs/advanced_cli.md")


def main() -> int:
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
            configure_cookies()
        elif choice == "5":
            advanced_menu()
        else:
            _print("无效选项，请重试。")
