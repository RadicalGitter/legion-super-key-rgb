"""Adversarial regression checks; no desktop or keyboard access."""
import os
from pathlib import Path
import runpy
import signal
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
s = runpy.run_path(str(ROOT/'src/safety.py'))
SafeDir, run_command = s['SafeDir'], s['run_command']


def refuses(fn, expected=(OSError, ValueError)):
    try:
        fn()
    except expected:
        return
    raise AssertionError('Unsafe operation unexpectedly succeeded')

with tempfile.TemporaryDirectory(prefix='legion-safety-') as temp:
    root = Path(temp)
    victim = root/'victim'
    victim.write_bytes(b'KEEP')
    base = root/'home'
    base.mkdir()
    with SafeDir(base) as d:
        (base/'file').symlink_to(victim)
        refuses(lambda: d.write('file', b'BAD'))
        refuses(lambda: d.read('file'))
        refuses(lambda: d.lock('file').__enter__())
        (base/'ancestor').symlink_to(root, target_is_directory=True)
        refuses(lambda: d.write('ancestor/victim', b'BAD'))
        refuses(lambda: SafeDir(base/'ancestor'))
        (base/'hardlink').hardlink_to(victim)
        refuses(lambda: d.write('hardlink', b'BAD'))
        refuses(lambda: d.lock('hardlink').__enter__())
        os.mkfifo(base/'fifo')
        refuses(lambda: d.read('fifo'))
        d.write('valid', b'OLD')
        # Exception before rename leaves old contents and removes random temp.
        with patch('os.replace', side_effect=OSError('injected replacement failure')):
            refuses(lambda: d.write('valid', b'NEW'))
        assert d.read('valid')[0] == b'OLD'
        assert not list(base.glob('.legion-*'))
        # Predictable old temporary name cannot block a fresh random temporary.
        (base/'valid.install-tmp').write_text('stale')
        d.write('valid', b'NEW')
        assert d.read('valid')[0] == b'NEW'
        # A pinned directory continues to address the original inode after rename.
        base.rename(root/'moved')
        base.symlink_to(root, target_is_directory=True)
        d.write('victim', b'IN PINNED DIR')
        assert (root/'moved/victim').read_bytes() == b'IN PINNED DIR'
    assert victim.read_bytes() == b'KEEP'
    # Group-writable directories and invalid relative paths fail closed.
    unsafe = root/'unsafe'; unsafe.mkdir(); unsafe.chmod(0o770)
    refuses(lambda: SafeDir(unsafe))
    with SafeDir(root/'moved') as d:
        refuses(lambda: d.write('../escape', b'BAD'))
        with d.lock('busy'):
            begin = time.monotonic()
            refuses(lambda: d.lock('busy', timeout=.06).__enter__())
            assert time.monotonic()-begin < .5

# Shadowed PATH and Python environment never reach the verified child.
with patch.dict(os.environ, {'PATH':'/nonexistent', 'PYTHONPATH':'/nonexistent',
                            'LD_PRELOAD':'/nonexistent', 'EVIL':'yes'}):
    r = run_command(['/usr/bin/python3','-I','-c',
        'import os; assert "EVIL" not in os.environ; assert "LD_PRELOAD" not in os.environ; assert os.environ["PATH"] == "/usr/bin"; print("closed")'])
    assert r.stdout.strip() == 'closed'
refuses(lambda: run_command(['python3','-V']))
refuses(lambda: run_command(['/tmp/shadow-systemctl']), ValueError)
start = time.monotonic()
refuses(lambda: run_command(['/usr/bin/python3','-I','-c','while True: print("x"*4096, flush=True)'], limit=1024), RuntimeError)
assert time.monotonic()-start < 2
start = time.monotonic()
refuses(lambda: run_command(['/usr/bin/python3','-I','-c','import time; time.sleep(60)'], timeout=.15), TimeoutError)
assert time.monotonic()-start < 2
# A grandchild retains the output pipe after its parent exits. The deadline
# still fires and the process group is killed (including a SIGTERM-ignoring child).
with tempfile.TemporaryDirectory() as tmp:
    marker = Path(tmp)/'pid'
    code = '''import os,signal,time,sys
pid=os.fork()
if pid == 0:
 signal.signal(signal.SIGTERM, signal.SIG_IGN)
 while True: time.sleep(1)
else:
 open(sys.argv[1], 'w').write(str(pid))
'''
    refuses(lambda: run_command(['/usr/bin/python3','-I','-c',code,str(marker)], timeout=.2), TimeoutError)
    pid = int(marker.read_text())
    for _ in range(20):
        status = Path(f'/proc/{pid}/stat')
        if not status.exists() or status.read_text().split()[2] == 'Z':
            break
        time.sleep(.02)
    else:
        raise AssertionError('Grandchild survived process-group deadline')
print('Passed: no-follow files/directories/locks, hardlink/FIFO rejection, pinned rename, atomic failure, bounded locks, clean env, flood/time limits, descendant cleanup')
