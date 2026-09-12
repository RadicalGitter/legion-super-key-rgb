"""Simulated suspend, re-enumeration, transient IPC failure, and stop recovery."""
import errno
import os
from pathlib import Path
import runpy
import tempfile
from unittest.mock import Mock, patch

m = runpy.run_path(str(Path(__file__).resolve().parents[1]/'src/helper.py'))
g = m['run'].__globals__
rows = [(64, '', False, 10, None, 'apps')]

class Event:
    def __init__(self):
        self.stopped = False
        self.waits = []
        self.now = 0.0
        self.stop_after = None
    def set(self): self.stopped = True
    def is_set(self): return self.stopped
    def wait(self, delay):
        self.waits.append(delay)
        self.now += delay
        if self.stop_after and len(self.waits) >= self.stop_after: self.set()
        return self.stopped

class Controller:
    fd = -1
    def __init__(self): self.commands, self.packets = [], []
    def query(self, op): return bytes([7, op, 0, 0, 1])
    def command(self, *args): self.commands.append(args)
    def send(self, packet): self.packets.append(packet)


def exercise(event, factory, states, offsets=None, binding_query=None):
    values = iter(states)
    def state():
        value = next(values)
        if isinstance(value, BaseException): raise value
        if value == (0, ''): event.set()
        return value
    close = os.close
    with tempfile.TemporaryDirectory() as tmp, \
         patch.dict(g, STATE=Path(tmp), modifier_state=state,
                    bindings=binding_query or (lambda: (rows,[])),
                    occupied_workspaces=lambda: frozenset({1}),
                    suspend_offset=Mock(side_effect=offsets) if offsets else lambda: 0.0), \
         patch.dict(m['RGB'], Controller=factory), \
         patch('threading.Event', return_value=event), \
         patch('time.monotonic', side_effect=lambda: event.now), \
         patch('signal.signal'), patch('os.close', side_effect=lambda fd: None if fd == -1 else close(fd)):
        m['run']()

# A timeout while lit clears the old overlay; transient ACL loss is retried;
# a fresh fd lights again and release restores the current theme.
a,b=Controller(),Controller()
event=Event();factory=Mock(side_effect=[a,PermissionError(errno.EACCES,'seat unavailable'),b])
exercise(event,factory,[(64,''),TimeoutError('IPC busy'),(64,''),(0,'')])
assert factory.call_count == 3 and len(a.packets)==len(b.packets)==1
assert a.commands[-1] == b.commands[-1] == (0xd0,2,1)
assert .25 in event.waits and .5 in event.waits

# Detect sleep even when no I/O error occurs; discard/reopen, reload bindings.
a,b=Controller(),Controller();event=Event();query=Mock(return_value=(rows,[]))
exercise(event,Mock(side_effect=[a,b]),[(64,''),(0,'')], offsets=[0,0,3600],binding_query=query)
assert query.call_count==2 and a.commands[-1]==(0xd0,2,1)
assert len(a.packets)==1 and not b.packets

# Missing keyboards are transient (not IndexError); startup can wait for them.
with patch.dict(g, ipc=lambda _: '{"keyboards":[]}'):
    try: m['symbol_map']()
    except m['TemporarilyUnavailable']: pass
    else: raise AssertionError('Expected temporary missing keyboard')
event=Event();c=Controller()
query=Mock(side_effect=[m['TemporarilyUnavailable']('no keyboard'),(rows,[])])
exercise(event,lambda:c,[(0,'')],binding_query=query)
assert query.call_count==2 and event.waits[0]==.25

# Long unavailability has bounded retry rate, and off interrupts it without restart.
event=Event();event.stop_after=8
factory=Mock(side_effect=FileNotFoundError(errno.ENODEV,'absent'))
exercise(event,factory,[])
assert event.waits==[.25,.5,1,2,4,5,5,5] and factory.call_count==8

# Configuration/protocol programming errors remain fatal, never a retry loop.
event=Event()
try: exercise(event,lambda:Controller(),[RuntimeError('bad config')])
except RuntimeError as e: assert str(e)=='bad config'
else: raise AssertionError('Expected fatal configuration error')
assert not event.waits
assert not m['recoverable'](PermissionError('unsafe path'))
print('Passed: timeout/seat recovery, resume reopening, empty keyboards, capped backoff, stop while waiting, fatal error propagation')
