#!/usr/bin/env python3
"""Fixed network-free Linux maintenance; never opens live application inputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

PROJECT = Path('/home/alalapi/Projects/youtube-hq-downloader')
RUNTIME = Path('/home/alalapi/Runtimes/youtube-hq-downloader/ad-url-scout-venv')
SCRATCH = Path('/home/alalapi/Temp/youtube-hq-downloader')


def canonical(path, expected):
    if not path.is_absolute() or path != expected or path.resolve() != path or not path.is_dir():
        raise ValueError('Missing or noncanonical dedicated path')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'test'), nargs='?', default='check')
    args = parser.parse_args()
    canonical(Path(__file__).absolute().parent.parent, PROJECT)
    canonical(RUNTIME, RUNTIME)
    canonical(SCRATCH, SCRATCH)
    if not (RUNTIME / 'bin/python').is_file() or not shutil.which('bwrap'):
        raise ValueError('Dedicated runtime/bwrap unavailable; no automatic installation')
    # Fixed source families contain code, product config, tests and a public fixture.
    names = []
    for family in ('src', 'tests'):
        for path in sorted((PROJECT / family).rglob('*')):
            if path.is_file() and path.suffix in ('.py', '.yaml'):
                if path.resolve() != path:
                    raise ValueError('Aliased source refused')
                names.append(path.relative_to(PROJECT).as_posix())
    names += ['scripts/linux_validation.py', 'config/app.yaml', 'config/labels.yaml']
    before = {name: hashlib.sha256((PROJECT / name).read_bytes()).hexdigest() for name in names}
    with tempfile.TemporaryDirectory(prefix='ad-scout-offline-', dir=SCRATCH) as temporary:
        base = Path(temporary)
        source = base / 'source'
        work = base / 'work'
        home = work / 'home'
        home.mkdir(parents=True, mode=0o700)
        for name in names:
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT / name, path)
        for directory in ('output', 'cache', 'data', 'logs'):
            (source / directory).mkdir(parents=True, exist_ok=True)
            (work / directory).mkdir(mode=0o700)
        command = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session',
                   '--clearenv', '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin',
                   '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64',
                   '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--dir', '/etc',
                   '--ro-bind', '/etc/ld.so.cache', '/etc/ld.so.cache',
                   '--ro-bind', str(RUNTIME), str(RUNTIME), '--ro-bind', str(source), '/project',
                   '--bind', str(work), '/work']
        for directory in ('output', 'cache', 'data', 'logs'):
            command += ['--bind', str(work / directory), '/project/' + directory]
        command += ['--chdir', '/project', '--setenv', 'HOME', '/work/home',
                    '--setenv', 'PATH', str(RUNTIME / 'bin') + ':/usr/bin:/bin',
                    '--setenv', 'LANG', 'C.UTF-8', '--setenv', 'TMPDIR', '/work',
                    '--setenv', 'PYTHONDONTWRITEBYTECODE', '1',
                    '--setenv', 'XDG_CONFIG_HOME', '/work/home/.config',
                    '--setenv', 'XDG_CACHE_HOME', '/work/home/.cache',
                    str(RUNTIME / 'bin/python'), '-I', '-B', '/project/scripts/linux_validation.py',
                    args.action]
        result = subprocess.run(command, env={'PATH': '/usr/bin:/bin', 'HOME': str(home),
                                              'LANG': 'C.UTF-8'}, capture_output=True, text=True, timeout=90)
        after = {name: hashlib.sha256((PROJECT / name).read_bytes()).hexdigest() for name in names}
        assert after == before
        receipt = {'action': args.action, 'exit': result.returncode, 'command': command,
                   'stdout': result.stdout, 'stderr': result.stderr,
                   'source_sha256': before, 'source_unchanged': True,
                   'host_netns': os.readlink('/proc/self/ns/net')}
        (SCRATCH / ('ad-scout-' + args.action + '.json')).write_text(json.dumps(receipt, indent=2) + '\n')
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr, end='')
        return result.returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, subprocess.TimeoutExpired) as error:
        print('Offline maintenance refused:', error)
        raise SystemExit(2)
