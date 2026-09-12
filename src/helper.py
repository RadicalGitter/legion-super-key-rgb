#!/usr/bin/python3 -I
"""Optional Legion shortcut lighting. No Hyprland configuration changes.

Read-only Lua queries go through the IPC socket; no callbacks or globals are
installed. Hardware protocol and ISO positions: LenovoLegionToolkit (see README).
"""
import argparse
import errno
import threading
import ctypes as C
import fcntl
import json
import os
from pathlib import Path
import re
import runpy
import signal
import socket
import struct
import subprocess
import sys
import time

SAFETY = globals().get('SAFETY') or runpy.run_path(str(Path(__file__).absolute().with_name('safety.py')))
SafeDir = SAFETY['SafeDir']
run_command = SAFETY['run_command']
HOME = SAFETY['HOME']
UNIT = 'legion-shortcut-lights.service'
with SafeDir(Path(__file__).absolute().parent) as source:
    RGB = {'__name__': 'spectrum'}
    exec(compile(source.read('spectrum.py')[0], 'spectrum.py', 'exec'), RGB)
RUNTIME = SAFETY['RUNTIME']
STATE = HOME / '.local/state/legion-rgb'
# XKB physical keycodes -> Spectrum ISO LED IDs. Fn is handled by firmware.
PHYSICAL = {9: 1, 22: 0x38, 23: 0x40, 66: 0x55, 36: 0x77,
            50: 0x6a, 94: 0x4e, 62: 0x8d, 37: 0x7f, 133: 0x96,
            64: 0x97, 65: 0x98, 108: 0x9a, 105: 0x9b,
            111: 0x9d, 113: 0x9c, 116: 0x9f, 114: 0xa1,
            118: 0x0e, 107: 0x0f, 119: 0x10,
            110: 0x11, 115: 0x12, 112: 0x13, 117: 0x14}
PHYSICAL.update(dict(zip([*range(67, 77), 95, 96], range(2, 14))))
PHYSICAL.update(dict(zip([49, *range(10, 22)], range(0x16, 0x23))))
PHYSICAL.update(dict(zip(range(24, 36), range(0x42, 0x4e))))
PHYSICAL.update(dict(zip([*range(38, 49), 51],
                        [0x6d, 0x6e, 0x58, 0x59, 0x5a, 0x71, 0x72, 0x5b, 0x5c, 0x5d, 0x5f, 0xa8])))
PHYSICAL.update(dict(zip(range(52, 62), [0x82, 0x83, 0x6f, 0x70, 0x87, 0x88, 0x73, 0x74, 0x75, 0x76])))
PHYSICAL.update(dict(zip([77, 106, 63, 82, 79, 80, 81, 86, 83, 84, 85, 87, 88, 89, 104, 90, 91],
                        [0x26, 0x27, 0x28, 0x29, 0x4f, 0x50, 0x51, 0x68, 0x79, 0x7b, 0x7c, 0x8e, 0x90, 0x92, 0xa7, 0xa3, 0xa5])))
MODIFIERS = [(64, (133, 134)), (1, (50, 62)), (4, (37, 105)), (8, (64,)), (128, (108,))]
QUERY = ('local m=0; ' + ' '.join(
    f'if {" or ".join(f"hl.is_key_down({k})" for k in keys)} then m=m+{mask} end;'
    for mask, keys in MODIFIERS) + ' return tostring(m).."|"..hl.get_current_submap()')


def ipc(command):
    signature = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', '')
    if not signature or '/' in signature:
        raise RuntimeError('No Hyprland session in this environment')
    path = RUNTIME / 'hypr' / signature / '.socket.sock'
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        deadline = time.monotonic() + 0.75
        s.settimeout(0.75)
        s.connect(str(path))
        s.sendall(command.encode())
        chunks = []
        total = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Hyprland IPC deadline exceeded')
            s.settimeout(remaining)
            data = s.recv(65536)
            if not data:
                break
            total += len(data)
            if total > 2 * 1024 * 1024:
                raise RuntimeError('Hyprland IPC response exceeds limit')
            chunks.append(data)
        return b''.join(chunks).decode().strip()


def modifier_state():
    reply = ipc('repl ' + QUERY)
    mask, sep, submap = reply.partition('|')
    if not sep or not mask.isdigit():
        raise RuntimeError(f'Unexpected modifier query response: {reply[:200]}')
    return int(mask), submap


