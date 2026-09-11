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
