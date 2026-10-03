#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 ffprobe 和子进程运行功能
"""

from pathlib import Path
from scripts.common import (
    which,
    run_capture_raw,
    ensure_ffmpeg_and_ffprobe,
    ffprobe_video_info,
    validate_downloaded_file,
)

print("=" * 60)
print("测试 ffprobe 和子进程功能")
print("=" * 60)

# 1. 确认 ffmpeg/ffprobe 可用
print("\n[1] 检查 ffmpeg/ffprobe:")
ffmpeg_path = which("ffmpeg")
ffprobe_path = which("ffprobe")
print(f"  ffmpeg: {ffmpeg_path}")
print(f"  ffprobe: {ffprobe_path}")

if not ffmpeg_path or not ffprobe_path:
    print("\n❌ ffmpeg/ffprobe 未安装，跳过视频测试")
else:
    # 2. 测试 run_capture_raw
    print("\n[2] 测试命令捕获:")
    rc, out, err = run_capture_raw([ffprobe_path, "-version"])
    print(f"  返回码: {rc}")
    print(f"  输出前 100 字符: {out[:100] if out else '(empty)'}")
    
    # 3. 检查 downloads 目录中是否有视频文件
    print("\n[3] 检查本地视频文件:")
    downloads_dir = Path("downloads")
    if downloads_dir.exists():
        video_files = list(downloads_dir.glob("**/*.mp4")) + \
                     list(downloads_dir.glob("**/*.mkv")) + \
                     list(downloads_dir.glob("**/*.webm"))
        
        if video_files:
            test_video = video_files[0]
            print(f"  找到测试视频: {test_video.name}")
            
            # 测试 ffprobe_video_info
            info = ffprobe_video_info(test_video)
            if info:
                print(f"  视频信息:")
                print(f"    分辨率: {info['width']}x{info['height']}")
                print(f"    编码: {info['codec']}")
                print(f"    帧率: {info['fps']:.2f} fps")
                print(f"    大小: {info['size_bytes'] / 1024 / 1024:.2f} MB")
                print(f"    时长: {info['duration']:.2f} 秒")
                
                # 测试 validate_downloaded_file
                valid, msg, _ = validate_downloaded_file(test_video, 720)
                print(f"  验证 720p: {valid} - {msg}")
            else:
                print("  ❌ 无法读取视频信息")
        else:
            print("  downloads 目录中没有视频文件")
    else:
        print("  downloads 目录不存在")

print("\n" + "=" * 60)
print("✅ ffprobe 测试完成！")
print("=" * 60)