def symbol_map():
    """Resolve symbols against the active keyboard layout, including Swedish /."""
    keyboards = json.loads(ipc('j/devices'))['keyboards']
    if not keyboards:
        raise TemporarilyUnavailable('Hyprland reports no keyboard yet')
    kb = next((k for k in keyboards if k.get('main')), keyboards[0])
    class Names(C.Structure):
        _fields_ = [(n, C.c_char_p) for n in ('rules', 'model', 'layout', 'variant', 'options')]
    lib = C.CDLL(SAFETY['trusted_system_file']('/usr/lib/libxkbcommon.so.0'))
    funcs = {
        'xkb_context_new': ([C.c_int], C.c_void_p),
        'xkb_keymap_new_from_names': ([C.c_void_p, C.POINTER(Names), C.c_int], C.c_void_p),
        'xkb_keymap_key_get_syms_by_level': ([C.c_void_p, C.c_uint, C.c_uint, C.c_uint, C.POINTER(C.POINTER(C.c_uint))], C.c_int),
        'xkb_keysym_get_name': ([C.c_uint, C.c_char_p, C.c_size_t], C.c_int),
        'xkb_context_unref': ([C.c_void_p], None),
        'xkb_keymap_unref': ([C.c_void_p], None),
    }
    for name, (args, result) in funcs.items():
        getattr(lib, name).argtypes = args
        getattr(lib, name).restype = result
    names = Names(*[(kb.get(k) or '').encode() or None for k in ('rules','model','layout','variant','options')])
    ctx = lib.xkb_context_new(0)
    keymap = lib.xkb_keymap_new_from_names(ctx, C.byref(names), 0)
    if not keymap:
        lib.xkb_context_unref(ctx)
        raise RuntimeError('Cannot load keyboard layout')
    result = {}
    try:
        # Prefer unshifted symbols; only fall back to higher levels when needed.
        for level in range(8):
            for code, led in PHYSICAL.items():
                syms = C.POINTER(C.c_uint)()
                n = lib.xkb_keymap_key_get_syms_by_level(keymap, code, kb.get('active_layout_index', 0), level, C.byref(syms))
                for i in range(n):
                    buf = C.create_string_buffer(128)
                    lib.xkb_keysym_get_name(syms[i], buf, 128)
                    result.setdefault(buf.value.decode().lower(), led)
    finally:
        lib.xkb_keymap_unref(keymap)
        lib.xkb_context_unref(ctx)
    return result


def missing_code(description):
    # Workaround for 0.56.2 IPC's empty key/keycode for physical binds.
    # Corresponds to /usr/share/omarchy/default/hypr/bindings/{tiling,utilities}.lua.
    m = re.fullmatch(r'(?:Switch to workspace|Move window to workspace|Move window silently to workspace|Switch to group window|Bar panel) (\d+)', description)
    if m and 1 <= int(m[1]) <= 10:
        return int(m[1]) + 9
    if re.fullmatch(r'(?:Expand window left|Shrink window up)(?: a little| a lot)?', description):
        return 20
    if re.fullmatch(r'(?:Shrink window left|Expand window down)(?: a little| a lot)?', description):
        return 21
    return {'Make webcam overlay smaller': 34, 'Make webcam overlay larger': 35, 'Omarchy menu': 201}.get(description, 0)


PALETTE = {
    'apps': (180, 90, 255),
    'actions': (255, 135, 35),
    'workspaces': (50, 220, 170),
    'modifiers': (90, 160, 255),
}
APP_DESCRIPTIONS = {
    'terminal', 'browser', 'file manager', 'editor', 'tmux', 'herdr',
    'music', 'music tui', 'docker', 'signal', 'obsidian', 'omawrite',
    'passwords', 'chatgpt', 'grok', 'calendar', 'email', 'new email',
    'youtube', 'whatsapp', 'google messages', 'google photos', 'google maps',
    'x', 'x post', 'calculator', 'butler', 'lecture recorder', 'clipboard manager',
}


def category(binding):
    """Descriptions are heuristics: Lua dispatchers hide the actual operation.

    An explicit [rgb:apps/actions/workspaces] description tag takes precedence.
    Unknown operations default to actions; exec alone does not imply an app.
    """
    description = binding.get('description', '').strip().lower()
    tag = re.search(r'\[rgb:(apps|actions|workspaces)\]', description)
    if tag:
        return tag[1]
    if 'workspace' in description or binding.get('dispatcher') in {
        'workspace', 'movetoworkspace', 'movetoworkspacesilent',
        'togglespecialworkspace', 'focusworkspaceoncurrentmonitor',
    }:
        return 'workspaces'
    base = re.sub(r'\s*\([^)]*\)$', '', description)
    # Calendar is also the stock Super+Ctrl+Alt+D shell panel.
    if base == 'calendar' and binding.get('modmask') == 76:
        return 'actions'
    if base in APP_DESCRIPTIONS or description.startswith(('launch ', 'open app ')):
        return 'apps'
    return 'actions'


