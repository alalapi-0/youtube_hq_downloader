from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
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


class OfflineSmoke(unittest.TestCase):
    def test_product_offline_pipeline_outputs_review_and_dedupe_files(self) -> None:
        now = str(time.time_ns())[-10:]
        vid1 = f"a{now}"
        vid2 = f"b{now}"
        with tempfile.TemporaryDirectory() as d:
            candidates = Path(d) / "candidates.jsonl"
            _write_jsonl(
                candidates,
                [
                    {
                        "video_url": f"https://www.youtube.com/watch?v={vid1}",
                        "canonical_url": f"https://www.youtube.com/watch?v={vid1}",
                        "title": "Luxury perfume product film 4K macro studio commercial",
                        "channel_title": "Luxury Official",
                        "brand": "Test Brand",
                        "query_used": "luxury product film 4k",
                    },
                    {
                        "video_url": f"https://www.youtube.com/watch?v={vid1}",
                        "canonical_url": f"https://www.youtube.com/watch?v={vid1}",
                        "title": "Duplicate luxury film",
                    },
                    {
                        "video_url": f"https://www.youtube.com/watch?v={vid2}",
                        "canonical_url": f"https://www.youtube.com/watch?v={vid2}",
                        "title": "Jewelry campaign film 4K",
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

    def test_web_url_parser_accepts_video_urls_only(self) -> None:
        from src.llm.web_url_scout import _parse_candidates

        rows = _parse_candidates(
            json.dumps(
                {
                    "candidates": [
                        {"url": "https://vimeo.com/123456789", "title": "Dior product film"},
                        {"url": "https://www.youtube.com/watch?v=AbCdEfGhIj1", "title": "Brand commercial"},
                        {"url": "https://example.com/not-a-video", "title": "No"},
                    ]
                }
            )
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["source_platform"], "vimeo")
        self.assertEqual(rows[1]["source_platform"], "youtube")

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
