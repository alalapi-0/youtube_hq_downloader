#!/usr/bin/env python3
"""Fixed offline checks in a fresh network and filesystem namespace."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

OWNER = Path('/home/alalapi')
PROJECT = OWNER / 'Projects/youtube-hq-downloader/legacy/old_downloader'
RUNTIME = OWNER / 'Runtimes/youtube-hq-downloader'
SCRATCH = OWNER / 'Temp/youtube-hq-downloader'
FILES = (
    'scripts/common.py', 'scripts/probe_best_plan.py', 'scripts/download_by_plan.py',
    'scripts/export_hub_metric_snapshot.py', 'scripts/linux_validation.py', 'scripts/linux_verify.py',
    'test_common.py', 'test_common_full.py', 'test_probe_best_plan.py',
    'test_ffprobe.py', 'test_hub_metric_snapshot_entry.py', 'test_linux_runtime.py',
)


def canonical(value, required):
    path = Path(value)
    if not path.is_absolute() or path != required or path.resolve() != path:
        raise ValueError('Expected the canonical dedicated project path')
    if not path.is_dir():
        raise ValueError('Required directory is missing; prepare it explicitly')
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'test'), nargs='?', default='check')
    args = parser.parse_args(argv)
    canonical(str(Path(__file__).absolute().parent.parent), PROJECT)
    runtime = canonical(os.environ.get('YTHQ_RUNTIME_ROOT', str(RUNTIME)), RUNTIME)
    scratch = canonical(os.environ.get('YTHQ_SCRATCH_ROOT', str(SCRATCH)), SCRATCH)
    python = runtime / 'venv/bin/python'
    if not python.is_file() or not shutil.which('bwrap'):
        raise ValueError('Dedicated Python or bwrap missing; no automatic installation')
    before = {}
    for name in FILES:
        path = PROJECT / name
        if path.resolve() != path or not path.is_file():
            raise ValueError('Missing or aliased source: ' + name)
        before[name] = digest(path)
    # This faithful replica contains no live state, URL list, browser helper or media.
    with tempfile.TemporaryDirectory(prefix='offline-', dir=scratch) as temporary:
        base = Path(temporary)
        source = base / 'source'
        work = base / 'work'
        home = work / 'home'
        home.mkdir(parents=True, mode=0o700)
        source.mkdir(mode=0o700)
        for name in FILES:
            destination = source / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT / name, destination)
            assert digest(destination) == before[name]
        manifest = {'files': before, 'action': args.action}
        (scratch / 'last-source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        command = [
            '/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session',
            '--clearenv', '--ro-bind', '/usr', '/usr',
            '--symlink', 'usr/bin', '/bin', '--symlink', 'usr/lib', '/lib',
            '--symlink', 'usr/lib64', '/lib64', '--proc', '/proc', '--dev', '/dev',
            '--tmpfs', '/tmp', '--dir', '/etc',
            '--ro-bind', '/etc/ld.so.cache', '/etc/ld.so.cache',
            '--ro-bind', '/usr/lib/x86_64-linux-gnu/blas/libblas.so.3.12.0',
            '/etc/alternatives/libblas.so.3-x86_64-linux-gnu',
            '--ro-bind', '/usr/lib/x86_64-linux-gnu/lapack/liblapack.so.3.12.0',
            '/etc/alternatives/liblapack.so.3-x86_64-linux-gnu',
            '--ro-bind', str(runtime), str(runtime),
            '--ro-bind', str(source), '/project', '--bind', str(work), '/work',
            '--chdir', '/work', '--setenv', 'HOME', '/work/home',
            '--setenv', 'PATH', str(runtime / 'venv/bin') + ':/usr/bin:/bin',
            '--setenv', 'LANG', 'C.UTF-8', '--setenv', 'TMPDIR', '/work',
            '--setenv', 'PYTHONDONTWRITEBYTECODE', '1',
            '--setenv', 'XDG_CONFIG_HOME', '/work/home/.config',
            '--setenv', 'XDG_CACHE_HOME', '/work/home/.cache',
            str(python), '-I', '-B', '/project/scripts/linux_validation.py', args.action,
        ]
        host_netns = os.readlink('/proc/self/ns/net')
        clean = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'LANG': 'C.UTF-8'}
        result = subprocess.run(command, env=clean, capture_output=True, text=True, timeout=90)
        receipt = {'command': command, 'exit': result.returncode,
                   'stdout': result.stdout, 'stderr': result.stderr,
                   'host_netns': host_netns, 'source_manifest': before}
        for name in FILES:
            assert digest(PROJECT / name) == before[name]
            assert digest(source / name) == before[name]
        receipt['source_unchanged'] = True
        (scratch / ('last-' + args.action + '.json')).write_text(json.dumps(receipt, indent=2) + '\n')
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr, end='')
        return result.returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, subprocess.TimeoutExpired) as error:
        print('Linux check refused:', error)
        raise SystemExit(2)
