from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from .llm_cache import CacheParams, cache_fingerprint, read_cache, write_cache
from .llm_client import ChatMessage, GrokUnsupportedError, openai_compatible_chat_completion, require_non_empty_api_key
from .utils import PROJECT_ROOT, load_yaml_mapping


def _cache_dir(llm_cfg: Dict[str, Any]) -> Path:
    rel = (((llm_cfg or {}).get("cache") or {}) or {}).get("directory") or "cache"
    p = Path(rel)
    return p if p.is_absolute() else PROJECT_ROOT / p


def plan_with_llm(
    *,
    user_text: str,
    llm_config_path: Path,
    prompts_path: Path,
    skill_prompt_version: str,
) -> Dict[str, Any]:
    prompts = load_yaml_mapping(prompts_path)
    cfg = load_yaml_mapping(llm_config_path)

    provider = str(cfg.get("provider") or "openrouter")
    model = str(cfg.get("model") or "gpt-4o-mini")

    fingerprint = cache_fingerprint(
        CacheParams(
            provider=provider,
            model=model,
            skill_name="query_planner",
            prompt_version=skill_prompt_version,
            input_text=user_text,
        )
    )
    cdir = _cache_dir(cfg)
    cached = read_cache(cdir, fingerprint)
    if cached:
        blob = yaml.safe_load(cached["parsed"].get("plan_yaml_text") or "")
        if isinstance(blob, dict):
            return blob

    try:
        base, api_key = require_non_empty_api_key(provider, cfg)
    except GrokUnsupportedError:
        raise
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc

    reply = openai_compatible_chat_completion(
        base_url=base,
        api_key=api_key,
        model=model,
        messages=[ChatMessage("system", sys_msg), ChatMessage("user", user_msg)],
        temperature=float(cfg.get("temperature") or 0.2),
        max_tokens=int(((cfg.get("max_output_tokens") or 2048))),
        extra_headers=None,
    )

    text = reply.strip()

    blob = yaml.safe_load(text)

    meta = {"provider": provider, "model": model, "skill": "query_planner", "user_text_len": len(user_text)}
    write_cache(
        cdir,
        fingerprint,
        meta=meta,
        raw_text=text,
        parsed={"plan_yaml_text": text, "finger": fingerprint},
    )
    return blob if isinstance(blob, dict) else {}


def load_plan_yaml(plan_path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}
