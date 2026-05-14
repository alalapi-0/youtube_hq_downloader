#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tiktok.py — TikTok 平台适配器

支持的 URL 格式：
  - https://www.tiktok.com/@{用户名}/video/{数字ID}?...
  - https://vm.tiktok.com/xxxxx （短链接）

TikTok 的下载特点：
  - **不使用**浏览器 cookies（测试发现带 cookies 反而会导致「Unexpected response」错误）
  - 平台本身最高约 1080p，不提供 4K，因此会自动降低分辨率阈值
  - 不使用 YouTube 的 Token 机制
  - 如果反复失败，通常是网络/IP 问题（如需要 VPN 或换节点）

探测策略：
  只有一种策略：不带 cookies（带了反而有问题）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from common import build_output_template, tiktok_video_id_from_url

from .base import BaseAdapter

# TikTok 平台实际最高分辨率上限
TIKTOK_MAX_HEIGHT = 1080


class TikTokAdapter(BaseAdapter):
    """TikTok 视频下载适配器。"""

    platform_id = "tiktok"

    def build_probe_strategies(
        self,
        cookies_browser: Optional[str],
        tokens_data: Dict[str, Any],
    ) -> List[Dict[str, Optional[str]]]:
        """
        构建 TikTok 探测策略。
        
        TikTok 只使用「无 cookies」这一种策略。
        虽然提供了 cookies_browser 参数，但测试显示 TikTok 带浏览器 cookies
        会导致 yt-dlp 返回「Unexpected response」错误，所以故意不使用。
        """
        return [{"client": None, "cookies": None}]

    def build_probe_cmd(
        self,
        ytdlp_cmd: List[str],
        url: str,
        strategy: Dict[str, Optional[str]],
        js_runtime: str,
        tokens_data: Dict[str, Any],
    ) -> List[str]:
        """构建 TikTok 探测命令（不添加任何认证参数）。"""
        cmd: List[str] = [*ytdlp_cmd, "--ignore-config"]
        cmd += self._base_probe_flags(use_ipv4=True)
        # TikTok 不使用 cookies，不加任何认证参数
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
        构建 TikTok 下载命令。
        
        注意：TikTok 通常不需要 cookies，
        但如果 plan 中明确记录了 cookies_browser（未来扩展场景），仍然会尊重。
        """
        output_template = str(downloads_dir / build_output_template(plan))

        cmd: List[str] = [*ytdlp_cmd, "--ignore-config"]
        cmd += self._base_download_flags()
        cmd += [
            "--paths", str(downloads_dir),
            "-o", output_template,
            "-f", str(plan["format_expr"]),
        ]

        # 通常为空，但保留以备未来需要
        cookies_browser = plan.get("cookies_browser")
        if cookies_browser:
            cmd += ["--cookies-from-browser", str(cookies_browser)]

        if str(plan.get("mode")) == "adaptive":
            cmd += ["--merge-output-format", "mkv"]

        cmd += [str(plan["url"])]
        return cmd

    def suggested_min_height(self, url: str, default: int) -> int:
        """TikTok 最高约 1080p，自动降级分辨率阈值。"""
        return min(default, TIKTOK_MAX_HEIGHT)

    def diag_message(self, best_seen_height: int) -> str:
        """返回 TikTok 探测失败时的诊断建议。"""
        return (
            f"本轮探测能看到的最高高度大约是: {best_seen_height}p\n"
            "[Diag] TikTok 下载通常不需要 cookies；"
            "若反复失败通常是网络/IP 问题，建议检查网络环境或尝试更换 VPN 节点"
        )

    def extract_video_id(self, url: str) -> Optional[str]:
        """提取 TikTok 视频的数字 ID。"""
        return tiktok_video_id_from_url(url)
