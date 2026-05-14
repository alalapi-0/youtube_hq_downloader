#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/platforms 包

导出所有平台适配器及 BaseAdapter 基类。
"""

from __future__ import annotations

from .base import BaseAdapter
from .bilibili import BilibiliAdapter
from .douyin import DouyinAdapter
from .generic import GenericAdapter
from .tiktok import TikTokAdapter
from .xiaohongshu import XiaohongshuAdapter
from .youtube import YoutubeAdapter

__all__ = [
    "BaseAdapter",
    "YoutubeAdapter",
    "BilibiliAdapter",
    "XiaohongshuAdapter",
    "DouyinAdapter",
    "TikTokAdapter",
    "GenericAdapter",
]
