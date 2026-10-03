"""The Hub snapshot reader must stay explicit and refuse unsafe roots without any Hub checkout."""
import importlib.util
import unittest
from pathlib import Path

ENTRY = Path(__file__).resolve().parent / "scripts/export_hub_metric_snapshot.py"


def load_entry():
    spec = importlib.util.spec_from_file_location("youtube_hub_export", ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HubSnapshotEntryTests(unittest.TestCase):
    def test_entry_requires_both_explicit_roots(self):
        module = load_entry()
        for argv in ([], ["--hub-root", str(ENTRY.parent)], ["--project-root", str(ENTRY.parent)]):
            with self.assertRaises(SystemExit) as exit_info:
                module.main(argv)
            self.assertEqual(exit_info.exception.code, 2)

    def test_entry_refuses_symlinked_or_absent_project_root(self):
        module = load_entry()
        hub_root = Path(self._tempdir())
        project = hub_root / "project"
        project.mkdir()
        alias = hub_root / "alias"
        alias.symlink_to(project, target_is_directory=True)
        self.assertEqual(module.main(["--hub-root", str(hub_root), "--project-root", str(alias)]), 2)
        self.assertEqual(
            module.main(["--hub-root", str(hub_root), "--project-root", str(hub_root / "absent")]),
            2,
        )

    def test_missing_hub_root_is_reported_not_guessed(self):
        module = load_entry()
        with self.assertRaises(FileNotFoundError):
            module.main(["--hub-root", "/tmp/youtube-absent-hub", "--project-root", "/tmp"])

    def _tempdir(self):
        import tempfile
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return temporary.name


if __name__ == "__main__":
    unittest.main()
