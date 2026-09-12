#!/usr/bin/python3 -I
"""Isolated entry point; explicitly load only this installed source directory."""
import os
from pathlib import Path
import runpy
import sys

folder = Path(__file__).absolute().parent
safety = runpy.run_path(str(folder / 'safety.py'))
safety['trusted_system_file']('/usr/bin/python3', executable=True)
safety['trusted_system_file']('/usr/bin/timeout', executable=True)
closed = safety['clean_environment']()
os.environ.clear()
os.environ.update(closed)
# Read through owned no-follow directory descriptors, then execute those bytes.
with safety['SafeDir'](folder) as source:
    data = source.read('helper.py')
    if data is None:
        raise RuntimeError('Missing helper.py')
    code = compile(data[0], str(folder / 'helper.py'), 'exec')
exec(code, {'__name__': '__main__', '__file__': str(folder / 'helper.py'), 'SAFETY': safety})
