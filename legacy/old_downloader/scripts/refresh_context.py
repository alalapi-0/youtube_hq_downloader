#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refresh_context.py — 环境初始化与 Token 管理脚本

【这个脚本做什么？】
  检测本机的工具安装情况，并将结果缓存到 state/env_state.json，
  避免每次下载都重新检测（提高启动速度）。

  同时提供 YouTube Token 的管理功能（设置、查看、清除）。
  Token 是访问 YouTube 高画质内容（4K 等）的「身份证」。

【会检测哪些工具？】
  - yt-dlp: 核心下载工具（必需，找不到会自动安装）
  - ffmpeg: 视频合并工具（必需，adaptive 模式下用于合并视频流和音频流）
  - ffprobe: 视频信息检测工具（与 ffmpeg 一起安装）
  - JavaScript 运行时（node/deno/bun）: 处理 YouTube 反爬验证时需要
  - 浏览器（chrome/brave/edge 等）: 可提供 cookies，帮助通过 YouTube 验证

【Token 说明】
  visitor_data 和 po_token 是 YouTube 用于确认用户真实性的「身份令牌」。
  配置了这两个 Token 后，yt-dlp 能稳定地看到和下载 4K 画质。
  不配置 Token 也能尝试下载，但可能只看到 360p/720p 等低画质格式。

  Token 获取方法：请参考 README.md 的「Token 配置」部分。

【使用方式】
  检测并更新环境缓存：  python3 scripts/refresh_context.py
  只查看当前状态：      python3 scripts/refresh_context.py --show
  设置 Token：          python3 scripts/refresh_context.py --set-visitor-data "xxx" --set-po-token "yyy"
  从环境变量导入 Token：python3 scripts/refresh_context.py --import-env-tokens
  清除所有 Token：      python3 scripts/refresh_context.py --clear-tokens
  查看 Token 设置模板： python3 scripts/refresh_context.py --show-token-template
