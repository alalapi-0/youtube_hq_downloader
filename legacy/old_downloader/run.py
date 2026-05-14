#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run.py — 一键启动脚本

【使用方式】
  在项目根目录执行以下命令即可：
    python3 run.py

【执行流程】
  第 1 步：刷新环境状态
    检测本机的 yt-dlp、ffmpeg、浏览器等工具是否正常
    并将结果保存到 state/env_state.json
    
  第 2 步：探测视频格式
    读取 urls.txt 中的所有视频链接
    逐个探测最佳下载格式（4K 优先）
    将结果保存到 state/plan_cache.json
    
  第 3 步：执行下载
    按照第 2 步探测到的格式计划下载视频
    下载结果保存到 downloads/ 目录

【注意事项】
  - 首次运行前，请先在 urls.txt 中填写要下载的视频链接（每行一条）
  - 默认严格要求 4K（2160p）分辨率，不满足的视频会跳过
  - 如需下载 1080p，修改 scripts/probe_best_plan.py 中的 MIN_HEIGHT_DEFAULT
  - 如遇 4K 下载失败，请参考 README.md 配置 YouTube Token
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

# 项目根目录（run.py 所在的目录）
PROJECT_ROOT = Path(__file__).resolve().parent
# 脚本目录（所有核心脚本都在这里）
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

# env_state.json 的刷新间隔（秒）。在此间隔内不重复检测工具环境。
# 3600 = 1 小时
ENV_STATE_TTL_SECONDS = 3600


def run_script(script_name: str, *args: str) -> int:
    """
    在项目根目录下执行指定脚本，并返回其退出码。
    
    使用当前 Python 解释器（确保虚拟环境一致）。
    
    参数：
        script_name: 脚本文件名（如 "refresh_context.py"）
        *args: 传给脚本的额外命令行参数
    返回：
        脚本的退出码（0 表示成功，非 0 表示有错误）
    """
    cmd = [sys.executable, str(SCRIPTS_DIR / script_name), *args]
    r = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return r.returncode


def env_state_is_fresh() -> bool:
    """
    判断 state/env_state.json 是否在有效期内（避免每次都重新检测工具环境）。
    
    如果文件不存在，或 updated_at 距今超过 ENV_STATE_TTL_SECONDS，则认为需要刷新。
    """
    env_file = PROJECT_ROOT / "state" / "env_state.json"
    if not env_file.exists():
        return False
    try:
        data = json.loads(env_file.read_text(encoding="utf-8"))
        updated_at = int(data.get("updated_at") or 0)
        if updated_at <= 0:
            return False
        return (int(time.time()) - updated_at) <= ENV_STATE_TTL_SECONDS
    except Exception:
        return False


def main() -> int:
    """
    依次执行三个阶段的脚本。
    
    即使某个步骤失败（返回非 0），也会继续执行下一步，
    这样可以利用上一次运行时已保存的中间结果（如 plan_cache.json）。
    """
    # ---- 第 1 步：刷新环境状态 ----
    if env_state_is_fresh():
        print("[run] 1/3 工具环境状态缓存仍在有效期内，跳过重新检测")
    else:
        print("[run] 1/3 正在刷新本机工具环境状态（yt-dlp、ffmpeg、浏览器等）...")
        if run_script("refresh_context.py") != 0:
            print("[run] 环境检测遇到问题，但继续执行后续步骤（会使用已缓存的配置）")
    print()

    # ---- 第 2 步：探测视频格式计划 ----
    print("[run] 2/3 正在探测 urls.txt 中视频的最佳下载格式（严格要求 4K）...")
    if run_script("probe_best_plan.py") != 0:
        print("[run] 探测步骤遇到问题，但继续执行下载步骤（会使用已缓存的计划）")
    print()

    # ---- 第 3 步：按计划下载视频 ----
    print("[run] 3/3 正在按计划下载视频...")
    exit_code = run_script("download_by_plan.py")

    if exit_code == 0:
        print("[run] ✓ 全部完成！视频已保存到 downloads/ 目录")
    else:
        print("[run] 下载步骤遇到问题，请查看上方的输出信息排查原因")
        print("[run] 常见问题：1) 未配置 Token → 参考 README.md 的 Token 配置部分")
        print("[run]           2) 视频无 4K → 降低 MIN_HEIGHT_DEFAULT 参数")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
