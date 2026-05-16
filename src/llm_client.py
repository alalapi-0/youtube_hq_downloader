from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, MutableMapping


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


@dataclass
class ChatMessage:
    role: str
    content: str


def normalize_provider(raw: str) -> str:
    return "openrouter"


def compose_base_url(provider: str, cfg: Mapping[str, Any]) -> tuple[str, str]:
    defaults = cfg.get("defaults") or {}
    env = cfg.get("env") or {}
    env_url = os.environ.get(str(env.get("openrouter_base_url") or "OPENROUTER_BASE_URL"), "").strip()
    base = env_url or str(defaults.get("openrouter_base_url") or cfg.get("base_url") or "https://openrouter.ai/api/v1")
    key_env = str(env.get("openrouter_api_key") or cfg.get("api_key_env") or "OPENROUTER_API_KEY")
    api_key = os.environ.get(key_env, "").strip()
    return base.rstrip("/"), api_key


def openai_compatible_chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: Iterable[ChatMessage],
    temperature: float = 0.2,
    max_tokens: int | None = None,
    extra_headers: MutableMapping[str, str] | None = None,
) -> str:
    url = f"{base_url}/chat/completions"
    hdrs = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if extra_headers:
        hdrs.update(dict(extra_headers))
    body: Dict[str, Any] = {
        "model": model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "temperature": float(temperature),
    }
    if max_tokens is not None:
        body["max_tokens"] = int(max_tokens)

    data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    def _post_urllib() -> str:
        req = urllib.request.Request(url=url, data=data, headers=hdrs, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM HTTP {e.code}: {detail}") from e
        parsed = json.loads(payload)
        return str(((parsed.get("choices") or [{}])[0].get("message") or {}).get("content") or "")

    try:
        import requests  # type: ignore

        r = requests.post(url, headers=dict(hdrs), json=body, timeout=120)
        if not r.ok:
            raise RuntimeError(f"LLM HTTP {r.status_code}: {r.text}")
        parsed = r.json()
        return str(((parsed.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    except ImportError:
        return _post_urllib()


def require_non_empty_api_key(provider: str, cfg: Mapping[str, Any]) -> tuple[str, str]:
    """
    Resolve base URL + api key from env/yaml mapping.
    """
    base, api_key = compose_base_url(provider, cfg)
    if not api_key and not _truthy_env("ALLOW_EMPTY_LLM_KEY"):
        raise RuntimeError("未检测到 OPENROUTER_API_KEY。请在 .env 中填写 OPENROUTER_API_KEY。")
    return base, api_key
