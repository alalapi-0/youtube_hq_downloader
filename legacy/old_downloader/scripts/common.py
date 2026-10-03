#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# =========================
# 基础路径与目录
# =========================

def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


def project_paths(script_file: str | Path) -> Dict[str, Path]:
    script_dir = Path(script_file).resolve().parent
    project_root = script_dir.parent
    state_dir = project_root / "state"
    downloads_dir = project_root / "downloads"

    return {
        "script_dir": script_dir,
        "project_root": project_root,
        "state_dir": state_dir,
        "downloads_dir": downloads_dir,
        "locks_dir": state_dir / "locks",
        "env_state_file": state_dir / "env_state.json",
        "tokens_file": state_dir / "tokens.json",
        "plan_cache_file": state_dir / "plan_cache.json",
        "failed_jobs_file": state_dir / "failed_jobs.json",
        "run_log_file": state_dir / "run_log.jsonl",
        "urls_file": project_root / "urls.txt",
    }


# =========================
# 默认状态模板
# =========================

def default_env_state() -> Dict[str, Any]:
    return {
        "updated_at": 0,
        "ytdlp": {
            "cmd": [],
            "version": "",
            "source": "",
            "ok": False,
        },
        "ffmpeg": {
            "path": "",
            "ok": False,
        },
        "ffprobe": {
            "path": "",
            "ok": False,
        },
        "js_runtime": {
            "name": "",
            "ok": False,
        },
        "browser": {
            "cookies_browser": "",
            "detected": [],
        },
    }


def default_tokens_data() -> Dict[str, Any]:
    return {
        "updated_at": 0,
        "youtube": {
            "visitor_data": "",
            "po_token": "",
            "token_client": "web",
            "source": "manual",
            "expires_hint_seconds": 3600,
        },
    }


def default_failed_jobs() -> Dict[str, Any]:
    return {}


def ensure_standard_state_files(paths: Dict[str, Path], need_downloads_dir: bool = False) -> None:
    ensure_dir(paths["state_dir"])
    ensure_dir(paths["locks_dir"])

    if need_downloads_dir:
        ensure_dir(paths["downloads_dir"])

    if not paths["env_state_file"].exists():
        save_json(paths["env_state_file"], default_env_state())

    if not paths["tokens_file"].exists():
        save_json(paths["tokens_file"], default_tokens_data())

    if not paths["plan_cache_file"].exists():
        save_json(paths["plan_cache_file"], {})

    if not paths["failed_jobs_file"].exists():
        save_json(paths["failed_jobs_file"], default_failed_jobs())

    if not paths["run_log_file"].exists():
        paths["run_log_file"].touch()


# =========================
# JSON / JSONL
# =========================

def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        text = path.read_text(encoding="utf-8")
        obj = json.loads(text)
        return obj
    except Exception:
        return default


