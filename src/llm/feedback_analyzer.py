from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import yaml

from .openrouter_client import OpenRouterClient, OpenRouterError
from .prompts import FEEDBACK_SYSTEM


def _parse_yaml(raw: str) -> Dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.replace("yaml\n", "", 1)
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("LLM feedback output is not YAML mapping")
    return data


def analyze_feedback_with_openrouter(stats: Dict[str, Any], examples: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any], List[str]]:
    warnings: List[str] = []
    client = OpenRouterClient()
    if not client.is_configured():
        return "", {}, ["未检测到 OPENROUTER_API_KEY，反馈分析使用规则模式。"]
    payload = yaml.safe_dump(
        {"statistics": stats, "review_examples_truncated": examples[:80]},
        allow_unicode=True,
        sort_keys=False,
    )
    try:
        parsed, _raw, _cached = client.chat_cached(
            skill_name="feedback_analyzer",
            input_text=payload,
            messages=[
                {"role": "system", "content": FEEDBACK_SYSTEM},
                {"role": "user", "content": "REVIEW_FEEDBACK:\n```yaml\n" + payload + "\n```"},
            ],
            parser=_parse_yaml,
        )
        md = str(parsed.get("strategy_markdown") or "")
        plan = parsed.get("search_plan") if isinstance(parsed.get("search_plan"), dict) else {}
        return md, plan, warnings
    except (OpenRouterError, Exception) as exc:
        return "", {}, [f"OpenRouter 反馈分析失败，已使用规则模式：{exc}"]
