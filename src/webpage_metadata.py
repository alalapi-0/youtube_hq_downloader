from __future__ import annotations

import http.cookiejar
import json
import re
import urllib.error
import urllib.request
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List


def empty_webpage_metadata(status: str = "not_requested", error: str = "") -> Dict[str, Any]:
    return {
        "og_title": "",
        "og_description": "",
        "meta_keywords": [],
        "canonical_url": "",
        "json_ld": {},
        "page_title": "",
        "page_description": "",
        "webpage_metadata_status": status,
        "error": error,
    }


class _MetadataHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: Dict[str, str] = {}
        self.canonical_url = ""
        self.title_chunks: List[str] = []
        self.json_ld_chunks: List[str] = []
        self._in_title = False
        self._in_json_ld = False
        self._script_buffer: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, str | None]]) -> None:
        tag_l = tag.lower()
        amap = {str(k).lower(): (v or "") for k, v in attrs}
        if tag_l == "title":
            self._in_title = True
            return
        if tag_l == "meta":
            key = (amap.get("property") or amap.get("name") or amap.get("itemprop") or "").strip().lower()
            content = (amap.get("content") or "").strip()
            if key and content:
                self.meta[key] = content
            return
        if tag_l == "link":
            rel = (amap.get("rel") or "").lower()
            href = (amap.get("href") or "").strip()
            if "canonical" in rel and href:
                self.canonical_url = href
            return
        if tag_l == "script":
            typ = (amap.get("type") or "").lower()
            if "ld+json" in typ:
                self._in_json_ld = True
                self._script_buffer = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_chunks.append(data)
        if self._in_json_ld:
            self._script_buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        if tag_l == "title":
            self._in_title = False
        if tag_l == "script" and self._in_json_ld:
            raw = "".join(self._script_buffer).strip()
            if raw:
                self.json_ld_chunks.append(raw)
            self._script_buffer = []
            self._in_json_ld = False


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def _keywords(value: str) -> List[str]:
    out: List[str] = []
    for part in (value or "").replace("|", ",").split(","):
        p = _clean_text(part)
        if p:
            out.append(p)
    return out


def _parse_json_ld(chunks: List[str]) -> Dict[str, Any]:
    items: List[Any] = []
    video_object: Dict[str, Any] = {}
    for raw in chunks:
        try:
            parsed = json.loads(raw)
        except Exception:
            continue
        if isinstance(parsed, list):
            items.extend(parsed)
        else:
            items.append(parsed)

    def visit(obj: Any) -> None:
        nonlocal video_object
        if video_object:
            return
        if isinstance(obj, dict):
            typ = obj.get("@type")
            if typ == "VideoObject" or (isinstance(typ, list) and "VideoObject" in typ):
                video_object = obj
                return
            graph = obj.get("@graph")
            if isinstance(graph, list):
                for child in graph:
                    visit(child)
            for child in obj.values():
                if isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(obj, list):
            for child in obj:
                visit(child)

    visit(items)
    if video_object:
        return {"video_object": video_object, "items_count": len(items)}
    return {"items": items[:5], "items_count": len(items)} if items else {}


def parse_webpage_metadata(html: str) -> Dict[str, Any]:
    parser = _MetadataHTMLParser()
    try:
        parser.feed(html or "")
    except Exception:
        pass

    meta = parser.meta
    out = empty_webpage_metadata(status="ok")
    out["og_title"] = _clean_text(meta.get("og:title") or "")
    out["og_description"] = _clean_text(meta.get("og:description") or "")
    out["meta_keywords"] = _keywords(meta.get("keywords") or "")
    out["canonical_url"] = _clean_text(parser.canonical_url)
    out["json_ld"] = _parse_json_ld(parser.json_ld_chunks)
    out["page_title"] = _clean_text(" ".join(parser.title_chunks))
    out["page_description"] = _clean_text(meta.get("description") or "")
    return out


def _load_cookiejar(cookie_file: str) -> http.cookiejar.MozillaCookieJar | None:
    if not cookie_file:
        return None
    jar = http.cookiejar.MozillaCookieJar()
    jar.load(str(Path(cookie_file).expanduser()), ignore_discard=True, ignore_expires=True)
    return jar


def fetch_webpage_metadata(url: str, *, cookie_file: str = "", timeout: int = 20) -> Dict[str, Any]:
    if not url:
        return empty_webpage_metadata(status="failed", error="missing_url")

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; youtube-hq-url-analyzer/1.0; +metadata-only)",
        "Accept-Language": "en-US,en;q=0.8",
    }
    cookie_status = ""
    try:
        jar = _load_cookiejar(cookie_file) if cookie_file else None
    except Exception as exc:
        jar = None
        cookie_status = f"cookie_load_failed_fallback_no_cookie:{type(exc).__name__}"

    try:
        try:
            import requests  # type: ignore

            session = requests.Session()
            if jar is not None:
                session.cookies = jar  # type: ignore[assignment]
            resp = session.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            html = resp.text
        except ImportError:
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)) if jar is not None else urllib.request.build_opener()
            req = urllib.request.Request(url, headers=headers)
            with opener.open(req, timeout=timeout) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        out = parse_webpage_metadata(html)
        if cookie_status:
            out["cookie_status"] = cookie_status
        return out
    except (urllib.error.URLError, TimeoutError, Exception) as exc:
        out = empty_webpage_metadata(status="failed", error=f"{type(exc).__name__}: {str(exc)[:240]}")
        if cookie_status:
            out["cookie_status"] = cookie_status
        return out
