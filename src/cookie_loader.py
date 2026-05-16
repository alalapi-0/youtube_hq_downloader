from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from .utils import PROJECT_ROOT, load_yaml_mapping


COOKIE_CONFIG_PATH = PROJECT_ROOT / "config" / "cookie_config.yaml"


@dataclass
class CookieSettings:
    enabled: bool = False
    mode: str = "none"
    cookie_file: str = ""
    browser: str = "chrome"
    cookies_from_browser: bool = False
    never_log_cookie_content: bool = True
    status: str = "disabled"
    warning: str = ""


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("1", "true", "yes", "on", "y")


def load_cookie_settings(
    *,
    config_path: Path | str = COOKIE_CONFIG_PATH,
    cookie_file: str | None = None,
    cookies_from_browser: str | None = None,
    enable_cookie: bool | None = None,
) -> CookieSettings:
    raw = load_yaml_mapping(config_path) if Path(config_path).exists() else {}
    block: Dict[str, Any] = raw.get("cookie") if isinstance(raw.get("cookie"), dict) else {}
    settings = CookieSettings(
        enabled=_truthy(block.get("enabled")),
        mode=str(block.get("mode") or "none"),
        cookie_file=str(block.get("cookie_file") or ""),
        browser=str(block.get("browser") or "chrome"),
        cookies_from_browser=_truthy(block.get("cookies_from_browser")),
        never_log_cookie_content=bool(block.get("never_log_cookie_content", True)),
    )

    if enable_cookie is not None:
        settings.enabled = bool(enable_cookie)

    if cookie_file:
        settings.enabled = True
        settings.mode = "file"
        settings.cookie_file = str(cookie_file)
        settings.cookies_from_browser = False

    if cookies_from_browser:
        settings.enabled = True
        settings.mode = "browser"
        settings.browser = str(cookies_from_browser)
        settings.cookies_from_browser = True

    if not settings.enabled or settings.mode in ("", "none"):
        settings.enabled = False
        settings.mode = "none"
        settings.cookies_from_browser = False
        settings.status = "disabled"
        return settings

    if settings.mode == "file":
        if not settings.cookie_file:
            settings.enabled = False
            settings.status = "failed_missing_cookie_file"
            settings.warning = "Cookie file mode selected but no path was provided; falling back to no-cookie mode."
            return settings
        p = Path(settings.cookie_file).expanduser()
        if not p.is_absolute():
            p = (PROJECT_ROOT / p).resolve()
        if not p.exists():
            settings.enabled = False
            settings.status = "failed_cookie_file_not_found"
            settings.warning = f"Cookie file not found: {p}; falling back to no-cookie mode."
            return settings
        settings.cookie_file = str(p)
        settings.status = "enabled_cookie_file"
        return settings

    if settings.mode == "browser" or settings.cookies_from_browser:
        settings.mode = "browser"
        settings.cookies_from_browser = True
        settings.status = "enabled_cookies_from_browser"
        settings.warning = (
            "cookies-from-browser will ask yt-dlp to read cookies already available in the selected local browser. "
            "Use only for pages you can access yourself; this does not bypass permissions and must not be used to download restricted content."
        )
        return settings

    settings.enabled = False
    settings.mode = "none"
    settings.status = "disabled_unknown_mode"
    return settings


def ytdlp_cookie_args(settings: CookieSettings) -> List[str]:
    if not settings.enabled:
        return []
    if settings.mode == "file" and settings.cookie_file:
        return ["--cookies", settings.cookie_file]
    if settings.mode == "browser" and settings.cookies_from_browser:
        return ["--cookies-from-browser", settings.browser or "chrome"]
    return []


def webpage_cookie_file(settings: CookieSettings) -> str:
    if settings.enabled and settings.mode == "file" and settings.cookie_file:
        return settings.cookie_file
    return ""


def cookie_status_for_record(settings: CookieSettings) -> Dict[str, str | bool]:
    return {
        "enabled": bool(settings.enabled),
        "mode": settings.mode,
        "status": settings.status,
    }
