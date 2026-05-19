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
        "available_format_heights": [1440, 2160],
        "duration_seconds": 45,
        "published_at": date.today().isoformat(),
        "title": "Luxury product commercial 4K",
    }
    row.update(overrides)
    return row


def _video_id(prefix: str) -> str:
    return (prefix[:1] + str(time.time_ns())[-10:])[:11]


class OfflineSmoke(unittest.TestCase):
    def test_offline_pipeline_outputs_review_and_dedupe_files(self) -> None:
        vid1 = _video_id("A")
        vid2 = _video_id("B")
        with tempfile.TemporaryDirectory() as d:
            candidates = Path(d) / "candidates.jsonl"
            _write_jsonl(
                candidates,
                [
                    {
                        "video_url": f"https://www.youtube.com/watch?v={vid1}",
                        "canonical_url": f"https://www.youtube.com/watch?v={vid1}",
                        "title": "Luxury perfume product film 4K commercial",
                        "channel_title": "Luxury Official",
                        "brand": "Test Brand",
                        "query_used": "youtube search page",
                        **_hard_ok(),
                    },
                    _hard_ok(
                        video_url=f"https://www.youtube.com/watch?v={vid1}",
                        canonical_url=f"https://www.youtube.com/watch?v={vid1}",
                        title="Duplicate luxury film 4K",
                    ),
                    {
                        "video_url": f"https://youtu.be/{vid2}",
                        "canonical_url": f"https://youtu.be/{vid2}",
                        "title": "Jewelry campaign film 4K",
                        **_hard_ok(duration_seconds=52),
                    },
                ],
            )
            _run(
                [
                    "collect",
                    "--offline-candidates",
                    str(candidates),
                    "--max-entries",
                    "2",
                ]
            )
        tasks = sorted((ROOT / "output" / "tasks").glob("task_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        self.assertTrue(tasks)
        latest = tasks[0]
        self.assertTrue((latest / "review_sheet.csv").exists())
        self.assertTrue((latest / "collected_urls.jsonl").exists())
        self.assertTrue((latest / "dedupe_report.json").exists())
        self.assertTrue((latest / "duplicates.jsonl").exists())
        self.assertTrue((latest / "run_summary.md").exists())
        summary = json.loads((latest / "run_summary.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(summary["collected_url_count"], 3)
        self.assertGreaterEqual(summary["duplicate_count"], 1)

    def test_pipeline_cleans_malformed_terminal_unicode(self) -> None:
        from src.core.pipeline import run_new_task
        from src.core.task import PipelineOptions

        with tempfile.TemporaryDirectory() as d:
            candidates = Path(d) / "candidates.jsonl"
            _write_jsonl(
                candidates,
                [
                    {
                        "video_url": "https://www.youtube.com/watch?v=AbCdEfGhI01",
                        **_hard_ok(),
                    }
                ],
            )
            result = run_new_task(
                "我要找奢侈品广告\udce3，要求 4K",
                PipelineOptions(offline_candidates_path=candidates),
            )
        text = (result.task_dir / "user_request.txt").read_text(encoding="utf-8")
        self.assertIn("我要找奢侈品广告", text)
        self.assertNotIn("\udce3", text)

    def test_pipeline_drops_hard_constraint_failures(self) -> None:
        from src.core.pipeline import run_new_task
        from src.core.task import PipelineOptions

        old_date = (date.today() - timedelta(days=900)).isoformat()
        with tempfile.TemporaryDirectory() as d:
            candidates = Path(d) / "candidates.jsonl"
            _write_jsonl(
                candidates,
                [
                    {"video_url": f"https://www.youtube.com/watch?v={_video_id('G')}", **_hard_ok()},
                    {"video_url": f"https://www.youtube.com/watch?v={_video_id('L')}", **_hard_ok(max_format_height=720, available_format_heights=[720])},
                    {"video_url": f"https://www.youtube.com/watch?v={_video_id('D')}", **_hard_ok(duration_seconds=610)},
                    {"video_url": f"https://www.youtube.com/watch?v={_video_id('O')}", **_hard_ok(published_at=old_date)},
                    {"video_url": f"https://www.youtube.com/watch?v={_video_id('R')}", **_hard_ok(title="Luxury bag review 4K")},
                    {"video_url": f"https://www.youtube.com/watch?v={_video_id('M')}", "title": "Missing metadata"},
                ],
            )
            result = run_new_task("YouTube 4K 60 秒以内两年内", PipelineOptions(offline_candidates_path=candidates))
        self.assertEqual(result.summary["collected_url_count"], 6)
        self.assertEqual(result.summary["hard_constraint_rejected_count"], 5)
        self.assertEqual(result.summary["final_count"], 1)
        stats = result.summary["hard_constraint_reject_stats"]
        self.assertGreaterEqual(stats["not_4k"], 1)
        self.assertGreaterEqual(stats["duration_too_long"], 1)
        self.assertGreaterEqual(stats["published_too_old"], 1)
        self.assertGreaterEqual(stats["negative_keyword:review"], 1)
        self.assertGreaterEqual(stats["missing_4k_evidence"], 1)

    def test_youtube_search_entry_to_candidate(self) -> None:
        from src.youtube_collect import _candidate_from_entry

        row = _candidate_from_entry({"id": "AbCdEfGhI01", "title": "Test"}, search_url="https://www.youtube.com/results?search_query=test")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["video_url"], "https://www.youtube.com/watch?v=AbCdEfGhI01")

    def test_local_dedupe_marks_current_duplicates(self) -> None:
        from src.core.dedupe import dedupe_records

        stamp = str(time.time_ns())[-9:]
        vid = f"AbC{stamp}"[:11].ljust(11, "X")
        unique, duplicates, stats = dedupe_records(
            [
                {"video_url": f"https://www.youtube.com/watch?v={vid}"},
                {"video_url": f"https://youtu.be/{vid}"},
                {"video_url": ""},
            ],
            exclude_task_dir=ROOT / "output" / "tasks" / "not-a-real-task",
        )
        self.assertEqual(len(unique), 1)
        self.assertEqual(len(duplicates), 2)
        self.assertEqual(stats["duplicates"], 2)
        self.assertEqual(duplicates[0]["duplicate_reason"], "duplicate_in_current_task")
        self.assertEqual(duplicates[1]["duplicate_reason"], "missing_url")

    def test_cli_help_no_longer_exposes_removed_search_stacks(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "src.main", "--help"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        self.assertIn("collect", proc.stdout)
        self.assertNotIn("OpenRouter", proc.stdout)
        self.assertNotIn("Vimeo", proc.stdout)
        self.assertNotIn("YOUTUBE_API_KEY", proc.stdout)


if __name__ == "__main__":
    unittest.main()
