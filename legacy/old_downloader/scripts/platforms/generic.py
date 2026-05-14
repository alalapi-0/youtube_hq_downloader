#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generic.py — 通用兜底平台适配器

当 URL 无法被识别为任何具体平台（YouTube / Bilibili / 抖音 / TikTok / 小红书）时，
使用此适配器作为兜底处理。

通用适配器的策略：
  - 使用最基础的 yt-dlp 参数
  - 先尝试不带 cookies，如果有浏览器则再尝试带 cookies
  - 不添加任何平台专属的 header 或认证参数

适用于：任何 yt-dlp 支持但本项目未专门适配的平台
（如 Vimeo、Twitter/X、Instagram 等）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from common import build_output_template

from .base import BaseAdapter


class GenericAdapter(BaseAdapter):
    """通用平台兜底适配器，适用于任何未被专用适配器覆盖的 URL。"""

    platform_id = "generic"

    def build_probe_strategies(
        self,
        cookies_browser: Optional[str],
        tokens_data: Dict[str, Any],
    ) -> List[Dict[str, Optional[str]]]:
        """
        通用探测策略：先不带 cookies，如有浏览器再带 cookies 尝试。
        """
        strategies: List[Dict[str, Optional[str]]] = [
            {"client": None, "cookies": None},
        ]
        if cookies_browser:
            strategies.append({"client": None, "cookies": cookies_browser})
        return strategies

    def build_probe_cmd(
        self,
        ytdlp_cmd: List[str],
        url: str,
        strategy: Dict[str, Optional[str]],
        js_runtime: str,
        tokens_data: Dict[str, Any],
    ) -> List[str]:
        """构建通用探测命令（最简参数，不添加任何平台专属配置）。"""
        cookies = strategy.get("cookies")

        cmd: List[str] = [*ytdlp_cmd, "--ignore-config"]
        cmd += self._base_probe_flags(use_ipv4=True)

        if cookies:
            cmd += ["--cookies-from-browser", cookies]

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
        """构建通用下载命令。"""
        output_template = str(downloads_dir / build_output_template(plan))

        cmd: List[str] = [*ytdlp_cmd, "--ignore-config"]
        cmd += self._base_download_flags()
        cmd += [
            "--paths", str(downloads_dir),
            "-o", output_template,
            "-f", str(plan["format_expr"]),
        ]

        cookies_browser = plan.get("cookies_browser")
        if cookies_browser:
            cmd += ["--cookies-from-browser", str(cookies_browser)]

        # adaptive 模式需要合并视频流和音频流
        if str(plan.get("mode")) == "adaptive":
            cmd += ["--merge-output-format", "mkv"]

        cmd += [str(plan["url"])]
        return cmd

    def diag_message(self, best_seen_height: int) -> str:
        """返回通用诊断信息。"""
        return f"本轮探测能看到的最高高度大约是: {best_seen_height}p"
