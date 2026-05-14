#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common.py — 公共工具模块

这个文件是整个项目的「工具箱」，所有其他脚本都会从这里导入需要的工具函数。
它本身不执行任何下载操作，只提供通用的基础功能：
  - 文件路径管理
  - JSON/JSONL 文件读写
  - 工具软件检测（yt-dlp、ffmpeg、浏览器等）
  - URL 解析与缓存键生成
  - Token（令牌）管理
  - 下载计划状态管理
  - 视频文件验证
"""

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


# ===========================================================================
# 第一部分：路径与目录管理
# ===========================================================================

def ensure_dir(path: Path) -> Path:
    """
    确保目录存在，如果不存在则自动创建（包括所有上级目录）。
    
    参数：
        path: 要创建的目录路径
    返回：
        传入的 path（方便链式调用）
    
    示例：
        ensure_dir(Path("state/locks"))  # 如不存在，自动创建 state/locks/ 目录
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_unlink(path: Path) -> None:
    """
    安全删除文件，如果文件不存在或删除失败则静默忽略（不报错）。
    
    参数：
        path: 要删除的文件路径
    """
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


def project_paths(script_file: str | Path) -> Dict[str, Path]:
    """
    根据任意脚本文件的路径，自动推算整个项目的目录结构和各状态文件路径。
    
    项目目录结构：
        youtube_hq_downloader/        ← project_root（项目根目录）
          ├── scripts/                ← script_dir（脚本目录，传入脚本所在位置）
          ├── state/                  ← 状态文件目录
          │   ├── env_state.json      ← 环境信息缓存
          │   ├── tokens.json         ← YouTube Token 存储
          │   ├── plan_cache.json     ← 视频下载计划缓存
          │   ├── failed_jobs.json    ← 失败记录
          │   ├── run_log.jsonl       ← 运行日志
          │   └── locks/             ← 锁文件目录（防止重复运行）
          ├── downloads/              ← 视频下载目标目录
          └── urls.txt               ← 待下载的 URL 列表
    
    参数：
        script_file: 调用此函数的脚本文件路径（通常传入 __file__）
    返回：
        包含所有关键路径的字典
    """
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


# ===========================================================================
# 第二部分：默认状态数据模板
# ===========================================================================

def default_env_state() -> Dict[str, Any]:
    """
    返回 env_state.json 的默认空模板。
    
    env_state.json 保存本机工具环境的探测结果，避免每次运行都重新检测：
      - ytdlp: yt-dlp 工具的路径、版本、安装方式
      - ffmpeg/ffprobe: 视频合并工具路径
      - js_runtime: JavaScript 运行时（node/deno/bun），yt-dlp 处理 Token 时需要
      - browser: 可用于提供 cookies 的浏览器名称
    """
    return {
        "updated_at": 0,       # 最后更新时间戳（Unix 时间）
        "ytdlp": {
            "cmd": [],         # yt-dlp 命令（如 ["python3", "-m", "yt_dlp"]）
            "version": "",     # yt-dlp 版本号
            "source": "",      # 安装来源（brew / python-module / path-exe 等）
            "ok": False,       # 是否可用
        },
        "ffmpeg": {
            "path": "",        # ffmpeg 可执行文件路径
            "ok": False,
        },
        "ffprobe": {
            "path": "",        # ffprobe 可执行文件路径（用于验证已下载文件的分辨率）
            "ok": False,
        },
        "js_runtime": {
            "name": "",        # JS 运行时名称（node / deno / bun），找不到时为 "auto"
            "ok": False,
        },
        "browser": {
            "cookies_browser": "",   # 首选浏览器名称（如 "chrome"）
            "detected": [],          # 本机检测到的所有浏览器列表
        },
    }


def default_tokens_data() -> Dict[str, Any]:
    """
    返回 tokens.json 的默认空模板。
    
    tokens.json 保存 YouTube 身份令牌，用于解锁 4K 等高画质下载。
    这些 Token 相当于「会员身份证」，YouTube 凭此判断是否给你高清视频链接。
    
    字段说明：
      - visitor_data: YouTube 访客标识（相当于「设备ID」）
      - po_token: 播放 Token（用于验证你是真实浏览器用户，非机器人）
      - token_client: Token 对应的客户端类型（默认 "web"）
      - source: Token 来源（"manual" 手动设置 / "env" 环境变量 / "browser" 浏览器抓取）
      - expires_hint_seconds: Token 预计有效期（秒）
    """
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
    """返回 failed_jobs.json 的默认空模板（空字典）。"""
    return {}


def ensure_standard_state_files(paths: Dict[str, Path], need_downloads_dir: bool = False) -> None:
    """
    确保所有状态文件和目录都存在，首次运行时自动初始化。
    
    这个函数在每个主脚本启动时调用，确保 state/ 目录和所有 JSON 文件都已创建，
    防止因文件不存在而导致读取报错。
    
    参数：
        paths: 由 project_paths() 返回的路径字典
        need_downloads_dir: 是否同时创建 downloads/ 目录（下载脚本需要传 True）
    """
    # 创建状态目录和锁文件目录
    ensure_dir(paths["state_dir"])
    ensure_dir(paths["locks_dir"])

    # 如果需要，创建下载目录
    if need_downloads_dir:
        ensure_dir(paths["downloads_dir"])

    # 如果各状态文件不存在，用默认模板初始化
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


