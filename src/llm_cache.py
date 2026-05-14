from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass(frozen=True)
class CacheParams:
    provider: str
    model: str
    skill_name: str
    prompt_version: str
    input_text: str


def cache_fingerprint(params: CacheParams) -> str:
    payload = {
        "provider": params.provider.strip().lower(),
        "model": params.model.strip(),
        "skill_name": params.skill_name.strip(),
        "prompt_version": params.prompt_version.strip(),
        # input_text may be huge; hashing as whole string keeps stability
        "input_text": params.input_text,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cache_paths(cache_dir: Path, fingerprint: str) -> Dict[str, Path]:
    return {
        "meta": cache_dir / f"{fingerprint}.meta.json",
        "raw": cache_dir / f"{fingerprint}.raw.txt",
        "parsed": cache_dir / f"{fingerprint}.parsed.json",
    }


def read_cache(cache_dir: Path, fingerprint: str) -> Dict[str, Any] | None:
    paths = cache_paths(cache_dir, fingerprint)
    if not paths["parsed"].exists():
        return None
    try:
        meta = json.loads(paths["meta"].read_text(encoding="utf-8")) if paths["meta"].exists() else {}
        parsed = json.loads(paths["parsed"].read_text(encoding="utf-8"))
        raw = paths["raw"].read_text(encoding="utf-8") if paths["raw"].exists() else ""
        return {"meta": meta, "raw": raw, "parsed": parsed}
    except Exception:
        return None


def write_cache(
    cache_dir: Path,
    fingerprint: str,
    *,
    meta: Dict[str, Any],
    raw_text: str,
    parsed: Any,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths = cache_paths(cache_dir, fingerprint)
    paths["meta"].write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths["raw"].write_text(raw_text or "", encoding="utf-8")
    paths["parsed"].write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
