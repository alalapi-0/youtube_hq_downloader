from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str], cwd: Path = ROOT) -> None:
    env = os.environ.copy()
    env["OPENROUTER_API_KEY"] = ""
    env["YOUTUBE_API_KEY"] = ""
    subprocess.run([sys.executable, "-m", "src.main", *args], cwd=cwd, env=env, check=True)


class OfflineSmoke(unittest.TestCase):
    def test_plan_demo_writes_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            outp = Path(d) / "plan.yaml"
            _run(["plan", "--input", "examples/search_tasks.demo.yaml", "--output", str(outp), "--use-llm", "false"])
            text = outp.read_text(encoding="utf-8")
            self.assertTrue(outp.exists())
            self.assertIn("tasks:", text)

    def test_product_offline_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            task_id = "task_20990101_001"
            _run(
                [
                    "run-task",
                    "--request",
                    "我要找高端奢侈品官方广告，要求 4K，排除 review 和 unboxing",
                    "--offline",
                    "true",
                    "--offline-candidates",
                    "examples/sample_candidates.jsonl",
                    "--skip-format-probe",
                    "true",
                    "--ai",
                    "false",
                    "--max-results",
                    "2",
                ]
            )
            task_root = ROOT / "output" / "tasks"
            tasks = sorted(task_root.glob("task_*"), key=lambda p: p.stat().st_mtime, reverse=True)
            self.assertTrue(tasks)
            latest = tasks[0]
            self.assertTrue((latest / "review_sheet.csv").exists())
            self.assertTrue((latest / "run_summary.md").exists())

    def test_ytdlp_search_fallback_parses_entries(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            bin_dir = Path(d) / "bin"
            bin_dir.mkdir()
            fake = bin_dir / "yt-dlp"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import json\n"
                "print(json.dumps({'entries': [{'id': 'abc123XYZ90', 'title': 'Dior product film 4K', 'channel': 'Dior', 'duration': 60, 'webpage_url': 'https://www.youtube.com/watch?v=abc123XYZ90'}]}))\n",
                encoding="utf-8",
            )
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            prev_path = os.environ.get("PATH", "")
            os.environ["PATH"] = str(bin_dir) + os.pathsep + prev_path
            try:
                from src.youtube_search import execute_search_plan_ytdlp

                rows, warnings = execute_search_plan_ytdlp(
                    {
                        "global_rules": {"max_results_per_keyword": 1},
                        "tasks": [{"id": "t1", "keywords": ["luxury ad"], "brands": []}],
                    }
                )
            finally:
                os.environ["PATH"] = prev_path
            self.assertFalse(warnings)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["video_id"], "abc123XYZ90")

    def test_offline_fixture_pipeline(self) -> None:
        prev = os.environ.get("SKIP_FORMAT_PROBE")
        os.environ["SKIP_FORMAT_PROBE"] = "1"
        try:
            with tempfile.TemporaryDirectory() as d:
                base = Path(d)
                enriched = base / "enriched.jsonl"
                probed = base / "probed.jsonl"
                ok = base / "rule_ok.jsonl"
                rej = base / "rule_rej.jsonl"
                llm_ok = base / "llm_ok.jsonl"
                llm_rej = base / "llm_rej.jsonl"
                export_dir = base / "export"

                _run(["enrich", "--input", "data/fixtures/sample_raw.jsonl", "--output", str(enriched)])
                _run(["probe-format", "--input", str(enriched), "--output", str(probed)])
                _run(["filter", "--input", str(probed), "--output", str(ok), "--rejected", str(rej)])
                _run(["llm-filter", "--input", str(ok), "--output", str(llm_ok), "--rejected", str(llm_rej), "--use-llm", "false"])
                _run(
                    [
                        "export",
                        "--input",
                        str(llm_ok),
                        "--format",
                        "markdown",
                        "--output-dir",
                        str(export_dir),
                        "--rejected-rule",
                        str(rej),
                        "--rejected-llm",
                        str(llm_rej),
                    ]
                )

                md = export_dir / "markdown" / "filtered_urls.md"
                self.assertTrue(md.exists())
                self.assertIn("Export statistics", md.read_text(encoding="utf-8"))
        finally:
            if prev is None:
                os.environ.pop("SKIP_FORMAT_PROBE", None)
            else:
                os.environ["SKIP_FORMAT_PROBE"] = prev


if __name__ == "__main__":
    unittest.main()
