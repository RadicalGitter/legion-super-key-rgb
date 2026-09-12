"""Exercise the exact README root payload in an unprivileged synthetic /etc.

Only ROOT and OWNER constants are rewritten for the fixture. Production has no
arguments/environment overrides for either and never reads a checkout source.
"""
import ast
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
readme = (ROOT/'README.md').read_text()
block = readme.split('<!-- fixed-controller-rule-start -->')[1].split('<!-- fixed-controller-rule-end -->')[0]
command = shlex.split(block.split('```bash\n')[1].split('```')[0])
assert command[:8] == ['/usr/bin/sudo','/usr/bin/env','-i','PATH=/usr/bin','LANG=C.UTF-8','/usr/bin/python3','-I','-c']
assert len(command) == 9
code = command[-1]
tree = ast.parse(code)
rule = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='RULE' for t in n.targets))
assert rule == (ROOT/'packaging/70-legion-spectrum-rgb.rules').read_bytes()
assert 'ROOT = "/"' in code and 'OWNER = 0' in code
for attack in ('fresh', 'same', 'different', 'symlink', 'hardlink', 'fifo', 'ancestor', 'writable'):
    with tempfile.TemporaryDirectory(prefix='legion-rule-test-') as tmp:
        root = Path(tmp)
        directory = root/'etc/udev/rules.d';directory.mkdir(parents=True)
        destination = directory/'70-legion-spectrum-rgb.rules'
        victim = root/'victim';victim.write_bytes(b'KEEP')
        if attack == 'same': destination.write_bytes(rule)
        elif attack == 'different': destination.write_bytes(b'OTHER')
        elif attack == 'symlink': destination.symlink_to(victim)
        elif attack == 'hardlink': destination.hardlink_to(victim)
        elif attack == 'fifo': os.mkfifo(destination)
        elif attack == 'ancestor':
            directory.rename(root/'real-rules');directory.symlink_to(root/'real-rules',target_is_directory=True)
        elif attack == 'writable': directory.chmod(0o777)
        fixture_code = code.replace('ROOT = "/"', f'ROOT = {str(root)!r}').replace('OWNER = 0',f'OWNER = {os.getuid()}')
        result = subprocess.run(['/usr/bin/python3','-I','-c',fixture_code],capture_output=True,text=True,timeout=3)
        assert (result.returncode == 0) == (attack in ('fresh','same')), (attack,result.stderr)
        assert victim.read_bytes() == b'KEEP'
        if attack in ('fresh','same'):
            assert destination.read_bytes() == rule
            assert destination.stat().st_nlink == 1
            assert destination.stat().st_mode & 0o777 == 0o644
        if attack == 'different': assert destination.read_bytes() == b'OTHER'
        assert not list(directory.glob('.legion-*'))
print('Passed: literal argv rule matches reference; exclusive creation/idempotence; refuses redirected, linked, special, different and writable destinations')
