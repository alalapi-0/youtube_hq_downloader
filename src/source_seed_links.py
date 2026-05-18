from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import quote_plus


def _as_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, tuple):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        raw = value.replace("，", ",").replace("、", ",").replace(";", ",")
        return [x.strip() for x in raw.split(",") if x.strip()]
    return []


def _expanded_queries(plan: Dict[str, Any], *, max_queries: int = 120) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen: set[str] = set()
    tasks = plan.get("tasks") if isinstance(plan.get("tasks"), list) else []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id") or "")
        category = str(task.get("category") or "")
        subcategory = str(task.get("subcategory") or "")
        keywords = _as_list(task.get("keywords"))
        brands = _as_list(task.get("brands"))
        for keyword in keywords:
            candidates = [keyword]
            candidates.extend(f"{brand} {keyword}" for brand in brands)
            for query in candidates:
                norm = query.lower()
                if not query or norm in seen:
                    continue
                seen.add(norm)
                rows.append(
                    {
                        "query": query,
                        "task_id": task_id,
                        "category": category,
                        "subcategory": subcategory,
                    }
                )
                if len(rows) >= max_queries:
                    return rows
    return rows


def build_seed_link_rows(plan: Dict[str, Any], *, max_queries: int = 120) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for item in _expanded_queries(plan, max_queries=max_queries):
        query = item["query"]
        q = quote_plus(query)
        site_vimeo_q = quote_plus(f"site:vimeo.com {query}")
        rows.extend(
            [
                {
                    **item,
                    "platform": "vimeo",
                    "search_type": "vimeo_search",
                    "url": f"https://vimeo.com/search?q={q}",
                    "notes": "Vimeo 站内搜索；优先点 Ads and Commercials / Videos / 4K 等筛选。",
                },
                {
                    **item,
                    "platform": "vimeo",
                    "search_type": "google_site_vimeo",
                    "url": f"https://www.google.com/search?q={site_vimeo_q}",
                    "notes": "Google site:vimeo.com 辅助找 Vimeo 视频页。",
                },
                {
                    **item,
                    "platform": "vimeo",
                    "search_type": "bing_site_vimeo",
                    "url": f"https://www.bing.com/search?q={site_vimeo_q}",
                    "notes": "Bing site:vimeo.com 辅助找 Vimeo 视频页。",
                },
                {
                    **item,
                    "platform": "youtube",
                    "search_type": "youtube_search",
                    "url": f"https://www.youtube.com/results?search_query={q}",
                    "notes": "YouTube 网页搜索入口；适合手动挑选后复制 URL。",
                },
            ]
        )
    return rows


def write_seed_links(rows: Iterable[Dict[str, str]], *, output_csv: Path, output_md: Path) -> None:
    materialized = list(rows)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    columns = ["platform", "search_type", "query", "url", "task_id", "category", "subcategory", "notes"]
    with output_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in materialized:
            writer.writerow({key: row.get(key, "") for key in columns})

    lines = [
        "# Search seed links",
        "",
        "这些链接用于自动搜索失败时的人工寻源。打开链接后手动筛选视频页 URL，再复制到 URL 分析流程。",
        "",
        "| # | 平台 | 类型 | 查询 | 链接 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for idx, row in enumerate(materialized, start=1):
        query = str(row.get("query") or "").replace("|", "\\|")
        url = str(row.get("url") or "")
        lines.append(f"| {idx} | {row.get('platform', '')} | {row.get('search_type', '')} | {query} | [打开]({url}) |")
    lines.append("")
    output_md.write_text("\n".join(lines), encoding="utf-8")
