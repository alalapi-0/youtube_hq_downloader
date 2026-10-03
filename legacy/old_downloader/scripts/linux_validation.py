"""Runs only inside the fixed offline verification namespace."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.path[:0] = ['/project', '/project/scripts']
import common
import download_by_plan
import probe_best_plan


def run(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (command, result.stdout, result.stderr)
    return result.stdout


def main():
    assert sys.version_info[:2] == (3, 12)
    assert os.environ['HOME'] == '/work/home'
    assert not any(k.startswith(('YT_', 'OPENAI_', 'ANTHROPIC_', 'AWS_', 'SSH_')) for k in os.environ)
    assert not Path('/project/state').exists() and not Path('/project/urls.txt').exists()
    assert not Path('/home/alalapi/.codex').exists()
    # Source and dependency mounts are actually read-only.
    for path in [Path('/project/scripts/common.py'), Path(sys.prefix) / 'pyvenv.cfg']:
        try:
            with path.open('ab'):
                raise AssertionError('Readonly mount unexpectedly writable')
        except OSError:
            pass
    version = run([sys.executable, '-m', 'yt_dlp', '--ignore-config', '--version']).strip()
    print('Installed yt-dlp CLI version:', version)
    assert version == '2026.08.19' and importlib.metadata.version('yt-dlp') == '2026.8.19'
    assert 'Usage:' in run([sys.executable, '-m', 'yt_dlp', '--ignore-config', '--help'])
    assert common.ensure_ytdlp_installed(auto_install=False) == [sys.executable, '-m', 'yt_dlp']
    assert common.detect_all_browsers() == []
    downloads = Path('/work/downloads')
    downloads.mkdir()
    video = downloads / 'synthetic.mp4'
    run(['/usr/bin/ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
         'color=c=blue:s=1280x720:r=24', '-t', '1', '-c:v', 'mpeg4', str(video)])
    sha = hashlib.sha256(video.read_bytes()).hexdigest()
    info = common.ffprobe_video_info(video)
    assert info and info['width'] == 1280 and info['height'] == 720
    assert 0 < info['duration'] <= 2 and info['size_bytes'] > 0
    assert common.validate_downloaded_file(video, 720)[0]
    assert not common.validate_downloaded_file(video, 1080)[0]
    cache = Path('/work/synthetic-cache.json')
    key = common.cache_key_for_url('https://example.invalid/synthetic')
    data = {key: {'height': 720, 'mode': 'single', 'yt_client': 'web'}}
    common.save_json(cache, data)
    assert common.load_json(cache, {}) == data
    assert probe_best_plan.video_codec_rank('av01') > probe_best_plan.video_codec_rank('avc1')
    assert len(probe_best_plan.build_youtube_probe_strategies(None, {})) == 5
    plan = {'url': 'https://example.invalid/synthetic', 'id': 'synthetic',
            'format_expr': '18', 'yt_client': 'web', 'height': 720, 'mode': 'single'}
    command = download_by_plan.build_download_cmd([sys.executable, '-m', 'yt_dlp'], plan, {}, 'auto')
    assert '--cookies-from-browser' not in command
    assert plan['url'] in command
    common.touch_plan_verified(plan)
    assert common.plan_is_usable(plan, 720, 3600)
    common.mark_plan_status(plan, common.PLAN_STATUS_INVALID, 'synthetic invalidation')
    assert not common.plan_is_usable(plan, 720, 3600)
    candidate = probe_best_plan.choose_candidate_from_info({'formats': [
        {'format_id': 'synthetic-video', 'height': 720, 'width': 1280,
         'vcodec': 'vp9', 'acodec': 'none', 'ext': 'webm'},
        {'format_id': 'synthetic-audio', 'vcodec': 'none', 'acodec': 'opus', 'ext': 'webm'},
    ]}, 720)
    assert candidate['mode'] == 'adaptive'
    assert candidate['format_expr'] == 'synthetic-video+synthetic-audio'
    for name in ['probe_best_plan.py', 'download_by_plan.py']:
        assert 'usage:' in run([sys.executable, '-B', '/project/scripts/' + name, '--help'])
    if sys.argv[1] == 'test':
        entries = ['test_common.py', 'test_common_full.py', 'test_probe_best_plan.py',
                   'test_ffprobe.py', 'test_hub_metric_snapshot_entry.py', 'test_linux_runtime.py']
        for entry in entries:
            result = subprocess.run([sys.executable, '-B', '/project/' + entry],
                                    capture_output=True, text=True, timeout=30)
            print(entry, 'exit', result.returncode)
            print(result.stdout, end='')
            print(result.stderr, end='')
            assert result.returncode == 0, entry
            if entry == 'test_ffprobe.py':
                assert '验证 720p: True' in result.stdout and '1280x720' in result.stdout
            if entry == 'test_probe_best_plan.py':
                assert 'Token client priority OK' in result.stdout
            if entry == 'test_hub_metric_snapshot_entry.py':
                assert 'Ran 3 tests' in result.stderr
    assert hashlib.sha256(video.read_bytes()).hexdigest() == sha
    print(json.dumps({'check': 'PASS', 'python': sys.version.split()[0], 'yt_dlp': version,
                      'synthetic_media': info, 'media_sha256': sha,
                      'netns': os.readlink('/proc/self/ns/net'), 'action': sys.argv[1]}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
