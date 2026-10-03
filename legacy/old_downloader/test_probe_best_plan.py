#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round 4 单元测试：probe_best_plan.py 核心函数
"""

import sys
from pathlib import Path

# 添加 scripts 目录到 Python 路径
SCRIPT_DIR = Path(__file__).resolve().parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from probe_best_plan import (
    is_video_only_format,
    is_audio_only_format,
    is_combined_av_format,
    is_valid_media_format,
    video_codec_rank,
    audio_codec_rank,
    hdr_rank,
    build_youtube_probe_strategies,
    build_generic_probe_strategies,
)
from common import cache_key_for_url


def test_format_filters():
    """测试格式过滤器"""
    print("Testing format filters...")
    
    # 视频only
    assert is_video_only_format({"vcodec": "vp9", "acodec": "none"}) == True
    assert is_video_only_format({"vcodec": "none", "acodec": "opus"}) == False
    
    # 音频only
    assert is_audio_only_format({"vcodec": "none", "acodec": "opus"}) == True
    assert is_audio_only_format({"vcodec": "vp9", "acodec": "none"}) == False
    
    # 合流
    assert is_combined_av_format({"vcodec": "vp9", "acodec": "opus"}) == True
    assert is_combined_av_format({"vcodec": "none", "acodec": "opus"}) == False
    
    # 有效性
    assert is_valid_media_format({"format_note": "storyboard"}) == False
    assert is_valid_media_format({"ext": "mhtml"}) == False
    assert is_valid_media_format({"format_note": "1080p", "ext": "mp4"}) == True
    
    print("✅ Format filters OK")


def test_codec_rankings():
    """测试编解码器排序"""
    print("Testing codec rankings...")
    
    # 视频编解码器
    assert video_codec_rank("av01") > video_codec_rank("vp9")
    assert video_codec_rank("vp9.2") > video_codec_rank("vp9")
    assert video_codec_rank("vp9") > video_codec_rank("avc1")
    assert video_codec_rank("avc1") > video_codec_rank("none")
    
    # 音频编解码器
    assert audio_codec_rank("opus") > audio_codec_rank("aac")
    assert audio_codec_rank("aac") > audio_codec_rank("vorbis")
    assert audio_codec_rank("vorbis") > audio_codec_rank("none")
    
    print("✅ Codec rankings OK")


def test_hdr_ranking():
    """测试 HDR 排序"""
    print("Testing HDR ranking...")
    
    assert hdr_rank({"dynamic_range": "HDR10"}) == 2
    assert hdr_rank({"dynamic_range": "DV"}) == 2
    assert hdr_rank({"dynamic_range": "SDR"}) == 1
    assert hdr_rank({"dynamic_range": ""}) == 0
    
    assert hdr_rank({"dynamic_range": "HDR10"}) > hdr_rank({"dynamic_range": "SDR"})
    assert hdr_rank({"dynamic_range": "SDR"}) > hdr_rank({"dynamic_range": ""})
    
    print("✅ HDR ranking OK")


def test_cache_key():
    """测试缓存键生成"""
    print("Testing cache key generation...")
    
    key1 = cache_key_for_url("https://www.youtube.com/watch?v=BhNImM1N6vM")
    assert key1 == "youtube:BhNImM1N6vM"
    
    key2 = cache_key_for_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert key2 == "youtube:dQw4w9WgXcQ"
    
    # 非 YouTube URL 直接返回原 URL
    key3 = cache_key_for_url("https://example.com/video.mp4")
    assert key3 == "https://example.com/video.mp4"
    
    print("✅ Cache key generation OK")


def test_strategy_builders():
    """测试策略构建器"""
    print("Testing strategy builders...")
    
    # YouTube 策略（10种组合）
    strategies = build_youtube_probe_strategies(
        "chrome", 
        {"youtube": {"po_token": "", "token_client": "web"}}
    )
    assert len(strategies) == 10  # 5 clients × 2 cookie states
    
    # 验证策略结构
    first = strategies[0]
    assert "client" in first
    assert "cookies" in first
    
    print("✅ YouTube strategy builder OK")
    
    # 通用站点策略（2种组合）
    generic = build_generic_probe_strategies("chrome")
    assert len(generic) == 2
    assert generic[0]["client"] is None
    assert generic[0]["cookies"] is None
    assert generic[1]["cookies"] == "chrome"
    
    print("✅ Generic strategy builder OK")


def test_token_client_priority():
    """测试 token_client 优先级"""
    print("Testing token_client priority...")
    
    # 有 po_token 时，对应 client 优先
    strategies = build_youtube_probe_strategies(
        "chrome",
        {"youtube": {"po_token": "abc123", "token_client": "mweb"}}
    )
    
    # 第一个 client 应该是 mweb（对应 token_client）
    first_client = strategies[0]["client"]
    assert first_client == "mweb"
    
    print("✅ Token client priority OK")


def main():
    """运行所有测试"""
    print("=" * 60)
    print("Round 4 Unit Tests: probe_best_plan.py")
    print("=" * 60)
    print()
    
    try:
        test_format_filters()
        test_codec_rankings()
        test_hdr_ranking()
        test_cache_key()
        test_strategy_builders()
        test_token_client_priority()
        
        print()
        print("=" * 60)
        print("All tests passed! ✅")
        print("=" * 60)
        return 0
        
    except AssertionError as e:
        print()
        print("=" * 60)
        print(f"Test failed! ❌")
        print(f"Error: {e}")
        print("=" * 60)
        return 1
    except Exception as e:
        print()
        print("=" * 60)
        print(f"Unexpected error! ❌")
        print(f"Error: {e}")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
