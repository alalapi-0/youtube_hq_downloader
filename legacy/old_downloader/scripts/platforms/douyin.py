#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
douyin.py — 抖音平台适配器

支持的 URL 格式：
  - https://www.douyin.com/video/{数字ID}
  - https://v.douyin.com/xxxxx （短链接，会重定向到上面的格式）

抖音的下载特点：
  - **必须**提供浏览器 cookies（无 cookies 必然失败，这是抖音的反爬要求）
  - 需要添加 Referer header（否则视频流请求会被拒绝返回 403）
  - 平台本身最高约 1080p，不提供 4K 内容，因此会自动降低分辨率阈值
  - 不使用 YouTube 的 Token 机制

注意事项：
  使用浏览器 cookies 下载抖音时，确保浏览器（Chrome 等）中已访问过抖音，
  且未退出登录状态。

探测策略：
  只有一种策略：带 cookies（无 cookies 无法探测，强制要求）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from common import build_output_template, douyin_video_id_from_url

from .base import BaseAdapter

# 抖音平台实际最高分辨率上限（平台不提供 4K）
DOUYIN_MAX_HEIGHT = 1080


class DouyinAdapter(BaseAdapter):
    """抖音视频下载适配器。"""

    platform_id = "douyin"

    def build_probe_strategies(
        self,
        cookies_browser: Optional[str],
        tokens_data: Dict[str, Any],
    ) -> List[Dict[str, Optional[str]]]:
        """
        构建抖音探测策略。
        
        抖音必须提供浏览器 cookies 才能正常获取视频信息。
        如果没有检测到浏览器，仍然会尝试无 cookies 策略，
        这样至少能从 yt-dlp 的错误输出中获得明确的失败原因。
        """
        if cookies_browser:
            # 有浏览器：使用 cookies（正常情况）
            return [{"client": None, "cookies": cookies_browser}]
        else:
            # 没有浏览器：尝试无 cookies（预期会失败，但能看到错误信息）
            return [{"client": None, "cookies": None}]

    def build_probe_cmd(
        self,
        ytdlp_cmd: List[str],
        url: str,
        strategy: Dict[str, Optional[str]],
        js_runtime: str,
        tokens_data: Dict[str, Any],
    ) -> List[str]:
        """
        构建抖音探测命令。
        
        特殊参数：--add-headers Referer:https://www.douyin.com
        抖音的视频流 CDN 会校验请求来源（Referer），
        必须带上抖音自己的域名作为来源，否则请求会被拒绝。
        """
        cookies = strategy.get("cookies")

        cmd: List[str] = [*ytdlp_cmd, "--ignore-config"]
        cmd += self._base_probe_flags(use_ipv4=True)

        if cookies:
            cmd += ["--cookies-from-browser", cookies]

        # 抖音要求请求带有 Referer header（防盗链机制）
        cmd += [
            "--add-headers",
            "Referer:https://www.douyin.com",
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
        """构建抖音下载命令（同样需要带 Referer header）。"""
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

        # 下载阶段同样需要 Referer（否则实际视频流下载会 403）
        cmd += [
            "--add-headers",
            "Referer:https://www.douyin.com",
        ]

        if str(plan.get("mode")) == "adaptive":
            cmd += ["--merge-output-format", "mkv"]

        cmd += [str(plan["url"])]
        return cmd

    def suggested_min_height(self, url: str, default: int) -> int:
        """
        抖音平台本身最高约 1080p，
        自动将分辨率阈值降级为 1080p，避免因要求 4K 而永远找不到计划。
        """
        return min(default, DOUYIN_MAX_HEIGHT)

    def diag_message(self, best_seen_height: int) -> str:
        """返回抖音探测失败时的诊断建议。"""
        return (
            f"本轮探测能看到的最高高度大约是: {best_seen_height}p\n"
            "[Diag] 抖音下载必须提供浏览器 cookies；"
            "请确认已在 Chrome 中访问过抖音且未退出登录，"
            "或尝试先在 Chrome 中打开该视频页面后再重试"
        )

    def extract_video_id(self, url: str) -> Optional[str]:
        """提取抖音视频的数字 ID。"""
        return douyin_video_id_from_url(url)
