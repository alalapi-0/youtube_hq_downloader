"""Execute only in the fixed Linux offline namespace."""
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest

sys.path.insert(0, '/project')
assert os.environ['HOME'] == '/work/home'
assert not any(k.startswith(('YT_', 'OPENAI_', 'ANTHROPIC_', 'AWS_', 'SSH_')) for k in os.environ)
assert not Path('/home/alalapi/.codex').exists()
assert not Path('/project/legacy').exists()
assert not Path('/project/.env').exists()
assert not Path('/project/urls.txt').exists()
for target in [Path('/project/src/main.py'), Path(sys.prefix) / 'pyvenv.cfg']:
    try:
        with target.open('ab'):
            raise AssertionError('Source/runtime unexpectedly writable')
    except OSError:
        pass
# Fresh namespace has no external interface; no DNS/connection is attempted.
assert socket.if_nameindex() == [(1, 'lo')]
versions = {name: importlib.metadata.version(name) for name in ('yt-dlp', 'PyYAML', 'isodate')}
import src.console.app
help_result = subprocess.run([sys.executable, '-B', '-m', 'src.main', '--help'],
                             capture_output=True, text=True, timeout=30)
assert help_result.returncode == 0 and 'collect' in help_result.stdout
if sys.argv[1] == 'test':
    suite = unittest.defaultTestLoader.discover('/project/tests', pattern='test_*.py')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    assert result.wasSuccessful(), 'Original offline tests failed'
    assert result.testsRun == 11, result.testsRun
print(json.dumps({'status': 'PASS', 'action': sys.argv[1], 'dependencies': versions,
                  'netns': os.readlink('/proc/self/ns/net'), 'interfaces': socket.if_nameindex(),
                  'test_count': 11 if sys.argv[1] == 'test' else 0}))
