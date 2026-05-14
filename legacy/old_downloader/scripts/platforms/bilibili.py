#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bilibili.py — Bilibili（B站）平台适配器

支持的 URL 格式：
  - https://www.bilibili.com/video/BV1xxx/  （BV 号格式，现行标准）
  - https://www.bilibili.com/video/av12345/ （av 号格式，旧版，仍支持）

Bilibili 的下载特点：
  - 普通画质（1080p 及以下）无需登录也能下载
  - 4K 高画质需要登录状态的 cookies
  - 不使用 YouTube 专属的 Token（visitor_data / po_token）
  - 使用浏览器 cookies 时，确保浏览器里已登录 Bilibili 账号

探测策略：
  两种策略：不带 cookies（先尝试），带 cookies（需要高画质时）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from common import bilibili_bvid_from_url, build_output_template

from .base import BaseAdapter


class BilibiliAdapter(BaseAdapter):
    """Bilibili（B站）视频下载适配器。"""

    platform_id = "bilibili"

    def build_probe_strategies(
        self,
        cookies_browser: Optional[str],
        tokens_data: Dict[str, Any],
    ) -> List[Dict[str, Optional[str]]]:
        """
        构建 Bilibili 探测策略。
        
        策略 1：不带 cookies（适用于 1080p 及以下）
        策略 2：带 cookies（需要 4K，必须有浏览器登录状态）
        
        Bilibili 不使用 YouTube 的 Token 机制（client 字段始终为 None）。
        """
        strategies: List[Dict[str, Optional[str]]] = [
            {"client": None, "cookies": None},   # 先尝试无 cookies
        ]
        if cookies_browser:
            # 有浏览器时追加带 cookies 的策略（用于解锁 4K）
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
        """构建 Bilibili 探测命令（仅基础参数 + 可选 cookies，无 YouTube 专属参数）。"""
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
        """构建 Bilibili 下载命令。"""
        output_template = str(downloads_dir / build_output_template(plan))

        cmd: List[str] = [*ytdlp_cmd, "--ignore-config"]
        cmd += self._base_download_flags()
        cmd += [
            "--paths", str(downloads_dir),
            "-o", output_template,
            "-f", str(plan["format_expr"]),
        ]

        # 使用探测时确认有效的 cookies
        cookies_browser = plan.get("cookies_browser")
        if cookies_browser:
            cmd += ["--cookies-from-browser", str(cookies_browser)]

        # adaptive 模式需要 ffmpeg 合并视频流和音频流
        if str(plan.get("mode")) == "adaptive":
            cmd += ["--merge-output-format", "mkv"]

        cmd += [str(plan["url"])]
        return cmd

    def diag_message(self, best_seen_height: int) -> str:
        """返回 Bilibili 探测失败时的诊断建议。"""
        return (
            f"本轮探测能看到的最高高度大约是: {best_seen_height}p\n"
            "[Diag] Bilibili 4K 下载通常需要已登录 Bilibili 账号的浏览器 cookies，"
            "建议使用 Chrome 并确认浏览器中已登录"
        )

    def extract_video_id(self, url: str) -> Optional[str]:
        """提取 Bilibili 视频的 BV 号或 av 号。"""
        return bilibili_bvid_from_url(url)
