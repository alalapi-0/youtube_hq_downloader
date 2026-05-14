#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
router.py — URL 平台识别与适配器路由

这个文件是「平台分发中心」：
  - 根据视频 URL 判断是哪个平台（YouTube / Bilibili / 抖音 / TikTok / 小红书 / 其他）
  - 为每个平台生成稳定的缓存键（不受 URL 参数变化影响）
  - 返回对应平台的适配器实例（负责构建具体的探测和下载命令）

支持的平台：
  - YouTube（包含 Shorts、直播）
  - Bilibili（B站）
  - 小红书（Xiaohongshu）
  - 抖音（Douyin）
  - TikTok
  - 通用兜底（Generic，适用于其他 yt-dlp 支持的平台）
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Optional

from common import (
    bilibili_bvid_from_url,
    douyin_video_id_from_url,
    is_bilibili_url,
    is_douyin_url,
    is_tiktok_url,
    is_xiaohongshu_url,
    is_youtube_url,
    tiktok_video_id_from_url,
    xiaohongshu_note_id_from_url,
    youtube_video_id_from_url,
)

# 只在类型检查时导入，避免循环依赖
if TYPE_CHECKING:
    from platforms.base import BaseAdapter


# ===========================================================================
# 平台 ID 常量
# ===========================================================================
# 这些字符串常量用于标识平台，在 plan_cache.json 的缓存键前缀、
# 日志记录等场景中保持一致。

PLATFORM_YOUTUBE = "youtube"
PLATFORM_BILIBILI = "bilibili"
PLATFORM_XIAOHONGSHU = "xiaohongshu"
PLATFORM_DOUYIN = "douyin"
PLATFORM_TIKTOK = "tiktok"
PLATFORM_GENERIC = "generic"   # 通用兜底，适用于识别不到具体平台的 URL


# ===========================================================================
# URL 平台识别
# ===========================================================================

def classify_url(url: str) -> str:
    """
    根据 URL 特征判断视频所属平台，返回平台 ID 字符串。
    
    识别规则（按优先级从高到低）：
      1. YouTube 链接（youtube.com/watch、youtu.be 等）
      2. Bilibili 链接（bilibili.com/video/ 或 b23.tv/ 短链）
      3. 小红书链接（xiaohongshu.com/explore/ 等）
      4. 抖音链接（douyin.com/video/ 等）
      5. TikTok 链接（tiktok.com 等）
      6. 其他：返回 "generic"（通用兜底）
    
    参数：
        url: 要识别的视频 URL
    返回：
        平台 ID 字符串（PLATFORM_* 常量之一）
    
    示例：
        classify_url("https://www.youtube.com/watch?v=xxx") → "youtube"
        classify_url("https://www.bilibili.com/video/BV1xxx") → "bilibili"
        classify_url("https://example.com/video") → "generic"
    """
    if is_youtube_url(url):
        return PLATFORM_YOUTUBE
    if is_bilibili_url(url):
        return PLATFORM_BILIBILI
    if is_xiaohongshu_url(url):
        return PLATFORM_XIAOHONGSHU
    if is_douyin_url(url):
        return PLATFORM_DOUYIN
    if is_tiktok_url(url):
        return PLATFORM_TIKTOK
    return PLATFORM_GENERIC


# ===========================================================================
# 稳定缓存键生成
# ===========================================================================

