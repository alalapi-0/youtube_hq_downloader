from __future__ import annotations

import copy
from pathlib import Path

import yaml

from .utils import PROJECT_ROOT


def _backup(path: Path) -> Path:
    bak = path.with_suffix(path.suffix + ".bak")
    n = 1
    while bak.exists():
        bak = path.with_suffix(path.suffix + f".bak.{n}")
        n += 1
    bak.write_bytes(path.read_bytes())
    return bak


def load_yaml_roundtrip(path: Path) -> tuple[bool, str, dict | list | None]:
    try:
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        roundtrip = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        yaml.safe_load(roundtrip)
        return True, "", data
    except Exception as exc:
        return False, str(exc), None


def save_yaml_atomic(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def edit_yaml_file_interactive(path: Path, console_print) -> bool:
    """
    备份 → 提示外部编辑 → 回车校验 roundtrip。
    console_print: Callable[[str], None]
    """
    if not path.exists():
        console_print(f"文件不存在：{path}")
        return False
    ok, err, data = load_yaml_roundtrip(path)
    if not ok:
        console_print(f"YAML 当前无效：{err}")
        return False
    assert data is not None
    bak = _backup(path)
    console_print(f"已备份 -> {bak}")
    console_print("请在外部编辑器修改文件后回到此窗口。")
    input("修改完成按 Enter 继续校验…")
    ok2, err2, _ = load_yaml_roundtrip(path)
    if not ok2:
        console_print(f"校验失败，可从备份恢复：{bak}\n{err2}")
        return False
    console_print("YAML 校验通过。")
    return True


def known_editable_configs() -> list[tuple[str, Path]]:
    return [
        ("规则闸门 filter_rules.yaml", PROJECT_ROOT / "config" / "filter_rules.yaml"),
        ("LLM 配置 llm_config.yaml", PROJECT_ROOT / "config" / "llm_config.yaml"),
    ]


def deep_merge_dict(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge_dict(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out
