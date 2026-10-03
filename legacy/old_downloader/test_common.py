from pathlib import Path
from scripts.common import (
    detect_python,
    detect_cookies_browser,
    detect_js_runtime,
    ensure_ytdlp_installed,
    get_ytdlp_version,
    get_ytdlp_cmd_display,
    detect_ytdlp_source,
    cache_key_for_url,
    youtube_video_id_from_url,
)

print("python:", detect_python())
print("browser:", detect_cookies_browser())
print("js runtime:", detect_js_runtime())

cmd = ensure_ytdlp_installed(auto_install=False)
print("ytdlp cmd:", cmd)
if cmd:
    print("ytdlp version:", get_ytdlp_version(cmd))
    print("ytdlp display:", get_ytdlp_cmd_display(cmd))
    print("ytdlp source:", detect_ytdlp_source(cmd))

url = "https://www.youtube.com/watch?v=BhNImM1N6vM"
print("video id:", youtube_video_id_from_url(url))
print("cache key:", cache_key_for_url(url))