def cache_key_for_url(url: str) -> str:
    """
    为 URL 生成稳定的缓存键（用作 plan_cache.json 中的字典键）。
    
    「稳定」的含义：同一个视频，无论 URL 带了什么查询参数，都应该映射到同一个缓存键。
    例如，小红书 URL 中的 xsec_token 参数会不断变化，
    但只要是同一条笔记，note_id 是不变的，所以用 note_id 作为缓存键。
    
    各平台缓存键格式：
      - YouTube:   "youtube:{11位视频ID}"      如 "youtube:LJkIVzy7DSc"
      - Bilibili:  "bilibili:{BV号}"           如 "bilibili:BV1d6HKexEe8"
      - 小红书:    "xhs:{24位hex note_id}"     如 "xhs:674b2a5d000000000201bfb3"
      - 抖音:      "douyin:{数字ID}"           如 "douyin:7616874077805890835"
      - TikTok:    "tiktok:{数字ID}"           如 "tiktok:7553069613832080658"
      - 通用:      原始 URL（无法提取稳定ID时的兜底）
    
    参数：
        url: 视频 URL
    返回：
        稳定的缓存键字符串
    """
    platform = classify_url(url)

    if platform == PLATFORM_YOUTUBE:
        vid = youtube_video_id_from_url(url)
        if vid:
            return f"youtube:{vid}"
        return url

    if platform == PLATFORM_BILIBILI:
        bvid = bilibili_bvid_from_url(url)
        if bvid:
            return f"bilibili:{bvid}"
        return url

    if platform == PLATFORM_XIAOHONGSHU:
        note_id = xiaohongshu_note_id_from_url(url)
        if note_id:
            return f"xhs:{note_id}"
        return url

    if platform == PLATFORM_DOUYIN:
        vid = douyin_video_id_from_url(url)
        if vid:
            return f"douyin:{vid}"
        return url

    if platform == PLATFORM_TIKTOK:
        vid = tiktok_video_id_from_url(url)
        if vid:
            return f"tiktok:{vid}"
        return url

    return url  # 通用兜底：直接使用原始 URL


# ===========================================================================
# 平台适配器注册表
# ===========================================================================

# 全局适配器注册表：平台 ID → 适配器实例
# 使用延迟初始化（首次访问时才导入各平台模块），避免循环依赖问题
_ADAPTER_REGISTRY: Dict[str, "BaseAdapter"] = {}
_REGISTRY_INITIALIZED = False


def _init_registry() -> None:
    """
    初始化平台适配器注册表（延迟加载，只执行一次）。
    
    延迟加载的原因：各平台模块可能导入 common.py，
    而 common.py 和 router.py 的导入顺序需要管理，
    在函数内部导入可以避免潜在的循环依赖问题。
    """
    global _REGISTRY_INITIALIZED
    if _REGISTRY_INITIALIZED:
        return

    # 导入各平台适配器（仅在第一次调用时执行）
    from platforms.bilibili import BilibiliAdapter
    from platforms.douyin import DouyinAdapter
    from platforms.generic import GenericAdapter
    from platforms.tiktok import TikTokAdapter
    from platforms.xiaohongshu import XiaohongshuAdapter
    from platforms.youtube import YoutubeAdapter

    # 注册所有平台适配器
    _ADAPTER_REGISTRY[PLATFORM_YOUTUBE] = YoutubeAdapter()
    _ADAPTER_REGISTRY[PLATFORM_BILIBILI] = BilibiliAdapter()
    _ADAPTER_REGISTRY[PLATFORM_XIAOHONGSHU] = XiaohongshuAdapter()
    _ADAPTER_REGISTRY[PLATFORM_DOUYIN] = DouyinAdapter()
    _ADAPTER_REGISTRY[PLATFORM_TIKTOK] = TikTokAdapter()
    _ADAPTER_REGISTRY[PLATFORM_GENERIC] = GenericAdapter()   # 通用兜底

    _REGISTRY_INITIALIZED = True


def get_adapter(platform_id: str) -> "BaseAdapter":
    """
    根据平台 ID 获取对应的适配器实例。
    
    适配器负责为该平台构建具体的 yt-dlp 命令（探测命令和下载命令），
    以及提供平台特有的分辨率建议和错误诊断信息。
    
    参数：
        platform_id: 平台 ID（PLATFORM_* 常量之一，由 classify_url 返回）
    返回：
        对应平台的 BaseAdapter 子类实例；
        未知平台返回 GenericAdapter（通用兜底适配器）
    
    示例：
        adapter = get_adapter("youtube")    # 返回 YoutubeAdapter 实例
        adapter = get_adapter("bilibili")   # 返回 BilibiliAdapter 实例
        adapter = get_adapter("unknown")    # 返回 GenericAdapter（兜底）
    """
    _init_registry()
    if platform_id in _ADAPTER_REGISTRY:
        return _ADAPTER_REGISTRY[platform_id]
    return _ADAPTER_REGISTRY[PLATFORM_GENERIC]


def get_adapter_for_url(url: str) -> "BaseAdapter":
    """
    根据 URL 直接获取适配器实例（classify_url + get_adapter 的便捷组合）。
    
    参数：
        url: 视频 URL
    返回：
        对应平台的适配器实例
    
    等价于：get_adapter(classify_url(url))
    """
    return get_adapter(classify_url(url))
