from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

from .utils import PROJECT_ROOT, load_yaml_mapping


ENV_EXAMPLE_KEYS = [
    "YOUTUBE_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "GROK_API_KEY",
]


def mask_secret(val: str | None) -> str:
    s = (val or "").strip()
    if not s:
        return "（未设置）"
    if len(s) <= 4:
        return "****"
    return f"****{s[-4:]}"


def python_version_ok() -> tuple[bool, str]:
    v = sys.version_info
    return v >= (3, 10), f"{v.major}.{v.minor}.{v.micro}"


def try_import(module: str) -> tuple[bool, str]:
    spec = importlib.util.find_spec(module)
    return spec is not None, module


def yt_dlp_on_path() -> tuple[bool, str]:
    exe = shutil.which("yt-dlp")
    return exe is not None, exe or ""


def env_file_paths() -> tuple[Path, Path]:
    return PROJECT_ROOT / ".env", PROJECT_ROOT / ".env.example"


def gitignore_has_env() -> tuple[bool, str]:
    gi = PROJECT_ROOT / ".gitignore"
    if not gi.exists():
        return False, "无 .gitignore"
    text = gi.read_text(encoding="utf-8", errors="replace")
    # 宽松匹配：行或路径含 .env
    for line in text.splitlines():
        t = line.strip()
        if t == ".env" or (t.endswith(".env") and not t.startswith("#")):
            return True, str(gi)
    if ".env" in text:
        return True, str(gi)
    return False, str(gi)


def load_env_masked() -> dict[str, str]:
    env_path, _ = env_file_paths()
    load_dotenv(env_path)
    out: dict[str, str] = {}
    for k in ENV_EXAMPLE_KEYS:
        out[k] = mask_secret(os.environ.get(k))
    return out


def required_yaml_configs() -> list[tuple[str, Path, bool]]:
    rels = [
        "config/filter_rules.yaml",
        "config/llm_config.yaml",
        "config/llm_prompts.yaml",
        "config/brand_whitelist.yaml",
        "config/negative_keywords.yaml",
        "config/search_tasks.demo.yaml",
    ]
    out: list[tuple[str, Path, bool]] = []
    for r in rels:
        p = PROJECT_ROOT / r
        out.append((r, p, p.exists()))
    return out


def important_dirs() -> list[tuple[str, Path, bool]]:
    pairs = [
        ("output", PROJECT_ROOT / "output"),
        ("data/raw", PROJECT_ROOT / "data" / "raw"),
        ("data/enriched", PROJECT_ROOT / "data" / "enriched"),
        ("data/filtered", PROJECT_ROOT / "data" / "filtered"),
        ("data/rejected", PROJECT_ROOT / "data" / "rejected"),
        ("logs", PROJECT_ROOT / "logs"),
        ("config", PROJECT_ROOT / "config"),
    ]
    return [(name, p, p.exists()) for name, p in pairs]


def run_full_env_check() -> dict[str, object]:
    ok_py, py_ver = python_version_ok()
    imports = {
        "googleapiclient": try_import("googleapiclient.discovery"),
        "yaml": try_import("yaml"),
        "dotenv": try_import("dotenv"),
        "pandas": try_import("pandas"),
        "requests": try_import("requests"),
    }
    ytd_ok, ytd_which = yt_dlp_on_path()
    env_exists = env_file_paths()[0].exists()
    masked = load_env_masked() if env_exists else {k: "（无 .env）" for k in ENV_EXAMPLE_KEYS}
    yamls = required_yaml_configs()
    dirs = important_dirs()
    gi_ok, gi_path = gitignore_has_env()

    return {
        "python_ok": ok_py,
        "python_version": py_ver,
        "imports": imports,
        "yt_dlp_ok": ytd_ok,
        "yt_dlp_path": ytd_which,
        "env_exists": env_exists,
        "masked_env": masked,
        "yamls": yamls,
        "dirs": dirs,
        "gitignore_env": (gi_ok, gi_path),
        "platform": platform.platform(),
    }


def summarize_env_check(report: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append(f"Python: {report['python_version']} — {'OK' if report['python_ok'] else '建议 3.10+'}")
    lines.append(f"平台: {report['platform']}")
    imps = report["imports"]
    assert isinstance(imps, dict)
    for label, tup in imps.items():
        assert isinstance(tup, tuple)
        ok, mod = tup
        lines.append(f"依赖导入 {label} ({mod}): {'OK' if ok else '缺失'}")
    lines.append(f"yt-dlp PATH: {'OK ' + str(report['yt_dlp_path']) if report['yt_dlp_ok'] else '未找到（可选）'}")
    lines.append(f".env 存在: {'是' if report['env_exists'] else '否'}")
    gi_ok, gi_p = report["gitignore_env"]
    assert isinstance(gi_ok, bool)
    lines.append(f".gitignore 含 .env: {'是' if gi_ok else '否'} ({gi_p})")
    masked = report["masked_env"]
    assert isinstance(masked, dict)
    lines.append("环境变量（脱敏）：")
    for k, v in masked.items():
        lines.append(f"  {k}={v}")
    yamls = report["yamls"]
    assert isinstance(yamls, list)
    lines.append("YAML 配置：")
    for rel, _p, ex in yamls:
        lines.append(f"  {rel}: {'存在' if ex else '缺失'}")
    dirs = report["dirs"]
    assert isinstance(dirs, list)
    lines.append("目录：")
    for name, _p, ex in dirs:
        lines.append(f"  {name}: {'存在' if ex else '缺失（将按需创建）'}")
    return "\n".join(lines)


def brand_categories() -> list[str]:
    p = PROJECT_ROOT / "config" / "brand_whitelist.yaml"
    if not p.exists():
        return []
    data = load_yaml_mapping(p)
    cats: list[str] = []
    for k, v in (data or {}).items():
        if k == "positive_keywords":
            continue
        if isinstance(v, dict):
            cats.append(str(k))
    return sorted(set(cats))


def brand_names_for_category(category: str) -> list[str]:
    p = PROJECT_ROOT / "config" / "brand_whitelist.yaml"
    if not p.exists():
        return []
    data = load_yaml_mapping(p)
    block = data.get(category)
    if not isinstance(block, dict):
        return []
    raw = block.get("brand_names") or []
    return [str(x).strip() for x in raw if str(x).strip()]
