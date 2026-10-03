#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完整测试 scripts/common.py 的所有核心功能
"""

from pathlib import Path
from scripts.common import (
    # 环境探测
    detect_python,
    detect_cookies_browser,
    detect_all_browsers,
    detect_js_runtime,
    ensure_ytdlp_installed,
    get_ytdlp_version,
    get_ytdlp_cmd_display,
    detect_ytdlp_source,
    which,
    ensure_ffmpeg_and_ffprobe,
    
    # URL 处理
    is_youtube_url,
    youtube_video_id_from_url,
    cache_key_for_url,
    
    # JSON 操作
    load_json,
    save_json,
    append_jsonl,
    
    # 文本处理
    sanitize_label,
    clip_err,
    
    # YouTube extractor args
    build_youtube_extractor_args,
    
    # 计划文件名
    build_plan_fixed_fragment,
    build_output_template,
    
    # 时间
    now_ts,
)

print("=" * 60)
print("测试 scripts/common.py 完整功能")
print("=" * 60)

# 1. 环境探测
print("\n[1] 环境探测:")
print(f"  Python: {detect_python()}")
print(f"  默认浏览器: {detect_cookies_browser()}")
print(f"  所有浏览器: {detect_all_browsers()}")
print(f"  JS 运行时: {detect_js_runtime()}")
print(f"  ffmpeg: {which('ffmpeg')}")
print(f"  ffprobe: {which('ffprobe')}")

# 2. yt-dlp 探测
print("\n[2] yt-dlp 探测:")
cmd = ensure_ytdlp_installed(auto_install=False)
if cmd:
    print(f"  命令: {cmd}")
    print(f"  版本: {get_ytdlp_version(cmd)}")
    print(f"  显示: {get_ytdlp_cmd_display(cmd)}")
    print(f"  来源: {detect_ytdlp_source(cmd)}")
else:
    print("  yt-dlp 未安装")

# 3. URL 处理
print("\n[3] URL 处理:")
test_urls = [
    "https://www.youtube.com/watch?v=BhNImM1N6vM",
    "https://youtu.be/BhNImM1N6vM",
    "https://www.youtube.com/shorts/BhNImM1N6vM",
    "https://www.youtube.com/live/BhNImM1N6vM",
    "https://example.com/video",
]
for url in test_urls:
    is_yt = is_youtube_url(url)
    vid = youtube_video_id_from_url(url)
    cache_key = cache_key_for_url(url)
    print(f"  {url}")
    print(f"    → YouTube: {is_yt}, ID: {vid}, 缓存键: {cache_key}")

# 4. JSON 操作
print("\n[4] JSON 操作:")
test_dir = Path("test_tmp")
test_dir.mkdir(exist_ok=True)

test_json = test_dir / "test.json"
test_data = {"foo": "bar", "count": 42}
save_json(test_json, test_data)
loaded = load_json(test_json, {})
print(f"  保存并读取 JSON: {loaded}")

test_jsonl = test_dir / "test.jsonl"
append_jsonl(test_jsonl, {"event": "test1", "ts": now_ts()})
append_jsonl(test_jsonl, {"event": "test2", "ts": now_ts()})
lines = test_jsonl.read_text().strip().split("\n")
print(f"  追加 JSONL 行数: {len(lines)}")

# 清理测试文件
import shutil
shutil.rmtree(test_dir)

# 5. 文本处理
print("\n[5] 文本处理:")
test_labels = [
    "client+web",
    "format/best",
    "codec:vp9",
    "特殊字符@#$%",
    "  spaces  ",
]
for label in test_labels:
    sanitized = sanitize_label(label)
    print(f"  '{label}' → '{sanitized}'")

long_err = "X" * 1500
clipped = clip_err(long_err, 100)
print(f"  裁剪错误信息: {len(long_err)} → {len(clipped)} 字符")

# 6. YouTube extractor args
print("\n[6] YouTube extractor args:")
tokens_data = {
    "youtube": {
        "visitor_data": "test_visitor_data",
        "po_token": "test_po_token",
        "token_client": "web",
    }
}
args1 = build_youtube_extractor_args("web", tokens_data)
print(f"  带 token: {args1}")
args2 = build_youtube_extractor_args("android", None)
print(f"  仅 client: {args2}")
args3 = build_youtube_extractor_args(None, None)
print(f"  无参数: {args3}")

# 7. 计划文件名
print("\n[7] 计划文件名:")
test_plan = {
    "id": "BhNImM1N6vM",
    "yt_client": "web",
    "mode": "single",
    "format_expr": "bestvideo+bestaudio",
    "height": 1080,
}
fragment = build_plan_fixed_fragment(test_plan)
template = build_output_template(test_plan)
print(f"  固定片段: {fragment}")
print(f"  输出模板: {template}")

print("\n" + "=" * 60)
print("✅ 所有测试完成！")
print("=" * 60)