def bindings():
    symbols = symbol_map()
    rows, skipped = [], set()
    for b in json.loads(ipc('j/binds')):
        if not b['modmask'] & 64 or b.get('mouse'):
            continue
        key = b['key'].lower()
        if key.startswith(('mouse', 'switch:')):
            continue
        code = b['keycode'] or (missing_code(re.sub(r'\s*\[rgb:(?:apps|actions|workspaces)\]\s*', '', b['description']).strip()) if not key else 0)
        led = PHYSICAL.get(code) if code else symbols.get(key)
        if led is None:
            skipped.add(b['description'] or key)
            continue
        description = re.sub(r'\s*\[rgb:(?:apps|actions|workspaces)\]\s*', '', b['description']).strip()
        target = re.fullmatch(r'Switch to workspace (\d+)', description)
        workspace = int(target[1]) if target else None
        # Swedish slash shares physical 7. Let workspace occupancy govern
        # plain Super+7 lighting even though monitor scaling also uses it.
        if b['modmask'] == 64 and key == 'slash' and led == PHYSICAL[16]:
            workspace = 7
        rows.append((b['modmask'], b['submap'], str(b.get('submap_universal')).lower() == 'true', led, workspace, category(b)))
    return rows, sorted(skipped)


def occupied_workspaces():
    return frozenset(w['id'] for w in json.loads(ipc('j/workspaces')) if w['windows'] > 0)


def selected_colors(rows, mask, submap, occupied=None):
    if not mask & 64:
        return {}
    colors = {}
    # Deterministic shared-key priority: workspace > app > action.
    priority = {'actions': 0, 'apps': 1, 'workspaces': 2}
    for mods, sm, universal, led, workspace, kind in rows:
        if mods != mask or not (sm == submap or universal):
            continue
        if workspace is not None and occupied is not None and workspace not in occupied:
            continue
        if led not in colors or priority[kind] > priority[colors[led]]:
            colors[led] = kind
    return colors


def selected(rows, mask, submap, occupied=None):
    return set(selected_colors(rows, mask, submap, occupied))


def packet(keys, available, mask=64):
    active_mods = {PHYSICAL[k] for bit, codes in MODIFIERS if bit & mask for k in codes if k in PHYSICAL}
    data = bytearray([7, 0xa1, 0xc0, 3])
    for key in sorted(available):
        rgb = PALETTE[keys[key]] if key in keys else (PALETTE['modifiers'] if key in active_mods else (0, 0, 0))
        data.extend(struct.pack('<HBBB', key, *rgb))
    if len(data) > RGB['SIZE']:
        raise RuntimeError('Too many keyboard LEDs')
    return bytes(data).ljust(RGB['SIZE'], b'\0')


def restore(controller):
    profile = controller.query(0xca)[4]
    controller.command(0xd0, 2, profile)


class TemporarilyUnavailable(Exception):
    """Session data is temporarily absent (for example during seat resume)."""


def suspend_offset():
    # BOOTTIME includes suspend; MONOTONIC does not. No wall-clock/NTP dependency.
    return time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic()


def recoverable(error):
    return isinstance(error, TemporarilyUnavailable) or (
        isinstance(error, OSError) and (isinstance(error, TimeoutError) or error.errno in {
            errno.ENOENT, errno.ENODEV, errno.ENXIO, errno.EIO, errno.EACCES,
            errno.EPERM, errno.EPIPE, errno.ECONNREFUSED, errno.ECONNRESET,
            errno.ETIMEDOUT, errno.EBUSY, errno.EAGAIN,
        }))


