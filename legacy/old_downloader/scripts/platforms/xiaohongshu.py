#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xiaohongshu.py — 小红书平台适配器

支持的 URL 格式：
  - https://www.xiaohongshu.com/explore/{24位hex note_id}?...
  - https://xhslink.com/xxxxx （短链接）
  - https://www.xiaohongshu.com/discovery/item/{note_id}?...

小红书的下载特点：
  - 小红书 URL 包含会变化的 xsec_token 等查询参数，
    使用 note_id（24位十六进制）作为稳定缓存键
  - 需要添加 Referer header（防盗链机制，否则资源请求可能返回 403）
  - 平台本身最高约 1080p，不提供 4K，因此会自动降低分辨率阈值
  - 不使用 YouTube 的 Token 机制

探测策略：
  两种策略：不带 cookies，带 cookies（某些内容可能需要登录）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from common import build_output_template, xiaohongshu_note_id_from_url

from .base import BaseAdapter

# 小红书平台实际最高分辨率上限
XHS_MAX_HEIGHT = 1080


class XiaohongshuAdapter(BaseAdapter):
    """小红书视频下载适配器。"""

    platform_id = "xiaohongshu"

    def build_probe_strategies(
        self,
        cookies_browser: Optional[str],
        tokens_data: Dict[str, Any],
    ) -> List[Dict[str, Optional[str]]]:
        """
        构建小红书探测策略。
        
        策略 1：不带 cookies（公开内容无需登录）
        策略 2：带 cookies（需要登录才能查看的内容）
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
        """
        构建小红书探测命令。
        
        特殊参数：--add-headers Referer:https://www.xiaohongshu.com
        小红书 CDN 会检查请求来源（Referer），
        必须带上小红书域名，否则视频资源请求会被拒绝。
        """
        cookies = strategy.get("cookies")

        cmd: List[str] = [*ytdlp_cmd, "--ignore-config"]
        cmd += self._base_probe_flags(use_ipv4=True)

        if cookies:
            cmd += ["--cookies-from-browser", cookies]

        # 小红书防盗链：必须携带正确的 Referer header
        cmd += [
            "--add-headers",
            "Referer:https://www.xiaohongshu.com",
        ]

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
        """构建小红书下载命令（同样需要带 Referer header）。"""
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

        # 下载阶段同样需要 Referer
        cmd += [
            "--add-headers",
            "Referer:https://www.xiaohongshu.com",
        ]

        if str(plan.get("mode")) == "adaptive":
            cmd += ["--merge-output-format", "mkv"]

        cmd += [str(plan["url"])]
        return cmd

    def suggested_min_height(self, url: str, default: int) -> int:
        """
        小红书视频本身最高约 1080p，
        自动降级分辨率阈值，避免因要求 4K 而永远找不到计划。
        返回 960p/1280p 视为该视频的最高画质属于正常情况。
        """
        return min(default, XHS_MAX_HEIGHT)

    def diag_message(self, best_seen_height: int) -> str:
        """返回小红书探测失败时的诊断建议。"""
        return (
            f"本轮探测能看到的最高高度大约是: {best_seen_height}p\n"
            "[Diag] 小红书视频通常最高 1080p，不支持 4K；"
            "如果返回 960p/1280p 即为该视频最高画质，属于正常情况"
        )

    def extract_video_id(self, url: str) -> Optional[str]:
        """提取小红书笔记的 24 位 note_id。"""
        return xiaohongshu_note_id_from_url(url)