def load_json_dict(path: Path, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if default is None:
        default = {}
    obj = load_json(path, default)
    return obj if isinstance(obj, dict) else dict(default)


def save_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def log_event(log_path: Path, script_name: str, level: str, event: str, **kwargs: Any) -> None:
    obj = {
        "ts": now_ts(),
        "script": script_name,
        "level": level,
        "event": event,
    }
    obj.update(kwargs)
    append_jsonl(log_path, obj)


# =========================
# 时间
# =========================

def now_ts() -> int:
    return int(time.time())


# =========================
# 文本与读取
# =========================

def read_urls(path: Path) -> List[str]:
    if not path.exists():
        return []
    urls: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        urls.append(s)
    return urls


def sanitize_label(text: str) -> str:
    s = text.strip()
    s = s.replace("+", "_plus_")
    s = s.replace("/", "_")
    s = s.replace("\\", "_")
    s = s.replace(":", "_")
    s = re.sub(r"[^0-9A-Za-z._-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "na"


def clip_err(msg: str, n: int = 1200) -> str:
    msg = (msg or "").strip()
    if len(msg) <= n:
        return msg
    return msg[:n] + " ..."


# =========================
# 类型转换
# =========================

def to_int(v: Any, default: int = 0) -> int:
    try:
        return int(v) if v is not None else default
    except Exception:
        return default


def to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except Exception:
        return default


def safe_json_load(text: str) -> Optional[Dict[str, Any]]:
    s = text.strip()
    if not s:
        return None

    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(s[start:end + 1])
            if isinstance(obj, dict):
                return obj
        except Exception:
            return None
    return None


# =========================
# 命令与环境探测
# =========================

def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def detect_python() -> str:
    return sys.executable or "python3"


def run_capture_raw(cmd: List[str]) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return p.returncode, p.stdout or "", p.stderr or ""
    except Exception as e:
        return 1, "", str(e)


def run_stream(cmd: List[str], stall_seconds: int = 90) -> Tuple[int, str, bool]:
    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    assert p.stdout is not None

    last_ts = time.time()
    buf: List[str] = []
    stalled = False

    while True:
        line = p.stdout.readline()
        if line:
            print(line, end="")
            buf.append(line)
            last_ts = time.time()
        else:
            if p.poll() is not None:
                break
            if (time.time() - last_ts) >= stall_seconds and not stalled:
                stalled = True
                print(f"\n[Warn] {stall_seconds}s 没有新输出，疑似卡住")
            time.sleep(0.2)

    rc = p.wait()
    return rc, "".join(buf), stalled


def python_module_ytdlp_cmd() -> Optional[List[str]]:
    py = detect_python()
    rc, out, err = run_capture_raw([py, "-m", "yt_dlp", "--version"])
    if rc == 0:
        return [py, "-m", "yt_dlp"]
    return None


def path_ytdlp_cmd() -> Optional[List[str]]:
    exe = which("yt-dlp")
    if exe:
        return [exe]
    return None


def brew_ytdlp_cmd() -> Optional[List[str]]:
    for p in ["/opt/homebrew/bin/yt-dlp", "/usr/local/bin/yt-dlp"]:
        if Path(p).exists():
            return [p]
    return None


def ensure_ytdlp_installed(auto_install: bool = True) -> Optional[List[str]]:
    cmd = python_module_ytdlp_cmd() or path_ytdlp_cmd() or brew_ytdlp_cmd()
    if cmd:
        return cmd

    if not auto_install:
        return None

    # Linux dependencies belong to the explicitly prepared project environment.
    if sys.platform.startswith("linux"):
        return None

    py = detect_python()

    if which("brew"):
        subprocess.run(["brew", "install", "yt-dlp"], check=False)

    subprocess.run([py, "-m", "pip", "install", "--user", "-U", "yt-dlp"], check=False)

    return python_module_ytdlp_cmd() or path_ytdlp_cmd() or brew_ytdlp_cmd()


def get_ytdlp_version(ytdlp_cmd: List[str]) -> str:
    rc, out, err = run_capture_raw(ytdlp_cmd + ["--version"])
    if rc == 0:
        return out.strip()
    return "unknown"


def get_ytdlp_cmd_display(ytdlp_cmd: List[str]) -> str:
    return " ".join(ytdlp_cmd)


def detect_ytdlp_source(ytdlp_cmd: List[str]) -> str:
    first = ytdlp_cmd[0]
    py = detect_python()

    if first == py and len(ytdlp_cmd) >= 3 and ytdlp_cmd[1:3] == ["-m", "yt_dlp"]:
        return "python-module"
    if first in ("/opt/homebrew/bin/yt-dlp", "/usr/local/bin/yt-dlp"):
        return "brew"
    if ".pyenv/" in first:
        return "pyenv-exe"
    return "path-exe"


def browser_profile_paths() -> Dict[str, Path]:
    home = Path.home()
    if sys.platform.startswith("linux"):
        config = home / ".config"
        return {
            "chrome": config / "google-chrome",
            "brave": config / "BraveSoftware/Brave-Browser",
            "chromium": config / "chromium",
            "edge": config / "microsoft-edge",
            "firefox": home / ".mozilla/firefox",
        }
    return {
        "chrome": home / "Library/Application Support/Google/Chrome",
        "brave": home / "Library/Application Support/BraveSoftware/Brave-Browser",
        "chromium": home / "Library/Application Support/Chromium",
        "edge": home / "Library/Application Support/Microsoft Edge",
        "firefox": home / "Library/Application Support/Firefox",
    }


def detect_cookies_browser() -> Optional[str]:
    return next(iter(detect_all_browsers()), None)


def detect_all_browsers() -> List[str]:
    # Presence only; credentials are never opened by detection.
    return [name for name, path in browser_profile_paths().items() if path.exists()]


def detect_js_runtime() -> str:
    for cmd in ["node", "deno", "bun"]:
        if which(cmd):
            return cmd
    return "auto"


def ensure_ffmpeg_and_ffprobe(auto_install: bool = True) -> bool:
    ffmpeg_ok = which("ffmpeg") is not None
    ffprobe_ok = which("ffprobe") is not None
    if ffmpeg_ok and ffprobe_ok:
        return True

    if not auto_install or sys.platform.startswith("linux"):
        return False

    if which("brew"):
        subprocess.run(["brew", "install", "ffmpeg"], check=False)

    return which("ffmpeg") is not None and which("ffprobe") is not None


# =========================
# URL / cache key
# =========================

YOUTUBE_ID_PATTERNS = [
    r"[?&]v=([A-Za-z0-9_-]{11})",
    r"youtu\.be/([A-Za-z0-9_-]{11})",
    r"youtube\.com/shorts/([A-Za-z0-9_-]{11})",
    r"youtube\.com/live/([A-Za-z0-9_-]{11})",
    r"youtube\.com/embed/([A-Za-z0-9_-]{11})",
]


def is_youtube_url(url: str) -> bool:
    s = url.lower()
    return (
        "youtube.com/watch" in s
        or "youtube.com/shorts/" in s
        or "youtube.com/live/" in s
        or "youtu.be/" in s
        or "youtube.com/embed/" in s
    )


def youtube_video_id_from_url(url: str) -> Optional[str]:
    for pattern in YOUTUBE_ID_PATTERNS:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return None


def cache_key_for_url(url: str) -> str:
    vid = youtube_video_id_from_url(url)
    if vid:
        return f"youtube:{vid}"
    return url


# =========================
# ffprobe / 视频校验
# =========================

def ffprobe_video_info(path: Path) -> Optional[Dict[str, Any]]:
    ffprobe = which("ffprobe")
    if not ffprobe:
        return None

    cmd = [
        ffprobe,
        "-v", "error",
        "-print_format", "json",
        "-show_entries", "stream=index,codec_type,codec_name,width,height,r_frame_rate",
        "-show_entries", "format=size,duration",
        str(path),
    ]
    rc, out, err = run_capture_raw(cmd)
    if rc != 0:
        return None

    obj = safe_json_load(out)
    if not obj:
        return None

    streams = obj.get("streams") or []
    fmt = obj.get("format") or {}

    video_stream = None
    for s in streams:
        if isinstance(s, dict) and s.get("codec_type") == "video":
            video_stream = s
            break

    if not isinstance(video_stream, dict):
        return None

    width = to_int(video_stream.get("width"))
    height = to_int(video_stream.get("height"))
    codec = str(video_stream.get("codec_name") or "unknown")
    r_frame_rate = str(video_stream.get("r_frame_rate") or "0/0")

    fps = 0.0
    if "/" in r_frame_rate:
        a, b = r_frame_rate.split("/", 1)
        try:
            a_f = float(a)
            b_f = float(b)
            if b_f != 0:
                fps = a_f / b_f
        except Exception:
            fps = 0.0

    return {
        "width": width,
        "height": height,
        "codec": codec,
        "fps": fps,
        "size_bytes": to_int(fmt.get("size")),
        "duration": to_float(fmt.get("duration")),
    }


def validate_downloaded_file(path: Path, required_height: int) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    info = ffprobe_video_info(path)
    if not info:
        return False, "ffprobe 无法读取视频信息", None

    actual_height = to_int(info.get("height"))
    if actual_height < required_height:
        return False, f"实际分辨率 {actual_height}p，低于要求 {required_height}p", info

    return True, f"实际分辨率 {actual_height}p，符合要求", info


# =========================
# token 解析与优先级
# =========================

def _normalize_youtube_tokens(youtube_tokens: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "visitor_data": str(youtube_tokens.get("visitor_data") or "").strip(),
        "po_token": str(youtube_tokens.get("po_token") or "").strip(),
        "token_client": str(youtube_tokens.get("token_client") or "web").strip() or "web",
        "source": str(youtube_tokens.get("source") or "manual").strip() or "manual",
        "expires_hint_seconds": to_int(youtube_tokens.get("expires_hint_seconds"), 3600),
    }


def get_env_youtube_tokens() -> Dict[str, Any]:
    visitor_data = os.getenv("YT_VISITOR_DATA", "").strip()
    po_token = os.getenv("YT_PO_TOKEN", "").strip()
    token_client = os.getenv("YT_TOKEN_CLIENT", "web").strip() or "web"

    return {
        "visitor_data": visitor_data,
        "po_token": po_token,
        "token_client": token_client,
        "source": "env",
        "expires_hint_seconds": 3600,
    }


def effective_tokens_data(file_tokens_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    base = default_tokens_data()
    file_tokens_data = file_tokens_data or {}

    file_yt = file_tokens_data.get("youtube") if isinstance(file_tokens_data, dict) else {}
    if not isinstance(file_yt, dict):
        file_yt = {}

    file_norm = _normalize_youtube_tokens(file_yt)
    env_norm = get_env_youtube_tokens()

    visitor_data = env_norm["visitor_data"] or file_norm["visitor_data"]
    po_token = env_norm["po_token"] or file_norm["po_token"]
    token_client = env_norm["token_client"] if (env_norm["visitor_data"] or env_norm["po_token"]) else file_norm["token_client"]

    source = "none"
    if env_norm["visitor_data"] or env_norm["po_token"]:
        source = "env"
    elif file_norm["visitor_data"] or file_norm["po_token"]:
        source = file_norm["source"] or "file"

    base["updated_at"] = to_int(file_tokens_data.get("updated_at"), 0) if isinstance(file_tokens_data, dict) else 0
    base["youtube"] = {
        "visitor_data": visitor_data,
        "po_token": po_token,
        "token_client": token_client or "web",
        "source": source,
        "expires_hint_seconds": file_norm["expires_hint_seconds"],
    }
    return base


def token_runtime_summary(tokens_data: Dict[str, Any]) -> Dict[str, Any]:
    yt = tokens_data.get("youtube") if isinstance(tokens_data, dict) else {}
    if not isinstance(yt, dict):
        yt = {}
    return {
        "visitor_data_set": bool(str(yt.get("visitor_data") or "").strip()),
        "po_token_set": bool(str(yt.get("po_token") or "").strip()),
        "token_client": str(yt.get("token_client") or "web").strip() or "web",
        "token_source": str(yt.get("source") or "none").strip() or "none",
    }


# =========================
# YouTube extractor args
# =========================

def build_youtube_extractor_args(
    yt_client: Optional[str],
    tokens_data: Optional[Dict[str, Any]] = None,
    extra_args: Optional[List[str]] = None,
) -> Optional[str]:
    parts: List[str] = []

    tokens_data = effective_tokens_data(tokens_data)
    youtube_tokens = tokens_data.get("youtube") if isinstance(tokens_data, dict) else {}
    if not isinstance(youtube_tokens, dict):
        youtube_tokens = {}

    visitor_data = str(youtube_tokens.get("visitor_data") or "").strip()
    po_token = str(youtube_tokens.get("po_token") or "").strip()
    token_client = str(youtube_tokens.get("token_client") or "web").strip() or "web"

    effective_client = yt_client
    if po_token and not effective_client:
        effective_client = token_client

    if effective_client:
        parts.append(f"player_client={effective_client}")

    if visitor_data:
        parts.append(f"visitor_data={visitor_data}")

    if po_token:
        parts.append(f"po_token={(effective_client or token_client)}.gvs+{po_token}")

    for extra in (extra_args or []):
        e = str(extra).strip()
        if e:
            parts.append(e)

    if not parts:
        return None

    return "youtube:" + ";".join(parts)


# =========================
# 计划文件名辅助
# =========================

def build_plan_fixed_fragment(plan: Dict[str, Any]) -> str:
    vid_id = str(plan.get("id") or "unknown")
    client_label = sanitize_label("auto" if plan.get("yt_client") is None else str(plan.get("yt_client")))
    mode_label = sanitize_label(str(plan.get("mode") or "unknown"))
    fmt_label = sanitize_label(str(plan.get("format_expr") or "na"))
    height_label = f"{to_int(plan.get('height'))}p"

    return f"[{vid_id}] [client-{client_label}] [{height_label}] [{mode_label}-{fmt_label}]"


def build_output_template(plan: Dict[str, Any]) -> str:
    return f"%(title)s {build_plan_fixed_fragment(plan)}.%(ext)s"


# =========================
# plan 状态辅助
# =========================

PLAN_STATUS_USABLE = "usable"
PLAN_STATUS_SUSPECTED_EXPIRED = "suspected_expired"
PLAN_STATUS_INVALID = "invalid"


def plan_status(plan: Dict[str, Any]) -> str:
    return str(plan.get("status") or PLAN_STATUS_USABLE)


def plan_is_fresh(plan: Dict[str, Any], ttl_seconds: int) -> bool:
    if ttl_seconds <= 0:
        return True

    base_ts = to_int(plan.get("last_verified_at")) or to_int(plan.get("cached_at"))
    if base_ts <= 0:
        return False

    return (now_ts() - base_ts) <= ttl_seconds


def plan_is_usable(plan: Dict[str, Any], min_height: int, ttl_seconds: int) -> bool:
    status = plan_status(plan)
    height = to_int(plan.get("height"))
    if status != PLAN_STATUS_USABLE:
        return False
    if height < min_height:
        return False
    return plan_is_fresh(plan, ttl_seconds)


def touch_plan_verified(plan: Dict[str, Any]) -> Dict[str, Any]:
    plan["last_verified_at"] = now_ts()
    plan["status"] = PLAN_STATUS_USABLE
    plan["last_error"] = ""
    return plan


def mark_plan_status(plan: Dict[str, Any], status: str, reason: str = "") -> Dict[str, Any]:
    plan["status"] = status
    plan["last_error"] = reason
    plan["last_status_at"] = now_ts()
    return plan
