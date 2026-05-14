#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
base.py — 平台适配器抽象基类

所有平台适配器（YouTube / Bilibili / 抖音等）都必须继承这个基类，
并实现三个核心抽象方法：
  - build_probe_strategies: 返回探测策略列表（尝试哪些 client / cookies 组合）
  - build_probe_cmd: 根据策略构建具体的探测命令
  - build_download_cmd: 构建实际下载命令

每个平台的下载行为不同（需要不同的认证方式、header等），
通过适配器模式，可以统一调用接口，同时保持各平台逻辑的独立性。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional


class BaseAdapter(ABC):
    """
    视频平台下载适配器抽象基类。
    
    子类必须实现：build_probe_strategies、build_probe_cmd、build_download_cmd
    子类可选覆盖：suggested_min_height、diag_message、extract_video_id
    """

    #: 平台唯一标识字符串（子类必须覆盖，如 "youtube"、"bilibili"）
    platform_id: str = "generic"

    # ===========================================================================
    # 抽象方法（子类必须实现）
    # ===========================================================================

    @abstractmethod
    def build_probe_strategies(
        self,
        cookies_browser: Optional[str],
        tokens_data: Dict[str, Any],
    ) -> List[Dict[str, Optional[str]]]:
        """
        返回该平台的探测策略列表。
        
        探测时会按列表顺序逐个尝试策略，直到找到一个符合分辨率要求的计划为止。
        策略数量越多，找到最佳计划的可能性越大，但耗时也越长。
        
        每个策略是一个字典，包含：
          - "client": str | None — yt-dlp 使用的 YouTube 客户端名称（仅 YouTube 使用）
                                   其他平台统一设为 None
          - "cookies": str | None — 浏览器名称（如 "chrome"），None 表示不使用浏览器 cookies
        
        示例（通用两策略：先不用 cookies，再用 cookies）：
          [{"client": None, "cookies": None},
           {"client": None, "cookies": "chrome"}]
        
        参数：
            cookies_browser: 检测到的浏览器名称（来自 env_state.json），None 表示无浏览器
            tokens_data: 当前生效的 Token 数据（经 effective_tokens_data 处理）
        返回：
            策略字典列表
        """
        ...

    @abstractmethod
    def build_probe_cmd(
        self,
        ytdlp_cmd: List[str],
        url: str,
        strategy: Dict[str, Optional[str]],
        js_runtime: str,
        tokens_data: Dict[str, Any],
    ) -> List[str]:
        """
        根据给定策略构建 yt-dlp 探测命令。
        
        探测命令使用 --skip-download --dump-single-json 参数，
        只获取视频信息（格式列表、分辨率等），不实际下载视频内容。
        
        参数：
            ytdlp_cmd: yt-dlp 基础命令（如 ["python3", "-m", "yt_dlp"]）
            url: 目标视频 URL
            strategy: 来自 build_probe_strategies 的单个策略字典
            js_runtime: JavaScript 运行时名称（如 "node"），供 yt-dlp 处理 Token
            tokens_data: 当前生效的 Token 数据
        返回：
            完整的命令行参数列表，可直接传入 subprocess.run()
        """
        ...

    @abstractmethod
    def build_download_cmd(
        self,
        ytdlp_cmd: List[str],
        plan: Dict[str, Any],
        tokens_data: Dict[str, Any],
        js_runtime: str,
        downloads_dir: Path,
    ) -> List[str]:
        """
        构建实际下载视频的 yt-dlp 命令。
        
        下载命令会使用探测阶段已确定的格式 ID，直接下载最佳质量的视频和音频，
        并在需要时自动合并为 mkv 文件。
        
        参数：
            ytdlp_cmd: yt-dlp 基础命令
            plan: 来自 plan_cache.json 的下载计划字典（包含格式ID、分辨率等）
            tokens_data: 当前生效的 Token 数据
            js_runtime: JavaScript 运行时名称
            downloads_dir: 视频下载目标目录（Path 对象）
        返回：
            完整的命令行参数列表
        """
        ...

    # ===========================================================================
    # 可选覆盖方法（有默认实现，子类按需覆盖）
    # ===========================================================================

    def suggested_min_height(self, url: str, default: int) -> int:
        """
        为特定 URL 建议最低分辨率阈值。
        
        部分平台或内容类型本身不支持 4K（如抖音最高 1080p，YouTube Shorts 最高 1080p），
        此时强制要求 2160p 会导致永远找不到合适的计划。
        子类可以覆盖此方法，在适当的情况下降低分辨率阈值。
        
        默认行为：直接返回 default，不做任何调整（适用于可能有 4K 的平台）。
        
        参数：
            url: 目标视频 URL（可用于区分 Shorts 和普通视频等）
            default: 用户在配置中设置的最低分辨率要求（如 2160）
        返回：
            实际使用的最低分辨率阈值
        """
        return default

    def diag_message(self, best_seen_height: int) -> str:
        """
        返回探测失败时的平台专属诊断建议。
        
        当探测结束但找不到符合分辨率要求的格式时，调用此方法获取给用户的提示信息。
        子类可以根据平台特点提供有针对性的建议（如 Bilibili 需要登录 cookies 才能看 4K）。
        
        默认行为：返回空字符串（使用通用提示）。
        
        参数：
            best_seen_height: 本轮所有探测策略中能看到的最高分辨率
        返回：
            诊断提示字符串，空字符串表示使用通用提示
        """
        return ""

    def extract_video_id(self, url: str) -> Optional[str]:
        """
        从 URL 中提取稳定的视频/内容唯一 ID。
        
        此 ID 用于生成不随 URL 参数变化的缓存键（在 router.py 中使用）。
        子类可覆盖此方法来提供平台专属的 ID 提取逻辑。
        
        默认行为：返回 None（由 router 使用原始 URL 作为缓存键）。
        
        参数：
            url: 视频 URL
        返回：
            稳定的唯一 ID 字符串，或 None
        """
        return None

    # ===========================================================================
    # 内部辅助方法（子类可直接复用，无需重复实现）
    # ===========================================================================

    def _base_probe_flags(self, use_ipv4: bool = True) -> List[str]:
        """
        返回所有平台探测阶段通用的 yt-dlp 参数列表。
        
        这些参数告诉 yt-dlp：
          --skip-download: 只获取信息，不下载视频
          --dump-single-json: 将视频信息以单行 JSON 输出（便于程序解析）
          --no-warnings: 不显示警告信息（保持输出干净）
          --no-playlist: 只处理单个视频，不展开播放列表
          --force-ipv4: 强制使用 IPv4 网络（避免 IPv6 可能带来的访问问题）
        
        参数：
            use_ipv4: 是否添加 --force-ipv4 参数（默认 True）
        返回：
            yt-dlp 参数列表
        """
        flags = [
            "--skip-download",
            "--dump-single-json",
            "--no-warnings",
            "--no-playlist",
        ]
        if use_ipv4:
            flags.append("--force-ipv4")
        return flags

    def _base_download_flags(
        self,
        socket_timeout: int = 60,
        retries: int = 50,
        fragment_retries: int = 50,
        retry_sleep_count: int = 10,
        http_retry_sleep: str = "10",
        fragment_retry_sleep: str = "5",
        sleep_requests: float = 1.0,
        concurrent_fragments: int = 1,
        use_ipv4: bool = True,
    ) -> List[str]:
        """
        返回所有平台下载阶段通用的 yt-dlp 参数列表。
        
        这些参数配置了下载的可靠性策略：
          -c: 支持断点续传（Continue，遇到中断可以继续）
          --newline --progress: 实时显示下载进度
          --socket-timeout: 网络连接超时时间（秒）
          --retries: 下载失败最多重试次数
          --fragment-retries: 分片下载失败最多重试次数
          --retry-sleep: 重试前等待时间（避免频繁请求触发限流）
          --sleep-requests: 请求之间的间隔（降低请求频率，减少被限流概率）
          --concurrent-fragments: 同时下载的分片数量（1 = 不并发，更稳定）
          --force-ipv4: 强制使用 IPv4
        
        参数可以按需调整，但建议保持默认值以确保稳定性。
        """
        flags = [
            "-c",                                       # 断点续传
            "--newline",                                # 进度信息换行显示
            "--progress",                               # 显示进度
            "--socket-timeout", str(socket_timeout),   # 连接超时
            "--retries", str(retries),                  # 重试次数
            "--fragment-retries", str(fragment_retries), # 分片重试次数
            "-R", str(retry_sleep_count),               # 重试睡眠次数
            "--retry-sleep", f"http:{http_retry_sleep}",         # HTTP 重试间隔
            "--retry-sleep", f"fragment:{fragment_retry_sleep}", # 分片重试间隔
            "--sleep-requests", str(sleep_requests),    # 请求间隔
            "--concurrent-fragments", str(concurrent_fragments), # 并发分片数
        ]
        if use_ipv4:
            flags.append("--force-ipv4")
        return flags
