from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from .llm_cache import CacheParams, cache_fingerprint, read_cache, write_cache
from .llm_client import ChatMessage, GrokUnsupportedError, openai_compatible_chat_completion, require_non_empty_api_key
from .utils import PROJECT_ROOT, load_yaml_mapping


def _cache_dir(llm_cfg: Dict[str, Any]) -> Path:
    rel = (((llm_cfg or {}).get("cache") or {}) or {}).get("directory") or "cache"
    p = Path(rel)
    return p if p.is_absolute() else PROJECT_ROOT / p


def resolve_channels(
    *,
    hints: List[str],
    llm_config_path: Path,
    prompts_path: Path,
    prompt_version: str,
) -> Dict[str, Any]:
    prompts = load_yaml_mapping(prompts_path)
    cfg = load_yaml_mapping(llm_config_path)
    provider = str(cfg.get("provider") or "openrouter")
    model = str(cfg.get("model") or "gpt-4o-mini")
    inp = json.dumps({"hints": hints}, ensure_ascii=False)

    fingerprint = cache_fingerprint(
        CacheParams(
            provider=provider,
            model=model,
            skill_name="channel_resolver",
            prompt_version=prompt_version,
            input_text=inp,
        )
    )
    cdir = _cache_dir(cfg)
    cached = read_cache(cdir, fingerprint)
    if cached and isinstance(cached["parsed"].get("json"), dict):
        return cached["parsed"]["json"]

    try:
        base, api_key = require_non_empty_api_key(provider, cfg)
    except GrokUnsupportedError:
        raise

    sys_msg = str(prompts.get("channel_resolver_system") or "").strip()
    user_msg = f"HINTS_JSON:\n{inp}\n"
    reply = openai_compatible_chat_completion(
        base_url=base,
        api_key=api_key,
        model=model,
        messages=[ChatMessage("system", sys_msg), ChatMessage("user", user_msg)],
        temperature=float(cfg.get("temperature") or 0.2),
        max_tokens=int(((cfg.get("max_output_tokens") or 1024))),
    )

    payload = _parse_json_with_retry(reply)
    meta = {"provider": provider, "model": model, "skill": "channel_resolver"}
    write_cache(cdir, fingerprint, meta=meta, raw_text=reply, parsed={"json": payload})
    return payload


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


def _parse_json_with_retry(text: str) -> Dict[str, Any]:
    blob = text.strip()
    try:
        return json.loads(blob)
    except Exception:
        m = _JSON_FENCE_RE.search(blob)
        if m:
            return json.loads(m.group(1).strip())
        raise

