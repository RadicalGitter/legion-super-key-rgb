#!/usr/bin/env python3
"""Optional Legion shortcut lighting. No Hyprland configuration changes.

Read-only Lua queries go through the IPC socket; no callbacks or globals are
installed. Hardware protocol and ISO positions: LenovoLegionToolkit (see README).
"""
import argparse
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

HOME = Path.home()
UNIT = 'legion-shortcut-lights.service'
RGB = runpy.run_path(str(Path(__file__).resolve().with_name('spectrum.py')))
RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
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
        s.settimeout(0.75)
        s.connect(str(path))
        s.sendall(command.encode())
        chunks = []
        while data := s.recv(65536):
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
    kb = next((k for k in keyboards if k.get('main')), keyboards[0])
    class Names(C.Structure):
        _fields_ = [(n, C.c_char_p) for n in ('rules', 'model', 'layout', 'variant', 'options')]
    lib = C.CDLL('libxkbcommon.so.0')
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


def run(preview=False, duration=None):
    rows, skipped = bindings()
    modifier_state()  # Fail before opening hardware if queries are unavailable.
    available = set(RGB['AVAILABLE_KEYS'])
    if skipped:
        print('Unmapped shortcuts (not lit): ' + ', '.join(skipped), flush=True)
    STATE.mkdir(parents=True, exist_ok=True)
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with (STATE / 'controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        controller = RGB['Controller']()
        overlay = False
        try:
            start = refreshed = time.monotonic()
            previous = None
            occupied, workspace_checked = frozenset(), 0.0
            print('Shortcut lighting running' + (f' ({duration:g}-second preview)' if preview else ''), flush=True)
            while not stopping and (duration is None or time.monotonic() - start < duration):
                mask, submap = (64, '') if preview else modifier_state()
                now = time.monotonic()
                if mask & 64:
                    if not overlay or now - workspace_checked >= 0.1:
                        occupied = occupied_workspaces()
                        workspace_checked = now
                    if not overlay:
                        profile = controller.query(0xca)[4]
                        overlay = True  # Ensure cleanup even if the start write fails.
                        controller.command(0xd0, 1, profile)
                    state = (mask, submap, occupied)
                    if state != previous:
                        controller.send(packet(selected_colors(rows, mask, submap, occupied), available, mask))
                    previous = state
                elif overlay:
                    restore(controller)
                    overlay, previous = False, None
                # Restore on release before doing the periodic binding refresh.
                if now - refreshed >= 5:
                    rows, _ = bindings()
                    refreshed = now
                    previous = None
                time.sleep(0.02)
        finally:
            try:
                restore(controller)
                print('Temporary lighting cleared; hardware theme restored', flush=True)
            finally:
                os.close(controller.fd)


def systemctl(*args, check=True):
    return subprocess.run(['systemctl', '--user', *args, UNIT], check=check, capture_output=True, text=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', nargs='?', default='toggle', choices=['toggle','on','off','status','run','preview','check','clear'])
    p.add_argument('--duration', type=float)
    args = p.parse_args()
    if args.action in ('run', 'preview'):
        run(args.action == 'preview', 3 if args.action == 'preview' else args.duration)
    elif args.action == 'check':
        rows, skipped = bindings()
        print(json.dumps({'modifiers': modifier_state(), 'mapped_bindings': len(rows), 'super_keys': len(selected(rows,64,'',occupied_workspaces())), 'unmapped': skipped}, indent=2))
    elif args.action == 'clear':
        with (STATE / 'controller.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            controller = RGB['Controller']()
            try:
                restore(controller)
            finally:
                os.close(controller.fd)
    elif args.action == 'status':
        print('On' if systemctl('is-active', '--quiet', check=False).returncode == 0 else 'Off')
    else:
        with (RUNTIME / 'legion-shortcut-toggle.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            active = systemctl('is-active', '--quiet', check=False).returncode == 0
            turn_on = args.action == 'on' or (args.action == 'toggle' and not active)
            if turn_on:
                subprocess.run(['systemctl', '--user', 'import-environment', 'HYPRLAND_INSTANCE_SIGNATURE'], check=True)
                systemctl('start')
                time.sleep(0.6)
                if systemctl('is-active', '--quiet', check=False).returncode:
                    raise RuntimeError('Helper failed; see journalctl --user -u ' + UNIT)
            else:
                systemctl('stop')
            message = 'On — hold Super to show shortcuts' if turn_on else 'Off — normal keyboard theme'
            print(message)
            subprocess.run(['notify-send', 'Shortcut lighting', message], check=False)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'Shortcut lighting: {e}', file=sys.stderr)
        sys.exit(1)
