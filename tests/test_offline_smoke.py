from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["OPENROUTER_API_KEY"] = ""
    return subprocess.run(
        [sys.executable, "-m", "src.main", *args],
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _hard_ok(**overrides: object) -> dict:
    row = {
        "max_format_height": 2160,
        "duration_seconds": 45,
        "published_at": date.today().isoformat(),
        "resolution_evidence": "4K / UHD",
        "duration_evidence": "Duration 0:45",
        "date_evidence": "Published recently",
    }
    row.update(overrides)
    return row


class OfflineSmoke(unittest.TestCase):
    def test_product_offline_pipeline_outputs_review_and_dedupe_files(self) -> None:
        now = str(time.time_ns())[-10:]
        vid1 = f"88{now}"
        vid2 = f"99{now}"
        with tempfile.TemporaryDirectory() as d:
            candidates = Path(d) / "candidates.jsonl"
            _write_jsonl(
                candidates,
                [
                    {
                        "video_url": f"https://vimeo.com/{vid1}",
                        "canonical_url": f"https://vimeo.com/{vid1}",
                        "title": "Luxury perfume product film 4K macro studio commercial",
                        "channel_title": "Luxury Official",
                        "brand": "Test Brand",
                        "query_used": "luxury product film 4k",
                        **_hard_ok(),
                    },
                    _hard_ok(
                        video_url=f"https://vimeo.com/{vid1}",
                        canonical_url=f"https://vimeo.com/{vid1}",
                        title="Duplicate luxury film",
                    ),
                    {
                        "video_url": f"https://vimeo.com/{vid2}",
                        "canonical_url": f"https://vimeo.com/{vid2}",
                        "title": "Jewelry campaign film 4K",
                        **_hard_ok(duration_seconds=52),
                    },
                ],
            )
            _run(
                [
                    "run-task",
                    "--request",
                    "我要找高端奢侈品官方广告，要求 4K，排除 review 和 unboxing",
                    "--offline-candidates",
                    str(candidates),
                    "--max-results",
                    "2",
                ]
            )
        task_root = ROOT / "output" / "tasks"
        tasks = sorted(task_root.glob("task_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        self.assertTrue(tasks)
        latest = tasks[0]
        self.assertTrue((latest / "review_sheet.csv").exists())
        self.assertTrue((latest / "llm_found_urls.jsonl").exists())
        self.assertTrue((latest / "dedupe_report.json").exists())
        self.assertTrue((latest / "duplicates.jsonl").exists())
        self.assertTrue((latest / "run_summary.md").exists())
        summary = json.loads((latest / "run_summary.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(summary["total_candidates"], 3)
        self.assertGreaterEqual(summary["duplicate_count"], 1)

    def test_product_pipeline_cleans_malformed_terminal_unicode(self) -> None:
        from src.core.pipeline import run_new_task
        from src.core.task import PipelineOptions

        with tempfile.TemporaryDirectory() as d:
            candidates = Path(d) / "candidates.jsonl"
            _write_jsonl(
                candidates,
                [
                    {
                        "video_url": "https://vimeo.com/999000111222",
                        "title": "Luxury product film 4K",
                        **_hard_ok(),
                    }
                ],
            )
            result = run_new_task(
                "我要找奢侈品广告\udce3，要求 4K",
                PipelineOptions(
                    offline_candidates_path=candidates,
                    max_results_per_query=1,
                ),
            )
        text = (result.task_dir / "user_request.txt").read_text(encoding="utf-8")
        self.assertIn("我要找奢侈品广告", text)
        self.assertNotIn("\udce3", text)

    def test_web_url_parser_accepts_vimeo_video_urls_only(self) -> None:
        from src.llm.web_url_scout import _parse_candidates

        rows = _parse_candidates(
            json.dumps(
                {
                    "candidates": [
                        {"url": "https://vimeo.com/123456789", "title": "Dior product film"},
                        {"url": "https://www.youtube.com/watch?v=AbCdEfGhIj1", "title": "Brand commercial"},
                        {"url": "https://youtu.be/AbCdEfGhIj1", "title": "Brand commercial short URL"},
                        {"url": "https://example.com/not-a-video", "title": "No"},
                    ]
                }
            )
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_platform"], "vimeo")

    def test_pipeline_drops_non_vimeo_candidates(self) -> None:
        from src.core.pipeline import run_new_task
        from src.core.task import PipelineOptions

        stamp = str(time.time_ns())[-10:]
        with tempfile.TemporaryDirectory() as d:
            candidates = Path(d) / "candidates.jsonl"
            _write_jsonl(
                candidates,
                [
                    {"video_url": f"https://vimeo.com/77{stamp}", "title": "Vimeo luxury product film 4K", **_hard_ok()},
                    {"video_url": "https://www.youtube.com/watch?v=AbCdEfGhIj1", "title": "Forbidden platform"},
                ],
            )
            result = run_new_task(
                "我要找 Vimeo 奢侈品广告",
                PipelineOptions(offline_candidates_path=candidates),
            )
        self.assertEqual(result.summary["total_candidates"], 1)
        self.assertEqual(result.summary["non_vimeo_dropped"], 1)

    def test_pipeline_drops_hard_constraint_failures(self) -> None:
        from src.core.pipeline import run_new_task
        from src.core.task import PipelineOptions

        stamp = str(time.time_ns())[-8:]
        old_date = (date.today() - timedelta(days=900)).isoformat()
        with tempfile.TemporaryDirectory() as d:
            candidates = Path(d) / "candidates.jsonl"
            _write_jsonl(
                candidates,
                [
                    {"video_url": f"https://vimeo.com/10{stamp}", "title": "Good Vimeo 4K product film", **_hard_ok()},
                    {"video_url": f"https://vimeo.com/20{stamp}", "title": "Low res Vimeo product film 720p", **_hard_ok(max_format_height=720, resolution_evidence="720p")},
                    {"video_url": f"https://vimeo.com/30{stamp}", "title": "Long Vimeo 4K product film", **_hard_ok(duration_seconds=610, duration_evidence="Duration 10:10")},
                    {"video_url": f"https://vimeo.com/40{stamp}", "title": "Old Vimeo 4K product film", **_hard_ok(published_at=old_date, date_evidence=f"Published {old_date}")},
                    {"video_url": f"https://vimeo.com/50{stamp}", "title": "Missing metadata Vimeo product film"},
                ],
            )
            result = run_new_task(
                "我要找 Vimeo 4K 60 秒以内两年内的广告",
                PipelineOptions(offline_candidates_path=candidates),
            )
        self.assertEqual(result.summary["total_candidates"], 5)
        self.assertEqual(result.summary["hard_constraint_rejected_count"], 4)
        self.assertEqual(result.summary["final_count"], 1)
        stats = result.summary["hard_constraint_reject_stats"]
        self.assertGreaterEqual(stats["not_4k"], 1)
        self.assertGreaterEqual(stats["duration_too_long"], 1)
        self.assertGreaterEqual(stats["published_too_old"], 1)
        self.assertGreaterEqual(stats["missing_4k_evidence"], 1)
        self.assertGreaterEqual(stats["missing_duration"], 1)
        self.assertGreaterEqual(stats["missing_publish_date"], 1)

    def test_local_dedupe_marks_current_duplicates(self) -> None:
        from src.core.dedupe import dedupe_records

        stamp = str(time.time_ns())[-12:]
        unique, duplicates, stats = dedupe_records(
            [
                {"video_url": f"https://vimeo.com/{stamp}"},
                {"video_url": f"https://vimeo.com/{stamp}"},
                {"video_url": ""},
            ],
            exclude_task_dir=ROOT / "output" / "tasks" / "not-a-real-task",
        )
        self.assertEqual(len(unique), 1)
        self.assertEqual(len(duplicates), 2)
        self.assertEqual(stats["duplicates"], 2)
        self.assertEqual(duplicates[0]["duplicate_reason"], "duplicate_in_current_task")
        self.assertEqual(duplicates[1]["duplicate_reason"], "missing_url")

    def test_cli_help_no_longer_exposes_old_search_stack(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "src.main", "--help"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        self.assertIn("run-task", proc.stdout)
        self.assertNotIn("yt-dlp", proc.stdout)
        self.assertNotIn("YOUTUBE_API_KEY", proc.stdout)
        self.assertNotIn("probe-format", proc.stdout)


if __name__ == "__main__":
    unittest.main()
