"""Exercise first install, update, edits, uninstall and prior-file restoration."""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='legion-install-test-') as tmp:
    home = Path(tmp)
    command = home / '.local/bin/legion-shortcut-lights'
    command.parent.mkdir(parents=True)
    command.write_text('original helper\n')
    command.chmod(0o750)
    def install(*args, okay=True):
        p = subprocess.run([sys.executable, str(ROOT/'install.py'), '--prefix', tmp, '--no-reload', *args], capture_output=True, text=True)
        assert (p.returncode == 0) == okay, p.stdout+p.stderr
        return p
    install()
    assert 'runpy' in command.read_text()
    assert command.stat().st_mode & 0o777 == 0o755
    install()  # Idempotent reinstall must retain the original backup.
    command.write_text('local edit\n')
    install(okay=False)
    install('--uninstall')
    assert command.read_text() == 'local edit\n'
    # Resolve the edit to the installed version, then uninstall.
    command.write_text((ROOT/'packaging/legion-shortcut-lights').read_text())
    install('--uninstall')
    assert command.read_text() == 'original helper\n'
    assert command.stat().st_mode & 0o777 == 0o750
    assert not (home/'.local/share/legion-super-key-rgb/helper.py').exists()
    install('--uninstall')  # Safe repeated removal.
print('Passed: installation, repeated update, modified-file protection, uninstall, backup restoration')

# Exercise the actual installer against hostile destination/record/backup paths.
for attack in ('ancestor', 'record', 'backup', 'destination', 'install-lock'):
    with tempfile.TemporaryDirectory(prefix='legion-installer-attack-') as tmp:
        home = Path(tmp)/'home'; home.mkdir()
        outside = Path(tmp)/'outside'; outside.mkdir()
        victim = outside/'victim'; victim.write_text('KEEP')
        state = home/'.local/state/legion-super-key-rgb-install'
        if attack == 'ancestor':
            (home/'.local').symlink_to(outside, target_is_directory=True)
        else:
            state.mkdir(parents=True)
            if attack == 'record':
                (state/'files.json').symlink_to(victim)
            elif attack == 'backup':
                command = home/'.local/bin/legion-shortcut-lights'
                command.parent.mkdir(parents=True); command.write_text('old')
                (state/'backups').symlink_to(outside, target_is_directory=True)
            elif attack == 'destination':
                command = home/'.local/bin/legion-shortcut-lights'
                command.parent.mkdir(parents=True); command.symlink_to(victim)
            else:
                (state/'install.lock').symlink_to(victim)
        p = subprocess.run([sys.executable,str(ROOT/'install.py'),'--prefix',str(home),'--no-reload'],
                           capture_output=True,text=True,timeout=5)
        assert p.returncode != 0, attack
        assert victim.read_text() == 'KEEP', attack
        assert list(outside.iterdir()) == [victim], attack
print('Passed: installer rejects symlinked ancestors, records, backups, destinations and locks without redirected writes')
