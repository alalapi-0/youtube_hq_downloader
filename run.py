from __future__ import annotations


def _missing_dependency_message(name: str) -> str:
    return f"""启动失败：缺少 Python 依赖 `{name}`。

macOS / Homebrew Python 不允许直接把依赖装进系统环境。请在项目目录执行：

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 run.py

以后再次启动时只需要：

source .venv/bin/activate
python3 run.py
"""


def main() -> int:
    try:
        from src.console.app import main as console_main
    except ModuleNotFoundError as exc:
        print(_missing_dependency_message(exc.name or "unknown"))
        return 2
    return int(console_main())


if __name__ == "__main__":
    raise SystemExit(main())