"""

from __future__ import annotations

import argparse
import os
from typing import Any, Dict

from common import (
    default_env_state,
    default_tokens_data,
    detect_all_browsers,
    detect_cookies_browser,
    detect_js_runtime,
    detect_ytdlp_source,
    effective_tokens_data,
    ensure_ffmpeg_and_ffprobe,
    ensure_standard_state_files,
    ensure_ytdlp_installed,
    get_ytdlp_cmd_display,
    get_ytdlp_version,
    load_json_dict,
    log_event,
    now_ts,
    project_paths,
    save_json,
    token_runtime_summary,
    which,
)

# 项目路径配置
PATHS = project_paths(__file__)
PROJECT_ROOT = PATHS["project_root"]


# ===========================================================================
# 环境检测
# ===========================================================================

def collect_env_state(auto_install: bool = True) -> Dict[str, Any]:
    """
    检测本机的工具安装情况，返回包含所有检测结果的字典。
    
    检测内容包括：yt-dlp、ffmpeg、ffprobe、JavaScript 运行时、浏览器。
    结果将保存到 state/env_state.json，供其他脚本快速读取（无需重复检测）。
    
    参数：
        auto_install: 是否自动安装缺失的工具（True：自动安装；False：只检测不安装）
    返回：
        包含所有检测结果的字典
    """
    state = default_env_state()

    # 检测 yt-dlp（找不到时可自动安装）
    ytdlp_cmd = ensure_ytdlp_installed(auto_install=auto_install)
    # 检测 ffmpeg 和 ffprobe（找不到时可自动安装）
    ensure_ffmpeg_and_ffprobe(auto_install=auto_install)

    state["updated_at"] = now_ts()

    # 保存 yt-dlp 检测结果
    if ytdlp_cmd:
        state["ytdlp"] = {
            "cmd": ytdlp_cmd,
            "version": get_ytdlp_version(ytdlp_cmd),
            "source": detect_ytdlp_source(ytdlp_cmd),
            "ok": True,
        }
    else:
        state["ytdlp"] = {
            "cmd": [],
            "version": "",
            "source": "",
            "ok": False,
        }

    # 保存 ffmpeg/ffprobe 路径
    ffmpeg_path = which("ffmpeg") or ""
    ffprobe_path = which("ffprobe") or ""
    state["ffmpeg"] = {"path": ffmpeg_path, "ok": bool(ffmpeg_path)}
    state["ffprobe"] = {"path": ffprobe_path, "ok": bool(ffprobe_path)}

    # 检测 JavaScript 运行时（node/deno/bun）
    js_runtime = detect_js_runtime()
    state["js_runtime"] = {
        "name": js_runtime,
        "ok": js_runtime != "auto",  # "auto" 表示未检测到，让 yt-dlp 自行处理
    }

    # 检测已安装的浏览器
    detected_browsers = detect_all_browsers()
    cookies_browser = detect_cookies_browser() or ""
    state["browser"] = {
        "cookies_browser": cookies_browser,   # 首选浏览器（第一个检测到的）
        "detected": detected_browsers,         # 所有已检测到的浏览器
    }

    return state


def print_env_state(state: Dict[str, Any]) -> None:
    """打印环境检测结果摘要（人类可读格式）。"""
    print("=== 本机环境状态 ===")
    print(f"更新时间: {state.get('updated_at', 0)}")

    y = state.get("ytdlp", {})
    print(f"yt-dlp 可用: {'✓ 是' if y.get('ok') else '✗ 否（请运行此脚本安装）'}")
    if y.get("ok"):
        print(f"  版本: {y.get('version', '')}")
        print(f"  来源: {y.get('source', '')}")
        print(f"  命令: {' '.join(y.get('cmd', []))}")

    f1 = state.get("ffmpeg", {})
    f2 = state.get("ffprobe", {})
    print(f"ffmpeg 可用: {'✓ 是' if f1.get('ok') else '✗ 否（adaptive 模式必需）'}")
    print(f"ffprobe 可用: {'✓ 是' if f2.get('ok') else '✗ 否（分辨率验证功能需要）'}")

    js = state.get("js_runtime", {})
    print(f"JavaScript 运行时: {js.get('name', '')} {'✓' if js.get('ok') else '（未找到，yt-dlp 自动处理）'}")

    b = state.get("browser", {})
    cb = b.get("cookies_browser", "")
    print(f"首选浏览器: {cb if cb else '未检测到已安装的浏览器'}")
    if b.get("detected"):
        print(f"  已检测到: {', '.join(b.get('detected', []))}")


# ===========================================================================
# Token 管理
# ===========================================================================

def load_tokens_file() -> Dict[str, Any]:
    """读取 state/tokens.json（YouTube Token 文件）。"""
    return load_json_dict(PATHS["tokens_file"], default_tokens_data())


def save_tokens_file(tokens: Dict[str, Any]) -> None:
    """将 Token 数据写入 state/tokens.json。"""
    save_json(PATHS["tokens_file"], tokens)


def print_tokens_file_view(tokens: Dict[str, Any]) -> None:
    """打印 tokens.json 中保存的 Token 信息。"""
    print("=== tokens.json 内容 ===")
    print(f"更新时间: {tokens.get('updated_at', 0)}")
    yt = tokens.get("youtube", {})
    if not isinstance(yt, dict):
        yt = {}
    print(f"visitor_data 已设置: {'是' if yt.get('visitor_data') else '否（未配置，可能影响 4K 下载）'}")
    print(f"po_token 已设置: {'是' if yt.get('po_token') else '否（未配置，可能影响 4K 下载）'}")
    print(f"token_client: {yt.get('token_client', 'web')}")
    print(f"来源: {yt.get('source', 'manual')}")
    print(f"预计有效期: {yt.get('expires_hint_seconds', 3600)} 秒")


def print_effective_tokens_view(tokens_file_data: Dict[str, Any]) -> None:
    """打印当前实际生效的 Token 状态（文件 Token + 环境变量 Token 合并后的结果）。"""
    effective = effective_tokens_data(tokens_file_data)
    summary = token_runtime_summary(effective)
    print("=== 当前生效的 Token ===")
    print(f"visitor_data 已设置: {'是' if summary['visitor_data_set'] else '否'}")
    print(f"po_token 已设置: {'是' if summary['po_token_set'] else '否'}")
    print(f"token_client: {summary['token_client']}")
    print(f"Token 来源: {summary['token_source']}")
    if not summary['visitor_data_set'] or not summary['po_token_set']:
        print("")
        print("  ⚠️ 提示：未配置 Token 可能导致只能看到 360p/720p 等低画质格式。")
        print("  请参考 README.md 的「Token 配置」部分获取并设置 Token。")


def update_tokens_file(
    visitor_data: str | None = None,
    po_token: str | None = None,
    token_client: str | None = None,
    source: str | None = None,
    expires_hint_seconds: int | None = None,
) -> Dict[str, Any]:
    """
    更新 tokens.json 中的一个或多个字段。
    
    只有传入非 None 的参数才会被更新，其余字段保持不变。
    
    参数：
        visitor_data: YouTube 访客标识
        po_token: YouTube 播放 Token
        token_client: Token 对应的客户端类型（通常为 "web"）
        source: Token 来源说明（"manual" / "env" / "browser"）
        expires_hint_seconds: Token 预计有效期（秒）
    返回：
        更新后的完整 tokens 字典
    """
    tokens = load_tokens_file()
    youtube = tokens.get("youtube")
    if not isinstance(youtube, dict):
        youtube = default_tokens_data()["youtube"]
        tokens["youtube"] = youtube

    changed = False

    if visitor_data is not None:
        youtube["visitor_data"] = visitor_data.strip()
        changed = True

    if po_token is not None:
        youtube["po_token"] = po_token.strip()
        changed = True

    if token_client is not None:
        youtube["token_client"] = token_client.strip() or "web"
        changed = True

    if source is not None:
        youtube["source"] = source
        changed = True

    if expires_hint_seconds is not None:
        youtube["expires_hint_seconds"] = int(expires_hint_seconds)
        changed = True

    if changed:
        tokens["updated_at"] = now_ts()
        save_tokens_file(tokens)

    return tokens


def clear_tokens_file() -> Dict[str, Any]:
    """
    清除所有 Token（将 tokens.json 重置为空模板）。
    清除后需要重新配置 Token 才能访问 4K 画质。
    """
    tokens = default_tokens_data()
    tokens["updated_at"] = now_ts()
    save_tokens_file(tokens)
    return tokens


def import_env_tokens() -> Dict[str, Any]:
    """
    从当前 Shell 的环境变量中读取 Token 并写入 tokens.json。
    
    读取的环境变量：
      - YT_VISITOR_DATA: YouTube 访客标识
      - YT_PO_TOKEN: YouTube 播放 Token
      - YT_TOKEN_CLIENT: 客户端类型（默认 "web"）
    
    如何使用：
      先在终端设置环境变量：
        export YT_VISITOR_DATA='你的 visitor_data'
        export YT_PO_TOKEN='你的 po_token'
      然后运行：
        python3 scripts/refresh_context.py --import-env-tokens
    """
    visitor_data = os.getenv("YT_VISITOR_DATA", "")
    po_token = os.getenv("YT_PO_TOKEN", "")
    token_client = os.getenv("YT_TOKEN_CLIENT", "web")

    tokens = update_tokens_file(
        visitor_data=visitor_data,
        po_token=po_token,
        token_client=token_client,
        source="env",
    )
    log_event(
        PATHS["run_log_file"], "refresh_context", "info", "import_env_tokens",
        visitor_data_set=bool(visitor_data),
        po_token_set=bool(po_token),
        token_client=token_client,
    )
    return tokens


def maybe_show_token_template(show: bool) -> None:
    """
    打印 Shell 环境变量设置模板，方便用户快速复制后替换内容。
    
    打印效果：
      export YT_VISITOR_DATA='your_visitor_data_here'
      export YT_PO_TOKEN='your_po_token_here'
      export YT_TOKEN_CLIENT='web'
    """
    if not show:
        return
    print("# 将下面的命令复制到终端，替换引号里的内容后执行：")
    print("export YT_VISITOR_DATA='your_visitor_data_here'")
    print("export YT_PO_TOKEN='your_po_token_here'")
    print("export YT_TOKEN_CLIENT='web'")
    print("# 执行后再运行：python3 scripts/refresh_context.py --import-env-tokens")


# ===========================================================================
# 命令行参数解析
# ===========================================================================

def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(
            "检测本机工具环境并保存到 state/env_state.json，同时管理 YouTube Token。\n"
            "首次使用或工具更新后需要运行此脚本。"
        )
    )
    ap.add_argument(
        "--show",
        action="store_true",
        help="检测完后详细打印环境状态、Token 文件内容和当前生效的 Token"
    )
    ap.add_argument(
        "--no-auto-install",
        action="store_true",
        help="只检测，不自动安装缺失的 yt-dlp / ffmpeg"
    )
    ap.add_argument(
        "--tokens-only",
        action="store_true",
        help="只操作 Token，跳过环境工具检测（更快）"
    )
    ap.add_argument(
        "--import-env-tokens",
        action="store_true",
        help="从环境变量（YT_VISITOR_DATA / YT_PO_TOKEN / YT_TOKEN_CLIENT）导入 Token"
    )
    ap.add_argument(
        "--set-visitor-data",
        default=None,
        help="直接设置 visitor_data（示例：--set-visitor-data 'Cgt...'）"
    )
    ap.add_argument(
        "--set-po-token",
        default=None,
        help="直接设置 po_token（示例：--set-po-token 'MnT...'）"
    )
    ap.add_argument(
        "--set-token-client",
        default=None,
        help="设置 token_client，通常为 'web'（示例：--set-token-client 'web'）"
    )
    ap.add_argument(
        "--set-expires-hint-seconds",
        type=int,
        default=None,
        help="设置 Token 预计有效期（秒）"
    )
    ap.add_argument(
        "--clear-tokens",
        action="store_true",
        help="清除所有 Token，将 tokens.json 重置为空（清除后需重新配置才能访问 4K）"
    )
    ap.add_argument(
        "--show-token-template",
        action="store_true",
        help="打印环境变量设置模板（方便复制）"
    )
    return ap


# ===========================================================================
# 主函数
# ===========================================================================

def main() -> None:
    ap = build_arg_parser()
    args = ap.parse_args()

    # 确保所有状态文件和目录存在（首次运行时自动初始化）
    ensure_standard_state_files(PATHS, need_downloads_dir=False)

    # 打印 Token 设置模板（如果请求）
    maybe_show_token_template(args.show_token_template)

    auto_install = not args.no_auto_install

    # 读取现有环境状态
    env_state = load_json_dict(PATHS["env_state_file"], default_env_state())

    # 检测并更新环境状态（除非指定了 --tokens-only）
    if not args.tokens_only:
        print("正在检测本机工具环境（yt-dlp、ffmpeg、浏览器等）...")
        env_state = collect_env_state(auto_install=auto_install)
        save_json(PATHS["env_state_file"], env_state)
        log_event(
            PATHS["run_log_file"], "refresh_context", "info", "refresh_env_state",
            ytdlp_ok=env_state["ytdlp"]["ok"],
            ffmpeg_ok=env_state["ffmpeg"]["ok"],
            ffprobe_ok=env_state["ffprobe"]["ok"],
            js_runtime=env_state["js_runtime"]["name"],
            cookies_browser=env_state["browser"]["cookies_browser"],
        )
        print("环境检测完成，结果已保存到 state/env_state.json")

    # Token 管理操作
    tokens = load_tokens_file()

    if args.clear_tokens:
        tokens = clear_tokens_file()
        log_event(PATHS["run_log_file"], "refresh_context", "info", "clear_tokens")
        print("Token 已清除")

    if args.import_env_tokens:
        tokens = import_env_tokens()
        print("已从环境变量导入 Token")

    if (
        args.set_visitor_data is not None
        or args.set_po_token is not None
        or args.set_token_client is not None
        or args.set_expires_hint_seconds is not None
    ):
        tokens = update_tokens_file(
            visitor_data=args.set_visitor_data,
            po_token=args.set_po_token,
            token_client=args.set_token_client,
            source="manual",
            expires_hint_seconds=args.set_expires_hint_seconds,
        )
        log_event(
            PATHS["run_log_file"], "refresh_context", "info", "manual_set_tokens",
            visitor_data_set=args.set_visitor_data is not None,
            po_token_set=args.set_po_token is not None,
            token_client=args.set_token_client or "",
            expires_hint_seconds=args.set_expires_hint_seconds or "",
        )
        print("Token 已更新")

    # 打印检测结果摘要
    print_env_state(env_state)
    print()
    print_tokens_file_view(tokens)
    print()
    print_effective_tokens_view(tokens)


if __name__ == "__main__":
    main()
