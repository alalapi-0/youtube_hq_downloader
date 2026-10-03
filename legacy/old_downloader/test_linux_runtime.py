"""Linux behavior against synthetic homes and mocked dependency discovery."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import common
from scripts.linux_verify import canonical


class LinuxRuntimeTests(unittest.TestCase):
    def test_external_root_exact_canonical(self):
        self.assertEqual(canonical('/work', Path('/work')), Path('/work'))

    def test_external_root_wrong_or_relative_rejected(self):
        for value in ['work', '/etc', '/work/../work', '/work/absent']:
            with self.assertRaises(ValueError):
                canonical(value, Path('/work'))

    def test_symlink_root_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            alias = root / 'alias'
            alias.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                canonical(str(alias), alias)

    def test_missing_root_rejected(self):
        root = Path('/work/missing-runtime')
        with self.assertRaises(ValueError):
            canonical(str(root), root)

    def test_linux_missing_ytdlp_never_installs(self):
        with patch.object(common.sys, 'platform', 'linux'), \
             patch.object(common, 'python_module_ytdlp_cmd', return_value=None), \
             patch.object(common, 'path_ytdlp_cmd', return_value=None), \
             patch.object(common, 'brew_ytdlp_cmd', return_value=None), \
             patch.object(common.subprocess, 'run') as installer:
            self.assertIsNone(common.ensure_ytdlp_installed())
            installer.assert_not_called()

    def test_linux_missing_ffmpeg_never_installs(self):
        with patch.object(common.sys, 'platform', 'linux'), \
             patch.object(common, 'which', return_value=None), \
             patch.object(common.subprocess, 'run') as installer:
            self.assertFalse(common.ensure_ffmpeg_and_ffprobe())
            installer.assert_not_called()

    def test_mac_dependency_behavior_preserved_mocked(self):
        with patch.object(common.sys, 'platform', 'darwin'), \
             patch.object(common, 'python_module_ytdlp_cmd', return_value=None), \
             patch.object(common, 'path_ytdlp_cmd', return_value=None), \
             patch.object(common, 'brew_ytdlp_cmd', return_value=None), \
             patch.object(common, 'which', return_value='/mock/brew'), \
             patch.object(common.subprocess, 'run') as installer:
            common.ensure_ytdlp_installed()
            self.assertEqual(installer.call_count, 2)
            self.assertEqual(installer.call_args_list[0].args[0], ['brew', 'install', 'yt-dlp'])

    def test_linux_browser_presence_synthetic_home(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(common.Path, 'home', return_value=Path(directory)), \
             patch.object(common.sys, 'platform', 'linux'):
            self.assertEqual(common.detect_all_browsers(), [])
            (Path(directory) / '.config/google-chrome').mkdir(parents=True)
            (Path(directory) / '.mozilla/firefox').mkdir(parents=True)
            self.assertEqual(common.detect_all_browsers(), ['chrome', 'firefox'])
            self.assertEqual(common.detect_cookies_browser(), 'chrome')

    def test_mac_browser_presence_synthetic_home(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(common.Path, 'home', return_value=Path(directory)), \
             patch.object(common.sys, 'platform', 'darwin'):
            (Path(directory) / 'Library/Application Support/Microsoft Edge').mkdir(parents=True)
            self.assertEqual(common.detect_all_browsers(), ['edge'])

    def test_clean_environment(self):
        self.assertEqual(os.environ['HOME'], '/work/home')
        self.assertFalse(any(k.startswith(('YT_', 'OPENAI_', 'AWS_', 'SSH_')) for k in os.environ))

    def test_no_live_data(self):
        for name in ['state', 'downloads', 'urls.txt', '.venv']:
            self.assertFalse((Path('/project') / name).exists())


if __name__ == '__main__':
    unittest.main()
