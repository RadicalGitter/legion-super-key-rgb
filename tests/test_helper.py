"""Regression checks for mapping, temporary packets, and restoration on failure."""
import runpy
import tempfile
from pathlib import Path
from unittest.mock import patch

m = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'src/helper.py'))
g = m['run'].__globals__
rows = [(64, '', False, 10, None, 'apps'), (65, '', False, 20, None, 'actions'), (64, 'other', False, 30, None, 'actions')]
assert m['selected'](rows, 64, '') == {10}
assert m['selected'](rows, 65, '') == {20}
assert m['selected'](rows, 0, '') == set()
assert m['selected'](rows, 64, 'other') == {30}
assert m['missing_code']('Switch to workspace 10') == 19
assert m['missing_code']('Shrink window up a lot') == 20
assert m['missing_code']('Some unknown shortcut') == 0
packet = m['packet']({10: 'apps'}, {10, 20})
assert len(packet) == 960 and packet[:4] == bytes([7, 0xa1, 0xc0, 3])
assert packet[4:9] == bytes([10, 0, 180, 90, 255])
assert packet[9:14] == bytes([20, 0, 0, 0, 0])

rgb = m['RGB']
# Once an overlay starts, an IPC error must clear it and close the controller.
class FakeController:
    fd = -1
    def __init__(self):
        self.commands = []
    def query(self, op):
        return bytes([7, op, 0, 0, 1])
    def command(self, *args):
        self.commands.append(args)
    def send(self, data):
        assert data[:2] == bytes([7, 0xa1])
workspace_rows = [(64, '', False, 23, 1, 'workspaces'), (64, '', False, 24, 2, 'workspaces'),
                  (65, '', False, 24, None, 'workspaces'), (64, '', False, 99, None, 'actions')]
assert m['selected'](workspace_rows, 64, '', {1}) == {23, 99}
assert m['selected'](workspace_rows, 64, '', set()) == {99}
assert m['selected'](workspace_rows, 65, '', set()) == {24}
assert m['selected'](workspace_rows, 64, '', {2}) == {24, 99}
with patch.dict(g, ipc=lambda _: '[{"id":1,"windows":2},{"id":2,"windows":0}]'):
    assert m['occupied_workspaces']() == {1}
c = FakeController()
with tempfile.TemporaryDirectory() as tmp:
    with patch.dict(g, STATE=Path(tmp)), patch.dict(rgb, Controller=lambda: c), \
         patch.dict(g, bindings=lambda: (rows, [])), patch.dict(g, occupied_workspaces=lambda: frozenset({1})), \
         patch.dict(g, modifier_state=__import__('unittest.mock', fromlist=['Mock']).Mock(side_effect=[(0,''), (64,''), RuntimeError('IPC lost')])), \
         patch('os.close') as close, patch('time.sleep'), patch('signal.signal'):
        try:
            m['run']()
        except RuntimeError as e:
            assert str(e) == 'IPC lost'
        else:
            raise AssertionError('Expected IPC failure')
        assert c.commands == [(0xd0, 1, 1), (0xd0, 2, 1)]
        close.assert_called_once_with(-1)
print('Passed: exact modifiers/submaps, missing keycodes, packet format, IPC failure cleanup')

for desc, expected in [('Browser (private)', 'apps'), ('Close window', 'actions'),
                       ('Move window to workspace 7', 'workspaces'),
                       ('Launch My Custom App', 'apps'), ('Unknown shortcut', 'actions'),
                       ('Custom thing [rgb:apps]', 'apps')]:
    assert m['category']({'description': desc, 'dispatcher': '__lua'}) == expected
assert m['category']({'description': 'Take screenshot', 'dispatcher': 'exec'}) == 'actions'
assert m['category']({'description': 'Calendar', 'modmask': 76}) == 'actions'
assert m['selected_colors'](rows, 64, '') == {10: 'apps'}
collision = [(64, '', False, 23, 1, 'workspaces'), (64, '', False, 23, None, 'actions')]
assert m['selected_colors'](collision, 64, '', {1}) == {23: 'workspaces'}
assert m['selected_colors'](list(reversed(collision)), 64, '', {1}) == {23: 'workspaces'}
assert m['selected_colors'](collision, 64, '', set()) == {23: 'actions'}
print('Passed: category heuristics, explicit tags, packet colors, deterministic shared-key priority')
