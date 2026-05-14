#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
youtube.py — YouTube 平台适配器

支持的 URL 格式：
  - https://www.youtube.com/watch?v=xxxxx  （普通视频）
  - https://www.youtube.com/shorts/xxxxx   （短视频，最高 1080p）
  - https://youtu.be/xxxxx                 （短链接）
  - https://www.youtube.com/live/xxxxx     （直播）

YouTube 特有的下载机制：
  - YouTube 提供多种「客户端」类型（web / mweb / ios / tv 等），
    不同客户端能看到的可用格式可能不同（有时 ios 客户端能看到 4K，web 不行）
  - 需要配置 visitor_data 和 po_token（参见 README 的「Token 配置」部分）
    才能稳定看到 4K 等高画质格式
  - YouTube Shorts 本身最高只有 1080p，不会有 4K，因此会自动降低分辨率阈值

探测策略：
  最多尝试 10 种组合（5 种客户端 × 是否使用 cookies 两种模式），
  按顺序逐个尝试，找到第一个满足分辨率要求的就保存为计划。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from common import (
    build_output_template,
    build_youtube_extractor_args,
    token_runtime_summary,
    youtube_video_id_from_url,
)

from .base import BaseAdapter

# YouTube 探测时按此顺序尝试的客户端类型
# None 表示不指定客户端（让 yt-dlp 自行决定），通常等同于默认 web 客户端
# ios 客户端有时在没有 Token 的情况下也能看到 4K
# tv 客户端有时对某些地区限制较少
YOUTUBE_CLIENTS: List[Optional[str]] = [None, "web", "mweb", "ios", "tv"]


class YoutubeAdapter(BaseAdapter):
    """YouTube / YouTube Shorts 下载适配器。"""

    platform_id = "youtube"

    def build_probe_strategies(
        self,
        cookies_browser: Optional[str],
        tokens_data: Dict[str, Any],
    ) -> List[Dict[str, Optional[str]]]:
        """
        构建 YouTube 探测策略列表。
        
        策略生成逻辑：
          1. 如果设置了 po_token，将其对应的 token_client 放在最前面优先尝试
             （因为 po_token 与特定 client 绑定，用对应 client 成功率最高）
          2. 每种客户端类型都生成两个策略：
             - 不使用 cookies（不依赖浏览器，更通用）
             - 使用浏览器 cookies（需要浏览器登录，但能解锁更高画质）
        
        最终策略数量：5 客户端 × 2 = 10 种（有浏览器时），或 5 种（无浏览器时）
        """
        summary = token_runtime_summary(tokens_data)
        po_token = summary["po_token_set"]
        token_client = summary["token_client"]

        # 如果有 po_token，优先使用其绑定的 client
        if po_token and token_client in YOUTUBE_CLIENTS:
            ordered = [token_client] + [c for c in YOUTUBE_CLIENTS if c != token_client]
        else:
            ordered = list(YOUTUBE_CLIENTS)

        strategies: List[Dict[str, Optional[str]]] = []
        for client in ordered:
            # 每个客户端先尝试不带 cookies
            strategies.append({"client": client, "cookies": None})
            # 如果有可用浏览器，再尝试带 cookies 的版本
            if cookies_browser:
                strategies.append({"client": client, "cookies": cookies_browser})

        return strategies

    def build_probe_cmd(
        self,
        ytdlp_cmd: List[str],
        url: str,
        strategy: Dict[str, Optional[str]],
        js_runtime: str,
        tokens_data: Dict[str, Any],
    ) -> List[str]:
        """
        构建 YouTube 探测命令。
        
        会根据策略添加：
          - --cookies-from-browser: 从指定浏览器读取 cookies（有 cookies 时）
          - --js-runtimes: 指定 JavaScript 运行时（处理 Token 需要）
          - --extractor-args: YouTube 专属参数（client 类型、visitor_data、po_token 等）
        """
        client = strategy.get("client")
        cookies = strategy.get("cookies")

        cmd: List[str] = [*ytdlp_cmd, "--ignore-config"]
        cmd += self._base_probe_flags(use_ipv4=True)

        # 使用浏览器 cookies（有助于通过 YouTube 的登录验证）
        if cookies:
            cmd += ["--cookies-from-browser", cookies]

        # 指定 JavaScript 运行时（yt-dlp 处理 po_token 等验证时需要）
        if js_runtime and js_runtime != "auto":
            cmd += ["--js-runtimes", js_runtime]

        # 构建 YouTube 专属的 extractor-args（客户端类型 + Token）
        ex_args = build_youtube_extractor_args(client, tokens_data=tokens_data, extra_args=None)
        if ex_args:
            cmd += ["--extractor-args", ex_args]

        cmd += [url]
        return cmd

    def build_download_cmd(
        self,
        ytdlp_cmd: List[str],
        plan: Dict[str, Any],
        tokens_data: Dict[str, Any],
        js_runtime: str,
        downloads_dir: Path,
    ) -> List[str]:
        """
        构建 YouTube 实际下载命令。
        
        下载命令会：
          - 使用探测阶段确定的 format_expr（如 "313+251"，表示指定的视频流+音频流）
          - 如果是 adaptive 模式（视频和音频分开的流），自动合并为 mkv 格式
          - 输出文件名包含视频ID和格式信息，方便识别
        """
        output_template = str(downloads_dir / build_output_template(plan))

        cmd: List[str] = [*ytdlp_cmd, "--ignore-config"]
        cmd += self._base_download_flags()
        cmd += [
            "--paths", str(downloads_dir),
            "-o", output_template,
            "-f", str(plan["format_expr"]),     # 指定要下载的格式 ID
        ]

        # 使用探测阶段记录的 cookies 来源
        cookies_browser = plan.get("cookies_browser")
        if cookies_browser:
            cmd += ["--cookies-from-browser", str(cookies_browser)]

        if js_runtime and js_runtime != "auto":
            cmd += ["--js-runtimes", js_runtime]

        # 构建 extractor-args（使用探测时成功的 client 和当前 Token）
        yt_client = plan.get("yt_client")
        ex_args = build_youtube_extractor_args(yt_client, tokens_data=tokens_data, extra_args=None)
        if ex_args:
            cmd += ["--extractor-args", ex_args]

        # adaptive 模式：视频和音频是分开的流，需要 ffmpeg 合并为 mkv
        if str(plan.get("mode")) == "adaptive":
            cmd += ["--merge-output-format", "mkv"]

        cmd += [str(plan["url"])]
        return cmd

    def suggested_min_height(self, url: str, default: int) -> int:
        """
        YouTube Shorts 本身最高约 1080p（部分可能到 1280p），
        如果用户设置要求 2160p，对 Shorts 永远找不到，
        所以自动将 Shorts 的分辨率阈值降低到 1080p。
        
        普通 YouTube 视频不做任何调整，严格执行用户设置的要求。
        """
        if "youtube.com/shorts/" in url.lower():
            return min(default, 1080)
        return default

    def diag_message(self, best_seen_height: int) -> str:
        """返回 YouTube 探测失败时的诊断建议。"""
        return (
            f"本轮探测能看到的最高高度大约是: {best_seen_height}p\n"
            "[Diag] 如果浏览器里能看 4K，但这里始终只能看到 360p/1080p，"
            "通常需要配置 visitor_data / po_token（参见 README 的 Token 配置部分）"
        )

    def extract_video_id(self, url: str) -> Optional[str]:
        """提取 YouTube 视频的 11 位 ID。"""
        return youtube_video_id_from_url(url)
