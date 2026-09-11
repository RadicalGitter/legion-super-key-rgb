#!/usr/bin/env python3
"""Install/remove user files. Does not edit Hyprland, enable services, or run sudo."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
FILES = {
    '.local/bin/legion-shortcut-lights': 'packaging/legion-shortcut-lights',
    '.local/share/legion-super-key-rgb/helper.py': 'src/helper.py',
    '.local/share/legion-super-key-rgb/spectrum.py': 'src/spectrum.py',
    '.config/systemd/user/legion-shortcut-lights.service': 'packaging/legion-shortcut-lights.service',
}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--uninstall', action='store_true')
    p.add_argument('--prefix', type=Path, default=Path.home(), help='Home directory (alternate prefix for packaging tests)')
    p.add_argument('--no-reload', action='store_true', help='Skip systemd interaction for packaging tests')
    a = p.parse_args()
    base = a.prefix.resolve()
    state = base / '.local/state/legion-super-key-rgb-install'
    record = state / 'files.json'
    previous = json.loads(record.read_text()) if record.exists() else {}
    if any(name not in FILES for name in previous):
        raise RuntimeError('Invalid installation record')
    if not a.no_reload:
        if base != Path.home().resolve():
            raise RuntimeError('Use --no-reload for an alternate prefix')
        # Stop a previous installation before replacing its files. Leave off.
        result = subprocess.run(['systemctl', '--user', 'is-active', '--quiet', 'legion-shortcut-lights.service'])
        if result.returncode == 0:
            subprocess.run(['systemctl', '--user', 'stop', 'legion-shortcut-lights.service'], check=True)
    state.mkdir(parents=True, exist_ok=True)
    if a.uninstall:
        remaining = {}
        for name, info in previous.items():
            dest = base / name
            if dest.is_symlink() or (dest.exists() and digest(dest) != info['sha256']):
                print(f'Keeping modified file: {dest}')
                remaining[name] = info
                continue
            backup = state / 'backups' / name
            if info['backup']:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, dest)
            else:
                dest.unlink(missing_ok=True)
        if remaining:
            record.write_text(json.dumps(remaining, indent=2)+'\n')
        else:
            record.unlink(missing_ok=True)
        print('Removed unmodified installed files; restored any prior versions. Backups retained.')
    else:
        # Check all destinations before writing; avoid overwriting local edits.
        for name in FILES:
            dest = base / name
            if dest.is_symlink():
                raise RuntimeError(f'Refusing symlink destination: {dest}')
            if name in previous and dest.exists() and digest(dest) != previous[name]['sha256']:
                raise RuntimeError(f'Local edits in {dest}; back them up and resolve before updating')
        for name, source in FILES.items():
            dest = base / name
            info = previous.get(name)
            if info is None:
                backed_up = dest.exists()
                if backed_up:
                    backup = state / 'backups' / name
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dest, backup)
                info = {'backup': backed_up}
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Replace atomically so partial writes never become executable.
            temp = dest.with_name(dest.name + '.install-tmp')
            with temp.open('x') as output:
                output.write((ROOT / source).read_text())
            temp.chmod(0o755 if name.startswith('.local/bin/') else 0o644)
            os.replace(temp, dest)
            info['sha256'] = digest(dest)
            previous[name] = info
            record.write_text(json.dumps(previous, indent=2)+'\n')
        print('Helper installed, OFF. Complete the controller access steps in README, then run legion-shortcut-lights check.')
    if not a.no_reload:
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)

if __name__ == '__main__':
    main()