def run(preview=False, duration=None):
    available = set(RGB['AVAILABLE_KEYS'])
    stopping = threading.Event()
    def stop(*_):
        stopping.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    # Keep the lock across recovery so another RGB writer cannot race retries.
    # Filesystem trust/lock failures occur outside the recoverable I/O block.
    with SafeDir(STATE, create=True) as state_dir, state_dir.lock('controller.lock'):
        controller = None
        overlay, previous = False, None
        occupied, workspace_checked = frozenset(), 0.0
        start = refreshed = time.monotonic()
        offset = suspend_offset()
        retry_delay, waiting, next_log = 0.25, False, 0.0

        def disconnect():
            nonlocal controller, overlay, previous
            current, controller = controller, None
            overlay, previous = False, None
            if current is not None:
                try:
                    restore(current)
                except Exception as error:
                    print(f'Cleanup unavailable: {error}', flush=True)
                else:
                    print('Temporary lighting cleared; hardware theme restored', flush=True)
                finally:
                    os.close(current.fd)

        print('Shortcut lighting enabled' + (f' ({duration:g}-second preview)' if preview else ''), flush=True)
        try:
            while not stopping.is_set() and (duration is None or time.monotonic() - start < duration):
                try:
                    current_offset = suspend_offset()
                    if current_offset - offset > 0.2:
                        print('Resume detected; reopening RGB controller and refreshing bindings', flush=True)
                        disconnect()
                        retry_delay = 0.25
                    offset = current_offset
                    if controller is None:
                        rows, skipped = bindings()
                        if skipped and not waiting:
                            print('Unmapped shortcuts (not lit): ' + ', '.join(skipped), flush=True)
                        controller = RGB['Controller']()
                        # Clear any stale overlay after a failed read or device reset.
                        restore(controller)
                        refreshed = time.monotonic()
                        workspace_checked = 0.0
                    mask, submap = (64, '') if preview else modifier_state()
                    now = time.monotonic()
                    if mask & 64:
                        if not overlay or now - workspace_checked >= 0.1:
                            occupied = occupied_workspaces()
                            workspace_checked = now
                        if not overlay:
                            profile = controller.query(0xca)[4]
                            overlay = True
                            controller.command(0xd0, 1, profile)
                        state = (mask, submap, occupied)
                        if state != previous:
                            controller.send(packet(selected_colors(rows, mask, submap, occupied), available, mask))
                        previous = state
                    elif overlay:
                        restore(controller)
                        overlay, previous = False, None
                    if now - refreshed >= 5:
                        rows, _ = bindings()
                        refreshed = now
                        previous = None
                except (OSError, TemporarilyUnavailable) as error:
                    if not recoverable(error):
                        raise
                    disconnect()
                    now = time.monotonic()
                    if not waiting or now >= next_log:
                        print(f'Waiting for session/controller recovery: {error}', flush=True)
                        next_log = now + 60
                    waiting = True
                    # Individual I/O attempts retain their deadlines. No process
                    # restart loop: wait at most five seconds between attempts,
                    # with an immediately interruptible off/stop operation.
                    delay = retry_delay
                    if duration is not None:
                        delay = min(delay, max(0, duration - (now - start)))
                    stopping.wait(delay)
                    retry_delay = min(5.0, retry_delay * 2)
                    continue
                if waiting:
                    print('Session/controller recovered; shortcut lighting ready', flush=True)
                waiting, retry_delay = False, 0.25
                stopping.wait(0.02)
        finally:
            disconnect()


def systemctl(*args, check=True):
    return run_command(['/usr/bin/systemctl', '--user', *args, UNIT], check=check)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', nargs='?', default='toggle', choices=['toggle','on','off','status','status-exit','run','preview','check','clear'])
    p.add_argument('--duration', type=float)
    p.add_argument('--quiet', action='store_true', help='Suppress toggle output and notifications for the bar')
    args = p.parse_args()
    if args.action in ('run', 'preview'):
        run(args.action == 'preview', 3 if args.action == 'preview' else args.duration)
    elif args.action == 'check':
        rows, skipped = bindings()
        print(json.dumps({'modifiers': modifier_state(), 'mapped_bindings': len(rows), 'super_keys': len(selected(rows,64,'',occupied_workspaces())), 'unmapped': skipped}, indent=2))
    elif args.action == 'clear':
        with SafeDir(STATE, create=True) as state_dir, state_dir.lock('controller.lock'):
            controller = RGB['Controller']()
            try:
                restore(controller)
            finally:
                os.close(controller.fd)
    elif args.action == 'status-exit':
        sys.exit(systemctl('is-active', '--quiet', check=False).returncode)
    elif args.action == 'status':
        print('On' if systemctl('is-active', '--quiet', check=False).returncode == 0 else 'Off')
    else:
        with SafeDir(RUNTIME) as runtime_dir, runtime_dir.lock('legion-shortcut-toggle.lock', timeout=2):
            active = systemctl('is-active', '--quiet', check=False).returncode == 0
            turn_on = args.action == 'on' or (args.action == 'toggle' and not active)
            if turn_on:
                run_command(['/usr/bin/systemctl', '--user', 'import-environment', 'HYPRLAND_INSTANCE_SIGNATURE'])
                systemctl('start')
                time.sleep(0.6)
                if systemctl('is-active', '--quiet', check=False).returncode:
                    raise RuntimeError('Helper failed; see journalctl --user -u ' + UNIT)
            else:
                systemctl('stop')
            message = 'On — hold Super to show shortcuts' if turn_on else 'Off — normal keyboard theme'
            if not args.quiet:
                print(message)
                run_command(['/usr/bin/notify-send', 'Shortcut lighting', message], check=False, timeout=2)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'Shortcut lighting: {e}', file=sys.stderr)
        sys.exit(1)
