#!/usr/bin/python3 -I
"""Install/remove user files through pinned, owned, no-follow directory fds."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).absolute().parent
SAFETY = runpy.run_path(str(ROOT / 'src/safety.py'))
SafeDir, run_command = SAFETY['SafeDir'], SAFETY['run_command']
FILES = {
    '.local/bin/legion-shortcut-lights': 'packaging/legion-shortcut-lights',
    '.local/share/legion-super-key-rgb/helper.py': 'src/helper.py',
    '.local/share/legion-super-key-rgb/spectrum.py': 'src/spectrum.py',
    '.local/share/legion-super-key-rgb/safety.py': 'src/safety.py',
    '.local/share/legion-super-key-rgb/entry.py': 'src/entry.py',
    '.config/systemd/user/legion-shortcut-lights.service': 'packaging/legion-shortcut-lights.service',
}
STATE = '.local/state/legion-super-key-rgb-install'
RECORD = STATE + '/files.json'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def apply(base, uninstall):
    previous_file = base.read(RECORD)
    previous = json.loads(previous_file[0]) if previous_file else {}
    if not isinstance(previous, dict) or any(name not in FILES for name in previous):
        raise RuntimeError('Invalid installation record')
    for info in previous.values():
        if not isinstance(info, dict) or type(info.get('backup')) is not bool or not isinstance(info.get('sha256'), str):
            raise RuntimeError('Invalid file record')
    if uninstall:
        remaining = {}
        for name, info in previous.items():
            current = base.read(name)  # Unsafe entries fail closed; never follow.
            if current is not None and digest(current[0]) != info['sha256']:
                print(f'Keeping modified file: {name}')
                remaining[name] = info
                continue
            if info['backup']:
                backup = base.read(STATE + '/backups/' + name)
                if backup is None:
                    raise RuntimeError(f'Missing original backup: {name}')
                base.write(name, *backup)
            elif current is not None:
                base.unlink(name)
        if remaining:
            base.write(RECORD, (json.dumps(remaining, indent=2)+'\n').encode())
        elif previous_file:
            base.unlink(RECORD)
        print('Removed unmodified installed files; restored prior versions. Backups retained.')
        return
    with SafeDir(ROOT) as source:
        payloads = {name: source.read(src)[0] for name, src in FILES.items()}
    current = {name: base.read(name) for name in FILES}
    for name, value in current.items():
        if name in previous and value is not None and digest(value[0]) != previous[name]['sha256']:
            raise RuntimeError(f'Local edits in {name}; resolve before updating')
    for name in FILES:
        info = previous.get(name)
        if info is None:
            info = {'backup': current[name] is not None}
            if current[name] is not None:
                base.write(STATE + '/backups/' + name, *current[name])
        # Atomic replacement, randomized exclusive temporary, directory fsync.
        info['sha256'] = digest(payloads[name])
        previous[name] = info
        # Write intent before replacement so interruption cannot lose backup ownership.
        base.write(RECORD, (json.dumps(previous, indent=2)+'\n').encode())
        base.write(name, payloads[name], 0o755 if name.startswith('.local/bin/') else 0o644)
    print('Helper installed, OFF. Complete README setup, then run legion-shortcut-lights check.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--uninstall', action='store_true')
    p.add_argument('--prefix', type=Path, default=SAFETY['HOME'])
    p.add_argument('--no-reload', action='store_true', help='Skip systemd interaction for packaging tests')
    a = p.parse_args()
    # Never resolve the prefix: that would silently accept a symlink ancestor.
    prefix = a.prefix.absolute()
    if not a.no_reload and prefix != SAFETY['HOME']:
        raise RuntimeError('Use --no-reload for an alternate prefix')
    if not a.no_reload:
        for path in ('/usr/bin/python3', '/usr/bin/env', '/usr/bin/timeout', '/usr/bin/systemctl', '/usr/bin/notify-send'):
            SAFETY['trusted_system_file'](path, executable=True)
    with SafeDir(prefix) as base, base.lock(STATE + '/install.lock', timeout=2):
        if not a.no_reload:
            active = run_command(['/usr/bin/systemctl','--user','is-active','--quiet','legion-shortcut-lights.service'], check=False)
            if active.returncode == 0:
                run_command(['/usr/bin/systemctl','--user','stop','legion-shortcut-lights.service'])
        if not a.no_reload:
            run_command(['/usr/bin/systemctl','--user','disable','legion-shortcut-lights.service'], check=False)
        apply(base, a.uninstall)
        if not a.no_reload:
            run_command(['/usr/bin/systemctl','--user','daemon-reload'])


if __name__ == '__main__':
    main()