# ===========================================================================
# 第三部分：JSON / JSONL 文件读写
# ===========================================================================

def load_json(path: Path, default: Any) -> Any:
    """
    读取 JSON 文件，如果文件不存在或内容无法解析则返回默认值。
    
    参数：
        path: JSON 文件路径
        default: 文件不存在或解析失败时返回的默认值
    返回：
        解析后的 Python 对象，或 default
    """
    if not path.exists():
        return default
    try:
        text = path.read_text(encoding="utf-8")
        obj = json.loads(text)
        return obj
    except Exception:
        return default


def load_json_dict(path: Path, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    读取 JSON 文件并确保返回值是字典类型。
    如果文件内容不是字典（例如是列表），则返回 default。
    
    参数：
        path: JSON 文件路径
        default: 默认字典，不传则为空字典 {}
    返回：
        字典类型的解析结果
    """
    if default is None:
        default = {}
    obj = load_json(path, default)
    return obj if isinstance(obj, dict) else dict(default)


def save_json(path: Path, data: Any) -> None:
    """
    将 Python 对象序列化为 JSON 并写入文件（格式化缩进，支持中文）。
    写入前会自动创建父目录。
    
    参数：
        path: 目标文件路径
        data: 要写入的 Python 对象（字典、列表等）
    """
    ensure_dir(path.parent)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    """
    向 JSONL 文件追加一条记录（每行一个 JSON 对象）。
    JSONL（JSON Lines）格式适合追加写入日志。
    
    参数：
        path: JSONL 文件路径
        obj: 要追加的字典
    """
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def log_event(log_path: Path, script_name: str, level: str, event: str, **kwargs: Any) -> None:
    """
    向运行日志（run_log.jsonl）追加一条事件记录。
    
    日志格式：{"ts": 时间戳, "script": 脚本名, "level": 级别, "event": 事件名, ...其他字段}
    
    参数：
        log_path: 日志文件路径（run_log.jsonl）
        script_name: 产生日志的脚本名（如 "probe_best_plan"）
        level: 日志级别（"info" / "warn" / "error"）
        event: 事件标识（如 "probe_start" / "download_success"）
        **kwargs: 额外的键值对，附加到日志记录中
    """
    obj = {
        "ts": now_ts(),
        "script": script_name,
        "level": level,
        "event": event,
    }
    obj.update(kwargs)
    append_jsonl(log_path, obj)


# ===========================================================================
# 第四部分：时间工具
# ===========================================================================

def now_ts() -> int:
    """
    返回当前 Unix 时间戳（整数，单位：秒）。
    用于记录文件创建/更新时间、计算缓存是否过期等。
    """
    return int(time.time())


# ===========================================================================
# 第五部分：文本处理工具
# ===========================================================================

def read_urls(path: Path) -> List[str]:
    """
    读取 urls.txt 文件，返回所有有效 URL 列表。
    
    文件格式规则：
      - 每行一条 URL
      - 以 # 开头的行视为注释，自动跳过
      - 空行自动跳过
    
    参数：
        path: urls.txt 文件路径
    返回：
        有效 URL 的列表（保持原始顺序）
    """
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
    """
    将任意文字清理为只含安全字符的标签，用于文件名片段。
    
    处理规则：
      - + 替换为 _plus_（保留格式表达式的可读性，如 "313+251" → "313_plus_251"）
      - / \ : 替换为 _
      - 其他非字母数字字符替换为 _
      - 合并连续的 _，去除首尾 _
    
    示例：
        sanitize_label("313+251") → "313_plus_251"
        sanitize_label("auto/web") → "auto_web"
    """
    s = text.strip()
    s = s.replace("+", "_plus_")
    s = s.replace("/", "_")
    s = s.replace("\\", "_")
    s = s.replace(":", "_")
    s = re.sub(r"[^0-9A-Za-z._-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "na"


def clip_err(msg: str, n: int = 1200) -> str:
    """
    截断过长的错误信息，避免日志文件过大。
    
    参数：
        msg: 原始错误信息字符串
        n: 最大保留长度（默认 1200 字符）
    返回：
        截断后的字符串（超出部分替换为 " ..."）
    """
    msg = (msg or "").strip()
    if len(msg) <= n:
        return msg
    return msg[:n] + " ..."


# ===========================================================================
# 第六部分：类型转换工具
# ===========================================================================

def to_int(v: Any, default: int = 0) -> int:
    """
    安全地将任意值转换为整数，转换失败时返回默认值（不抛异常）。
    
    示例：
        to_int("2160") → 2160
        to_int(None)   → 0
        to_int("abc")  → 0
    """
    try:
        return int(v) if v is not None else default
    except Exception:
        return default


def to_float(v: Any, default: float = 0.0) -> float:
    """
    安全地将任意值转换为浮点数，转换失败时返回默认值（不抛异常）。
    
    示例：
        to_float("29.97") → 29.97
        to_float(None)    → 0.0
    """
    try:
        return float(v) if v is not None else default
    except Exception:
        return default


def safe_json_load(text: str) -> Optional[Dict[str, Any]]:
    """
    从字符串中安全解析 JSON 字典。
    
    处理两种情况：
      1. 整个字符串就是合法 JSON
      2. 字符串中嵌入了 JSON（如 yt-dlp 输出中混有调试信息），
         尝试提取 { ... } 部分来解析
    
    参数：
        text: 包含 JSON 内容的字符串
    返回：
        解析成功返回字典，失败返回 None
    """
    s = text.strip()
    if not s:
        return None

    # 尝试直接解析
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # 尝试从字符串中提取 { ... } 部分
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


# ===========================================================================
# 第七部分：工具软件检测与安装
# ===========================================================================

def which(cmd: str) -> Optional[str]:
    """
    查找命令的完整路径（相当于 Shell 中的 which 命令）。
    
    参数：
        cmd: 命令名（如 "ffmpeg"、"node"）
    返回：
        找到则返回完整路径（如 "/usr/local/bin/ffmpeg"），找不到返回 None
    """
    return shutil.which(cmd)


def detect_python() -> str:
    """
    返回当前 Python 解释器的完整路径。
    优先使用运行当前脚本的解释器（确保虚拟环境一致性）。
    """
    return sys.executable or "python3"


def run_capture_raw(cmd: List[str]) -> Tuple[int, str, str]:
    """
    执行命令并捕获其输出（不在终端显示）。
    
    用于需要读取命令输出结果的场景（如 yt-dlp --dump-single-json 获取视频信息）。
    
    参数：
        cmd: 命令和参数列表（如 ["yt-dlp", "--version"]）
    返回：
        (退出码, 标准输出内容, 标准错误内容)
        退出码为 0 表示成功，非 0 表示失败
    """
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
    """
    执行命令并实时将输出打印到终端（流式输出）。
    
    用于下载场景，让用户能实时看到下载进度。
    内置卡顿检测：如果超过 stall_seconds 秒没有新输出，打印警告。
    
    参数：
        cmd: 命令和参数列表
        stall_seconds: 判定「卡住」的无输出等待时间（秒，默认 90 秒）
    返回：
        (退出码, 所有输出合并字符串, 是否曾经卡住)
    """
    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,   # 将标准错误合并到标准输出，统一展示
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,                  # 行缓冲，确保实时输出
    )

    assert p.stdout is not None

    last_ts = time.time()
    buf: List[str] = []
    stalled = False

    while True:
        line = p.stdout.readline()
        if line:
            print(line, end="")     # 实时打印到终端
            buf.append(line)
            last_ts = time.time()
        else:
            if p.poll() is not None:    # 进程已结束
                break
            if (time.time() - last_ts) >= stall_seconds and not stalled:
                stalled = True
                print(f"\n[Warn] {stall_seconds}s 没有新输出，疑似卡住")
            time.sleep(0.2)

    rc = p.wait()
    return rc, "".join(buf), stalled


def python_module_ytdlp_cmd() -> Optional[List[str]]:
    """
    尝试以 Python 模块方式调用 yt-dlp（python3 -m yt_dlp）。
    这种方式与当前 Python 环境（虚拟环境）完全一致，优先推荐。
    """
    py = detect_python()
    rc, out, err = run_capture_raw([py, "-m", "yt_dlp", "--version"])
    if rc == 0:
        return [py, "-m", "yt_dlp"]
    return None


def path_ytdlp_cmd() -> Optional[List[str]]:
    """
    尝试在系统 PATH 中查找 yt-dlp 可执行文件。
    """
    exe = which("yt-dlp")
    if exe:
        return [exe]
    return None


def brew_ytdlp_cmd() -> Optional[List[str]]:
    """
    尝试在 Homebrew 常见安装路径查找 yt-dlp（macOS 用户常用方式）。
    """
    for p in ["/opt/homebrew/bin/yt-dlp", "/usr/local/bin/yt-dlp"]:
        if Path(p).exists():
            return [p]
    return None


def ensure_ytdlp_installed(auto_install: bool = True) -> Optional[List[str]]:
    """
    检测 yt-dlp 是否已安装，未安装时可自动尝试安装。
    
    检测优先级：
      1. Python 模块方式（python3 -m yt_dlp）
      2. PATH 中的可执行文件
      3. Homebrew 安装路径（macOS）
    
    参数：
        auto_install: 是否在找不到时自动安装（True：自动安装，False：直接返回 None）
    返回：
        yt-dlp 命令列表，找不到返回 None
    """
    cmd = python_module_ytdlp_cmd() or path_ytdlp_cmd() or brew_ytdlp_cmd()
    if cmd:
        return cmd

    if not auto_install:
        return None

    py = detect_python()

    # 尝试通过 Homebrew 安装（macOS）
    if which("brew"):
        subprocess.run(["brew", "install", "yt-dlp"], check=False)

    # 尝试通过 pip 安装
    subprocess.run([py, "-m", "pip", "install", "--user", "-U", "yt-dlp"], check=False)

    return python_module_ytdlp_cmd() or path_ytdlp_cmd() or brew_ytdlp_cmd()


def get_ytdlp_version(ytdlp_cmd: List[str]) -> str:
    """
    获取 yt-dlp 版本号字符串。
    
    参数：
        ytdlp_cmd: yt-dlp 命令列表（由 ensure_ytdlp_installed 返回）
    返回：
        版本号字符串（如 "2024.01.01"），获取失败返回 "unknown"
    """
    rc, out, err = run_capture_raw(ytdlp_cmd + ["--version"])
    if rc == 0:
        return out.strip()
    return "unknown"


def get_ytdlp_cmd_display(ytdlp_cmd: List[str]) -> str:
    """
    将 yt-dlp 命令列表转换为可读的字符串，用于日志显示。
    
    示例：["python3", "-m", "yt_dlp"] → "python3 -m yt_dlp"
    """
    return " ".join(ytdlp_cmd)


def detect_ytdlp_source(ytdlp_cmd: List[str]) -> str:
    """
    检测 yt-dlp 的安装来源，用于记录到 env_state.json。
    
    返回值可能为：
      - "python-module": 通过 pip 安装，以 python3 -m yt_dlp 方式调用
      - "brew": 通过 Homebrew 安装
      - "pyenv-exe": 通过 pyenv 管理的 Python 环境
      - "path-exe": 其他方式，从 PATH 中找到的可执行文件
    """
    first = ytdlp_cmd[0]
    py = detect_python()

    if first == py and len(ytdlp_cmd) >= 3 and ytdlp_cmd[1:3] == ["-m", "yt_dlp"]:
        return "python-module"
    if first in ("/opt/homebrew/bin/yt-dlp", "/usr/local/bin/yt-dlp"):
        return "brew"
    if ".pyenv/" in first:
        return "pyenv-exe"
    return "path-exe"


def detect_cookies_browser() -> Optional[str]:
    """
    检测本机已安装的浏览器，返回第一个找到的浏览器名称。
    
    浏览器 cookies 可以帮助 yt-dlp 通过 YouTube 的登录验证，从而访问更高画质资源。
    检测顺序（优先级从高到低）：chrome > brave > chromium > edge > firefox
    
    当前仅支持 macOS 系统的默认安装路径检测。
    
    返回：
        浏览器名称（如 "chrome"），未检测到任何浏览器返回 None
    """
    home = Path.home()
    # macOS 各浏览器的用户数据目录（存在说明已安装）
    browser_paths = {
        "chrome":   home / "Library/Application Support/Google/Chrome",
        "brave":    home / "Library/Application Support/BraveSoftware/Brave-Browser",
        "chromium": home / "Library/Application Support/Chromium",
        "edge":     home / "Library/Application Support/Microsoft Edge",
        "firefox":  home / "Library/Application Support/Firefox",
    }

    for name in ["chrome", "brave", "chromium", "edge", "firefox"]:
        p = browser_paths.get(name)
        if p and p.exists():
            return name
    return None


def detect_all_browsers() -> List[str]:
    """
    检测本机所有已安装的浏览器，返回名称列表。
    与 detect_cookies_browser 的区别：这里返回全部，而非只返回第一个。
    """
    found: List[str] = []
    home = Path.home()
    browser_paths = {
        "chrome":   home / "Library/Application Support/Google/Chrome",
        "brave":    home / "Library/Application Support/BraveSoftware/Brave-Browser",
        "chromium": home / "Library/Application Support/Chromium",
        "edge":     home / "Library/Application Support/Microsoft Edge",
        "firefox":  home / "Library/Application Support/Firefox",
    }

    for name in ["chrome", "brave", "chromium", "edge", "firefox"]:
        p = browser_paths.get(name)
        if p and p.exists():
            found.append(name)
    return found


def detect_js_runtime() -> str:
    """
    检测本机已安装的 JavaScript 运行时。
    
    yt-dlp 在处理 YouTube 的某些反爬验证时需要 JavaScript 运行时来计算 Token。
    检测顺序：node > deno > bun
    
    返回：
        找到的运行时名称（如 "node"），未找到返回 "auto"（让 yt-dlp 自行处理）
    """
    for cmd in ["node", "deno", "bun"]:
        if which(cmd):
            return cmd
    return "auto"


def ensure_ffmpeg_and_ffprobe(auto_install: bool = True) -> bool:
    """
    检测 ffmpeg 和 ffprobe 是否已安装，未安装时可自动尝试安装。
    
    ffmpeg 用于将视频流和音频流合并为最终文件（adaptive 模式下必需）。
    ffprobe 用于检测已下载文件的实际分辨率，验证是否达到 4K 标准。
    
    参数：
        auto_install: 是否自动安装（仅支持通过 Homebrew 安装）
    返回：
        True 表示 ffmpeg 和 ffprobe 均可用，False 表示有缺失
    """
    ffmpeg_ok = which("ffmpeg") is not None
    ffprobe_ok = which("ffprobe") is not None
    if ffmpeg_ok and ffprobe_ok:
        return True

    if not auto_install:
        return False

    # 通过 Homebrew 自动安装（macOS）
    if which("brew"):
        subprocess.run(["brew", "install", "ffmpeg"], check=False)

    return which("ffmpeg") is not None and which("ffprobe") is not None


# ===========================================================================
# 第八部分：URL 解析与缓存键生成
# ===========================================================================

# YouTube 视频 ID 的正则表达式模式（11 位字母数字）
YOUTUBE_ID_PATTERNS = [
    r"[?&]v=([A-Za-z0-9_-]{11})",           # 普通视频：watch?v=xxxxx
    r"youtu\.be/([A-Za-z0-9_-]{11})",        # 短链接：youtu.be/xxxxx
    r"youtube\.com/shorts/([A-Za-z0-9_-]{11})",  # Shorts：/shorts/xxxxx
    r"youtube\.com/live/([A-Za-z0-9_-]{11})",    # 直播：/live/xxxxx
    r"youtube\.com/embed/([A-Za-z0-9_-]{11})",   # 嵌入：/embed/xxxxx
]


def is_youtube_url(url: str) -> bool:
    """
    判断 URL 是否为 YouTube 视频链接。
    
    支持格式：
      - youtube.com/watch?v=...（普通视频）
      - youtube.com/shorts/...（短视频）
      - youtube.com/live/...（直播）
      - youtu.be/...（短链接）
      - youtube.com/embed/...（嵌入）
    """
    s = url.lower()
    return (
        "youtube.com/watch" in s
        or "youtube.com/shorts/" in s
        or "youtube.com/live/" in s
        or "youtu.be/" in s
        or "youtube.com/embed/" in s
    )


def youtube_video_id_from_url(url: str) -> Optional[str]:
    """
    从 YouTube URL 中提取视频 ID（11 位字符串）。
    
    示例：
        "https://www.youtube.com/watch?v=LJkIVzy7DSc" → "LJkIVzy7DSc"
        "https://youtu.be/LJkIVzy7DSc" → "LJkIVzy7DSc"
    
    返回：
        11 位视频 ID，或 None（无法提取时）
    """
    for pattern in YOUTUBE_ID_PATTERNS:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return None



# ===========================================================================
# 第九部分：ffprobe 视频文件验证
# ===========================================================================

def ffprobe_video_info(path: Path) -> Optional[Dict[str, Any]]:
    """
    使用 ffprobe 读取视频文件的基本信息（分辨率、帧率、编码、时长等）。
    
    这个函数在下载完成后用于验证文件是否真的达到了目标分辨率（如 4K/2160p）。
    
    参数：
        path: 视频文件路径
    返回：
        包含视频信息的字典，或 None（ffprobe 不可用或文件无效时）
        字典字段：width（宽度）、height（高度）、codec（编码格式）、
                  fps（帧率）、size_bytes（文件大小）、duration（时长秒数）
    """
    ffprobe = which("ffprobe")
    if not ffprobe:
        return None

    # 调用 ffprobe 以 JSON 格式输出视频流和格式信息
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

    # 从所有流中找到视频流（跳过音频流、字幕流等）
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

    # 解析帧率（格式为 "分子/分母"，如 "30000/1001" 表示约 29.97fps）
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
    """
    验证下载完成的视频文件是否真的达到了要求的分辨率。
    
    用于下载成功后的最终校验：防止下载了「标称4K实为1080p」的情况。
    
    参数：
        path: 已下载视频文件的路径
        required_height: 最低要求的分辨率高度（如 2160 表示 4K）
    返回：
        (是否达标, 描述信息, 视频详细信息字典或None)
    """
    info = ffprobe_video_info(path)
    if not info:
        return False, "ffprobe 无法读取视频信息", None

    actual_height = to_int(info.get("height"))
    if actual_height < required_height:
        return False, f"实际分辨率 {actual_height}p，低于要求 {required_height}p", info

    return True, f"实际分辨率 {actual_height}p，符合要求", info


# ===========================================================================
# 第十部分：YouTube Token 解析与优先级
# ===========================================================================

def _normalize_youtube_tokens(youtube_tokens: Dict[str, Any]) -> Dict[str, Any]:
    """
    规范化 YouTube Token 字典，确保所有字段类型正确、有默认值。
    这是内部函数，不建议外部直接调用。
    """
    return {
        "visitor_data": str(youtube_tokens.get("visitor_data") or "").strip(),
        "po_token": str(youtube_tokens.get("po_token") or "").strip(),
        "token_client": str(youtube_tokens.get("token_client") or "web").strip() or "web",
        "source": str(youtube_tokens.get("source") or "manual").strip() or "manual",
        "expires_hint_seconds": to_int(youtube_tokens.get("expires_hint_seconds"), 3600),
    }


def get_env_youtube_tokens() -> Dict[str, Any]:
    """
    从环境变量中读取 YouTube Token。
    
    支持的环境变量：
      - YT_VISITOR_DATA: YouTube 访客标识
      - YT_PO_TOKEN: YouTube 播放 Token
      - YT_TOKEN_CLIENT: Token 对应的客户端类型（默认 "web"）
    
    如果未设置这些环境变量，对应字段将为空字符串。
    """
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
    """
    计算实际生效的 Token 数据，根据优先级合并文件 Token 和环境变量 Token。
    
    Token 优先级规则（从高到低）：
      1. 环境变量（YT_VISITOR_DATA / YT_PO_TOKEN / YT_TOKEN_CLIENT）
      2. state/tokens.json 文件中保存的 Token
    
    也就是说：环境变量会覆盖文件中的 Token。
    这样设计的好处是：平时把 Token 存在文件里，特殊情况可临时用环境变量覆盖。
    
    参数：
        file_tokens_data: 从 tokens.json 读取的原始数据
    返回：
        合并后实际生效的 Token 数据字典
    """
    base = default_tokens_data()
    file_tokens_data = file_tokens_data or {}

    file_yt = file_tokens_data.get("youtube") if isinstance(file_tokens_data, dict) else {}
    if not isinstance(file_yt, dict):
        file_yt = {}

    file_norm = _normalize_youtube_tokens(file_yt)
    env_norm = get_env_youtube_tokens()

    # 环境变量优先：有环境变量就用环境变量，否则用文件里的
    visitor_data = env_norm["visitor_data"] or file_norm["visitor_data"]
    po_token = env_norm["po_token"] or file_norm["po_token"]

    # token_client 跟随 Token 来源：有环境变量 Token 就用环境变量的 client，否则用文件的
    token_client = (
        env_norm["token_client"]
        if (env_norm["visitor_data"] or env_norm["po_token"])
        else file_norm["token_client"]
    )

    # 记录来源（用于日志显示）
    source = "none"
    if env_norm["visitor_data"] or env_norm["po_token"]:
        source = "env"
    elif file_norm["visitor_data"] or file_norm["po_token"]:
        source = file_norm["source"] or "file"

    base["updated_at"] = (
        to_int(file_tokens_data.get("updated_at"), 0)
        if isinstance(file_tokens_data, dict)
        else 0
    )
    base["youtube"] = {
        "visitor_data": visitor_data,
        "po_token": po_token,
        "token_client": token_client or "web",
        "source": source,
        "expires_hint_seconds": file_norm["expires_hint_seconds"],
    }
    return base


def token_runtime_summary(tokens_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    返回当前生效 Token 状态的简要摘要，用于日志打印和条件判断。
    
    参数：
        tokens_data: 由 effective_tokens_data() 返回的 Token 数据
    返回：
        包含以下字段的字典：
          - visitor_data_set: bool，visitor_data 是否已设置
          - po_token_set: bool，po_token 是否已设置
          - token_client: str，Token 对应的客户端类型
          - token_source: str，Token 来源（"env" / "file" / "none"）
    """
    yt = tokens_data.get("youtube") if isinstance(tokens_data, dict) else {}
    if not isinstance(yt, dict):
        yt = {}
    return {
        "visitor_data_set": bool(str(yt.get("visitor_data") or "").strip()),
        "po_token_set": bool(str(yt.get("po_token") or "").strip()),
        "token_client": str(yt.get("token_client") or "web").strip() or "web",
        "token_source": str(yt.get("source") or "none").strip() or "none",
    }


# ===========================================================================
# 第十一部分：YouTube extractor-args 构建
# ===========================================================================

def build_youtube_extractor_args(
    yt_client: Optional[str],
    tokens_data: Optional[Dict[str, Any]] = None,
    extra_args: Optional[List[str]] = None,
) -> Optional[str]:
    """
    为 yt-dlp 构建 YouTube 专用的 --extractor-args 参数字符串。
    
    这些参数告诉 yt-dlp 如何向 YouTube 标识自己的身份，包括：
      - player_client: 模拟哪种客户端（web / mweb / ios / tv 等）
      - visitor_data: 访客标识 Token
      - po_token: 播放 Token（与 player_client 配合，提升可访问的画质）
    
    参数：
        yt_client: 要使用的 YouTube 客户端名称，None 表示不指定
        tokens_data: 经 effective_tokens_data() 处理的 Token 数据
        extra_args: 额外的 extractor-args 片段
    返回：
        extractor-args 字符串（如 "youtube:player_client=web;visitor_data=xxx;po_token=web.gvs+yyy"），
        没有任何需要设置的参数时返回 None
    """
    parts: List[str] = []

    tokens_data = effective_tokens_data(tokens_data)
    youtube_tokens = tokens_data.get("youtube") if isinstance(tokens_data, dict) else {}
    if not isinstance(youtube_tokens, dict):
        youtube_tokens = {}

    visitor_data = str(youtube_tokens.get("visitor_data") or "").strip()
    po_token = str(youtube_tokens.get("po_token") or "").strip()
    token_client = str(youtube_tokens.get("token_client") or "web").strip() or "web"

    # 如果有 po_token 但没有指定 client，使用 token 对应的 client
    effective_client = yt_client
    if po_token and not effective_client:
        effective_client = token_client

    if effective_client:
        parts.append(f"player_client={effective_client}")

    if visitor_data:
        parts.append(f"visitor_data={visitor_data}")

    if po_token:
        # po_token 格式："{client}.gvs+{token_value}"
        parts.append(f"po_token={(effective_client or token_client)}.gvs+{po_token}")

    for extra in (extra_args or []):
        e = str(extra).strip()
        if e:
            parts.append(e)

    if not parts:
        return None

    return "youtube:" + ";".join(parts)


# ===========================================================================
# 第十二部分：下载计划文件名辅助
# ===========================================================================

def build_plan_fixed_fragment(plan: Dict[str, Any]) -> str:
    """
    根据下载计划生成文件名的固定后缀片段。
    
    生成格式：[视频ID] [client-客户端] [分辨率] [模式-格式ID]
    示例：[LJkIVzy7DSc] [client-auto] [2160p] [adaptive-313_plus_251]
    
    这个后缀与视频标题一起构成完整文件名，方便识别文件对应的下载参数。
    固定后缀不随标题变化，因此可用于查找与某个计划相关的文件。
    
    参数：
        plan: plan_cache.json 中的单条下载计划字典
    返回：
        文件名固定后缀字符串
    """
    vid_id = str(plan.get("id") or "unknown")
    client_label = sanitize_label("auto" if plan.get("yt_client") is None else str(plan.get("yt_client")))
    mode_label = sanitize_label(str(plan.get("mode") or "unknown"))
    fmt_label = sanitize_label(str(plan.get("format_expr") or "na"))
    height_label = f"{to_int(plan.get('height'))}p"

    return f"[{vid_id}] [client-{client_label}] [{height_label}] [{mode_label}-{fmt_label}]"


def build_output_template(plan: Dict[str, Any]) -> str:
    """
    根据下载计划生成 yt-dlp 的 -o 输出文件名模板。
    
    生成格式：%(title)s [视频ID] [client-客户端] [分辨率] [模式-格式ID].%(ext)s
    
    其中 %(title)s 和 %(ext)s 由 yt-dlp 在下载时自动替换为实际视频标题和扩展名。
    
    参数：
        plan: 下载计划字典
    返回：
        yt-dlp 输出模板字符串
    """
    return f"%(title)s {build_plan_fixed_fragment(plan)}.%(ext)s"


# ===========================================================================
# 第十三部分：下载计划状态管理
# ===========================================================================

# 下载计划的三种状态常量
PLAN_STATUS_USABLE = "usable"                     # 可用：计划正常，可以直接用于下载
PLAN_STATUS_SUSPECTED_EXPIRED = "suspected_expired"  # 疑似过期：遇到错误，但不确定是否彻底失效
PLAN_STATUS_INVALID = "invalid"                   # 无效：确认不可用（如视频本身没有4K）


def plan_status(plan: Dict[str, Any]) -> str:
    """
    获取下载计划的当前状态。
    
    如果计划没有明确的状态字段，默认认为是 "usable"（向后兼容旧格式）。
    
    参数：
        plan: 下载计划字典
    返回：
        状态字符串（PLAN_STATUS_* 常量之一）
    """
    return str(plan.get("status") or PLAN_STATUS_USABLE)


def plan_is_fresh(plan: Dict[str, Any], ttl_seconds: int) -> bool:
    """
    判断下载计划是否在有效期（TTL）内。
    
    计划可能因为时间过长而「过期」：视频平台的视频流 URL 通常有时效性，
    缓存太久的计划可能已经无法使用。
    
    参数：
        plan: 下载计划字典
        ttl_seconds: 计划有效期（秒）。0 或负数表示永不过期。
    返回：
        True 表示计划还在有效期内，False 表示已过期
    """
    if ttl_seconds <= 0:
        return True     # TTL 为 0 时认为永不过期

    # 以「最后验证时间」为基准，如果没有则回退到「缓存时间」
    base_ts = to_int(plan.get("last_verified_at")) or to_int(plan.get("cached_at"))
    if base_ts <= 0:
        return False

    return (now_ts() - base_ts) <= ttl_seconds


def plan_is_usable(plan: Dict[str, Any], min_height: int, ttl_seconds: int) -> bool:
    """
    综合判断下载计划是否可直接使用（状态正常 + 分辨率达标 + 未过期）。
    
    三个条件必须同时满足：
      1. 状态为 "usable"（非 suspected_expired 或 invalid）
      2. 计划的分辨率 >= min_height（满足最低分辨率要求）
      3. 计划未超过 TTL（在有效期内）
    
    参数：
        plan: 下载计划字典
        min_height: 最低要求分辨率（如 2160 表示 4K）
        ttl_seconds: 计划有效期（秒）
    返回：
        True 表示可直接使用，False 表示需要重新探测
    """
    status = plan_status(plan)
    height = to_int(plan.get("height"))
    if status != PLAN_STATUS_USABLE:
        return False
    if height < min_height:
        return False
    return plan_is_fresh(plan, ttl_seconds)


def touch_plan_verified(plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    更新计划的「最后验证时间」，并将状态重置为可用。
    
    在下载成功后调用，表示「这个计划刚刚被验证可用」，延长其有效期。
    
    参数：
        plan: 下载计划字典（会被直接修改）
    返回：
        修改后的计划字典（同一对象）
    """
    plan["last_verified_at"] = now_ts()
    plan["status"] = PLAN_STATUS_USABLE
    plan["last_error"] = ""
    return plan


def mark_plan_status(plan: Dict[str, Any], status: str, reason: str = "") -> Dict[str, Any]:
    """
    修改计划的状态，并记录原因和时间。
    
    用于标记失败的计划（如遇到 403 错误标记为 suspected_expired，
    确认视频无 4K 时标记为 invalid）。
    
    参数：
        plan: 下载计划字典（会被直接修改）
        status: 新状态（PLAN_STATUS_* 常量之一）
        reason: 状态变更原因（用于调试）
    返回：
        修改后的计划字典（同一对象）
    """
    plan["status"] = status
    plan["last_error"] = reason
    plan["last_status_at"] = now_ts()
    return plan


# ===========================================================================
# 第十四部分：多平台 URL 识别与 ID 提取
# ===========================================================================

# ---- Bilibili（B站）----

def is_bilibili_url(url: str) -> bool:
    """判断 URL 是否为 Bilibili（B站）视频链接。支持 bilibili.com/video/ 和 b23.tv/ 短链。"""
    s = url.lower()
    return "bilibili.com/video/" in s or "b23.tv/" in s


def bilibili_bvid_from_url(url: str) -> Optional[str]:
    """
    从 Bilibili URL 中提取 BV 号（视频唯一标识）。
    
    示例：
        "https://www.bilibili.com/video/BV1d6HKexEe8/" → "BV1d6HKexEe8"
        "https://www.bilibili.com/video/av12345/" → "av12345"
    
    返回：
        BV 号或 av 号字符串，无法提取返回 None
    """
    m = re.search(r"bilibili\.com/video/(BV[A-Za-z0-9]+)", url, re.IGNORECASE)
    if m:
        return m.group(1)
    # 兼容旧版 av 号格式
    m2 = re.search(r"bilibili\.com/video/(av\d+)", url, re.IGNORECASE)
    if m2:
        return m2.group(1)
    return None


# ---- 小红书（Xiaohongshu）----

def is_xiaohongshu_url(url: str) -> bool:
    """判断 URL 是否为小红书笔记链接。支持 xiaohongshu.com/explore/ 和 xhslink.com/ 短链。"""
    s = url.lower()
    return (
        "xiaohongshu.com/explore/" in s
        or "xhslink.com/" in s
        or "xiaohongshu.com/discovery/" in s
    )


def xiaohongshu_note_id_from_url(url: str) -> Optional[str]:
    """
    从小红书 URL 中提取笔记 ID（24 位十六进制字符串）。
    
    小红书 URL 通常包含 xsec_token 等查询参数，这些参数会变化，
    通过提取固定的 note_id 可以生成稳定的缓存键。
    
    示例：
        "https://www.xiaohongshu.com/explore/674b2a5d000000000201bfb3?..." → "674b2a5d000000000201bfb3"
    
    返回：
        24 位十六进制 note_id，无法提取返回 None
    """
    m = re.search(r"/explore/([0-9a-f]{24})", url, re.IGNORECASE)
    if m:
        return m.group(1)
    m2 = re.search(r"/discovery/item/([0-9a-f]{24})", url, re.IGNORECASE)
    if m2:
        return m2.group(1)
    return None


# ---- 抖音（Douyin）----

def is_douyin_url(url: str) -> bool:
    """判断 URL 是否为抖音视频链接。支持 douyin.com/video/、v.douyin.com/ 和 douyin.com/share/。"""
    s = url.lower()
    return "douyin.com/video/" in s or "v.douyin.com/" in s or "douyin.com/share/" in s


def douyin_video_id_from_url(url: str) -> Optional[str]:
    """
    从抖音 URL 中提取数字视频 ID。
    
    示例：
        "https://www.douyin.com/video/7616874077805890835" → "7616874077805890835"
    
    返回：
        数字 ID 字符串，无法提取返回 None
    """
    m = re.search(r"douyin\.com/video/(\d+)", url)
    if m:
        return m.group(1)
    return None


# ---- TikTok ----

def is_tiktok_url(url: str) -> bool:
    """判断 URL 是否为 TikTok 视频链接。支持 tiktok.com/ 和 vm.tiktok.com/ 短链。"""
    s = url.lower()
    return "tiktok.com/" in s or "vm.tiktok.com/" in s


def tiktok_video_id_from_url(url: str) -> Optional[str]:
    """
    从 TikTok URL 中提取数字视频 ID。
    
    示例：
        "https://www.tiktok.com/@user/video/7553069613832080658" → "7553069613832080658"
    
    返回：
        数字 ID 字符串，无法提取返回 None
    """
    m = re.search(r"tiktok\.com/@[^/]+/video/(\d+)", url)
    if m:
        return m.group(1)
    m2 = re.search(r"tiktok\.com/v/(\d+)", url)
    if m2:
        return m2.group(1)
    return None
