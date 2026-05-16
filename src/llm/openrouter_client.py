from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List

from ..core.config import openrouter_api_key, openrouter_config
from ..llm_cache import CacheParams, cache_fingerprint, read_cache, write_cache
from ..utils import PROJECT_ROOT


class OpenRouterError(RuntimeError):
    pass


class OpenRouterClient:
    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        self.config = dict(config or openrouter_config())
        self.model = str(self.config.get("model") or "google/gemini-2.5-flash")
        self.base_url = str(self.config.get("base_url") or "https://openrouter.ai/api/v1").rstrip("/")
        self.temperature = float(self.config.get("temperature") or 0.2)
        self.max_tokens = int(self.config.get("max_output_tokens") or 4096)
        self.prompt_version = str(self.config.get("prompt_version") or "ad-url-scout-v1")
        self.cache_enabled = bool(self.config.get("cache_enabled", True))
        cache_dir = Path(str(self.config.get("cache_dir") or "cache/llm"))
        self.cache_dir = cache_dir if cache_dir.is_absolute() else PROJECT_ROOT / cache_dir

    @property
    def api_key(self) -> str:
        return openrouter_api_key()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def chat(
        self,
        messages: Iterable[Dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if not self.api_key:
            raise OpenRouterError(
                "未检测到 OPENROUTER_API_KEY。请在 .env 中填写 OPENROUTER_API_KEY，或在设置菜单中配置。"
            )
        body: Dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": self.temperature if temperature is None else float(temperature),
        }
        body["max_tokens"] = self.max_tokens if max_tokens is None else int(max_tokens)
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/alalapi-0/ad-url-scout",
            "X-Title": "Ad URL Scout",
        }
        url = f"{self.base_url}/chat/completions"

        try:
            import requests  # type: ignore

            resp = requests.post(url, headers=headers, json=body, timeout=120)
            if not resp.ok:
                raise OpenRouterError(f"OpenRouter HTTP {resp.status_code}: {resp.text[:500]}")
            parsed = resp.json()
        except ImportError:
            req = urllib.request.Request(url=url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    parsed = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise OpenRouterError(f"OpenRouter HTTP {exc.code}: {detail[:500]}") from exc
        except OpenRouterError:
            raise
        except Exception as exc:
            raise OpenRouterError(f"OpenRouter 调用失败：{exc}") from exc

        text = str(((parsed.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        if not text.strip():
            raise OpenRouterError("OpenRouter 返回为空。")
        return text

    def chat_cached(
        self,
        *,
        skill_name: str,
        input_text: str,
        messages: List[Dict[str, str]],
        parser,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[Any, str, bool]:
        fingerprint = cache_fingerprint(
            CacheParams(
                provider="openrouter",
                model=self.model,
                skill_name=skill_name,
                prompt_version=self.prompt_version,
                input_text=input_text,
            )
        )
        if self.cache_enabled:
            cached = read_cache(self.cache_dir, fingerprint)
            if cached and cached.get("parsed") is not None:
                return cached["parsed"], str(cached.get("raw") or ""), True

        raw = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        parsed = parser(raw)
        if self.cache_enabled:
            write_cache(
                self.cache_dir,
                fingerprint,
                meta={"provider": "openrouter", "model": self.model, "skill": skill_name},
                raw_text=raw,
                parsed=parsed,
            )
        return parsed, raw, False
