# Legion Super Key RGB

**Hold Super. See what you can press.**

Turn a Lenovo Legion RGB keyboard into a shortcut guide for Omarchy / Hyprland.
Shortcut colors show their purpose, modifiers glow blue, and releasing Super
restores your existing hardware lighting and animations.

- Add Shift, Ctrl, or Alt to show shortcuts for that exact combination.
- Empty workspaces stay dark; moving a window to an empty workspace stays available.
- Reads live bindings every five seconds and workspace occupancy every 100 ms.
- Checks modifiers every 20 ms. Restoring the profile includes a 50 ms firmware query.
- Optional Omarchy bar button, terminal toggle, and Super+Alt+K binding.
- Off on installation; the toggle remembers on/off across logins and reboots.
  No compositor hooks or monkey-patching.

## Shortcut colors

| Color | Meaning |
|---|---|
| Purple | App launches |
| Orange | Actions, menus, and unrecognized shortcuts |
| Teal | Workspace operations |
| Blue | Held modifier keys |

Categories are inferred from binding descriptions because Hyprland's Lua
callbacks hide their underlying commands. Known Omarchy app descriptions and
`Launch …` / `Open app …` descriptions count as apps. This is a heuristic, not
inspection of what a callback does. Add `[rgb:apps]`, `[rgb:actions]`, or
`[rgb:workspaces]` to a binding's description to override it. Existing numeric
workspace filtering still works with these tags. Colors refresh with bindings.
When multiple bindings share a key, workspace color takes priority over apps,
then actions; empty-workspace filtering still runs before choosing the color.
Palette RGB values live in `PALETTE` in `src/helper.py`.

## Compatibility

**Experimental; tested on one machine:** Lenovo Legion 7 16IRX9, ISO Swedish
keyboard, USB Spectrum controller **048d:c997**, Omarchy **4.0.3**, Hyprland
**0.56.2**. Other Legion models, ANSI keyboards, and other Hyprland versions are
not verified. This is not a generic OpenRGB plugin or a four-zone RGB driver.
The helper refuses a different controller ID.

The hardware overlay, release restoration, CLI toggle and workspace filtering
were tested on that laptop. The optional bar widget has manifest and static QML
validation; visual bar testing is still pending.

Requires Linux, system-managed Python 3.10+ at `/usr/bin/python3`, GNU coreutils (`env` and `timeout`), systemd user services, libxkbcommon, and a Hyprland
build exposing `repl`, `hl.is_key_down`, and `hl.get_current_submap`. Notifications
use `/usr/bin/notify-send` (Arch package `libnotify`). The bar widget additionally requires
Omarchy Quattro's Quickshell shell. The helper works independently of which shell
is visible, including when using Caelestia on the tested Omarchy installation.

## Install the helper

Clone and inspect the repository, then run the installer as your normal user:

```bash
git clone https://github.com/RadicalGitter/legion-super-key-rgb.git
cd legion-super-key-rgb
/usr/bin/python3 -I install.py
```

This installs a command in `~/.local/bin`, four Python files in
`~/.local/share/legion-super-key-rgb`, and a user service. It backs up any existing
files it replaces and refuses updates over locally modified installed files.
Installing or updating stops an already-running helper, disables login startup,
and leaves it **off**. Turn it on again after updating if desired. It does not edit your
Hyprland configuration, change the bar, install packages, run privileged commands,
or write any keyboard effect profiles. Ensure `~/.local/bin` is on your PATH.

### Controller access (one-time, only if not already configured)

The access rule grants the active local user access to the matching controller's
raw HID interface, which also belongs to the keyboard. The helper does not read
input-event devices or log ordinary keystrokes.

**Review and paste the complete command below in your terminal.** The fixed rule
and installation logic are passed as one literal argument, already captured
before the privilege prompt. Root never opens a source file from this checkout,
reads rule data from stdin, or imports local Python modules. Do not substitute
`sudo install packaging/...`, command substitution, or a root-run repository
script: those would reintroduce a mutable source at the privilege boundary.

This checks every destination directory through no-follow descriptors and
requires root ownership without group/world write access. It publishes the
complete fixed rule atomically and exclusively. An identical safe rule is kept;
a different rule, symlink, hardlink, FIFO or unsafe directory is refused. Missing
system directories are not created. The `packaging/*.rules` file is a readable
reference only and is never consumed by the privileged operation.

<!-- fixed-controller-rule-start -->
```bash
/usr/bin/sudo /usr/bin/env -i PATH=/usr/bin LANG=C.UTF-8 /usr/bin/python3 -I -c '
import os, secrets, stat

OWNER = 0
ROOT = "/"
RULE = b"# RGB controller in this Lenovo Legion 7 16IRX9; active local user only.\nSUBSYSTEM==\"hidraw\", ATTRS{idVendor}==\"048d\", ATTRS{idProduct}==\"c997\", TAG+=\"uaccess\"\n"
NAME = "70-legion-spectrum-rgb.rules"
FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

def check_directory(fd):
    info = os.fstat(fd)
    if info.st_uid != OWNER or info.st_mode & 0o022:
        raise PermissionError("Destination directory must be root-owned and not writable by others")

if os.geteuid() != OWNER:
    raise PermissionError("Root privileges required")
directory = os.open(ROOT, FLAGS)
try:
    check_directory(directory)
    for part in ("etc", "udev", "rules.d"):
        child = os.open(part, FLAGS, dir_fd=directory)
        os.close(directory)
        directory = child
        check_directory(directory)
    try:
        current = os.open(NAME, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
    except FileNotFoundError:
        temp = ".legion-" + secrets.token_hex(16)
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(RULE)
                stream.flush()
                os.fchmod(stream.fileno(), 0o644)
                os.fsync(stream.fileno())
            # Exclusive atomic publication: never replace an existing entry.
            os.link(temp, NAME, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        finally:
            os.unlink(temp, dir_fd=directory)
            os.fsync(directory)
        print("Installed the fixed Spectrum access rule")
    else:
        try:
            info = os.fstat(current)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != OWNER or info.st_nlink != 1 or info.st_mode & 0o022:
                raise PermissionError("Unsafe existing destination; refusing to replace it")
            if os.read(current, len(RULE) + 1) != RULE:
                raise FileExistsError("Different rule already exists; review it manually")
            print("The exact Spectrum rule is already installed; unchanged")
        finally:
            os.close(current)
finally:
    os.close(directory)
'
```
<!-- fixed-controller-rule-end -->

After the command succeeds:

```bash
/usr/bin/sudo /usr/bin/udevadm control --reload-rules
/usr/bin/sudo /usr/bin/udevadm trigger --subsystem-match=hidraw
```

A logout/login may be needed for the active-seat access grant. No input-group
membership, passwordless sudo policy, or root daemon is required.

### Try it

```bash
legion-shortcut-lights check    # read-only Hyprland mapping diagnostics
legion-shortcut-lights preview  # three-second hardware preview, then restore
legion-shortcut-lights         # toggle on/off
legion-shortcut-lights status
legion-shortcut-lights off
```

When on, hold Super and try adding Shift, Ctrl, or Alt. Hardware commands are
serialized with the existing `~/.local/state/legion-rgb/controller.lock`. Avoid
running another RGB controller tool simultaneously. Stop this helper before
changing hardware profiles with Fn+Space; it queries the active profile when
restoring, but changing profiles mid-overlay is not verified.

### Optional Super+Alt+K shortcut

On stock Omarchy this replaces **Tmux keybindings**. Back up
`~/.config/hypr/bindings.lua`, then add:

```lua
hl.unbind("SUPER + ALT + K")
o.bind("SUPER + ALT + K", "Toggle keyboard shortcut lighting", "legion-shortcut-lights toggle")
```

Validate with `hyprctl reload` followed by `hyprctl configerrors`.
The shortcut starts/stops the external helper and remembers that choice using
systemd user-service enablement. When on, it starts after the graphical session
is ready on subsequent logins; when off, it stays off across reboots.

## Optional Omarchy bar widget

Complete the helper and controller setup first. The marketplace install installs
the bar widget, **not** the Python helper or udev rule. This plugin requires
manual setup; opening the widget never runs the installer.

```bash
omarchy plugin add https://github.com/RadicalGitter/legion-super-key-rgb --enable
omarchy bar put io.github.radicalgitter.legion-super-key-rgb --section right
```

The button shows `RGB off` / `RGB on`; click it to toggle. Removing the bar button
alone does not stop the independent helper; use `legion-shortcut-lights off`.

## How it works and known limits

The Python process sends read-only Lua queries over Hyprland's IPC socket for
held modifiers and the current submap. It reads bindings and the active XKB
layout separately, then sends a temporary Spectrum bitmap. It never registers
Hyprland callbacks, replaces `hl.bind`, or reads `/dev/input`. Temporary IPC/device failures clear the overlay when possible and keep the
enabled helper waiting for recovery, with retries slowing from 250 ms to at most
once every five seconds. Resume forces a fresh controller connection and binding
query. `RGB on` means enabled, including while waiting; turning it off interrupts
the recovery wait. Fatal configuration errors still stop the helper, and systemd
runs cleanup after exit. Recovery never turns an explicitly disabled helper back on.

The bitmap uses LED positions from LenovoLegionToolkit's ISO keyboard layout.
The original theme is kept in the keyboard; no personal preset is bundled or
required. Neither the helper nor installer writes an effect slot, brightness,
firmware, or the Windows partition. A disconnected device or failed USB write
can prevent cleanup; reconnect/restart the device if necessary.

Hyprland 0.56.2 omits keycodes for some physical `code:…` bindings. The helper
recognizes the installed Omarchy workspace/resize/bar-panel descriptions as a
workaround. New named-key shortcuts appear automatically; unknown code-only
shortcuts are reported and omitted. Renaming those descriptions can require
updating the fallback. Workspace occupancy filtering recognizes Omarchy's
`Switch to workspace N` descriptions. Relative/named/custom workspace dispatchers
are not filtered. Submaps are respected; app-specific shortcut inhibition,
device-specific binding restrictions and nonstandard ignore-modifier bindings
are not fully modeled. Mouse shortcuts and the nonphysical `code:201` menu key
are omitted. Fn combinations remain firmware-controlled.

Swedish-layout exception: plain Super+slash shares physical 7 with workspace 7.
Its light follows workspace 7 occupancy; the monitor-scaling shortcut still works
when dark. Other shortcuts sharing a key can keep that key lit.

## Execution and local-file protections

- System commands use verified absolute root-owned paths. No PATH search, shell
  execution, or inherited subprocess environment is used. Python entry points
  use `/usr/bin/python3 -I`; HOME and runtime paths come from the current UID,
  and only a validated Hyprland instance signature is carried into the helper.
- The user service removes native loader injection variables before starting
  `/usr/bin/env -i`, which supplies only its explicit environment to Python.
  Quickshell processes use `clearEnvironment: true` and an explicit allowlist.
- Helper/installer commands have a three-second deadline (notifications: two
  seconds), a live 16 KiB combined stdout/stderr cap, and their own process group.
  Timeout, excess output, interruption, and completion all reap/kill that group.
  The bar adds GNU timeout envelopes of five seconds for status and eighteen
  seconds for toggles, with a one-second kill grace. It attaches no output
  collectors. A toggle failure appears in the tooltip rather than launching an
  additional unbounded notification command.
- Hyprland socket reads have a total 750 ms deadline and a 2 MiB response cap.
- Installer destinations, originals/backups, JSON state and helper lock files
  are traversed through owned directory descriptors with `O_NOFOLLOW`. File
  checks reject nonregular files, hardlinks, other owners and writable-by-others
  entries. Locks are not opened in append/truncate mode and have bounded waits.
- Updates use randomized exclusive temporary files, descriptor-relative atomic
  replacement, and file/directory fsync. Directory descriptors stay pinned if
  a pathname is renamed or replaced; redirected symlinks are never followed.

These protections assume a trusted OS and trusted user-owned project code.
They are not a sandbox against an attacker already able to replace this plugin's
code or control the user's session. Device I/O and hardware restoration can
still fail on disconnection. See `tests/test_safety.py` for exercised boundaries.

## Update / remove

To update, pull a reviewed version in this checkout and rerun `/usr/bin/python3 -I install.py`.
It leaves lighting off. The bar plugin is managed separately by Omarchy.

To remove the helper:

```bash
legion-shortcut-lights off
/usr/bin/python3 -I install.py --uninstall
```

Uninstall restores files that predated installation and removes unchanged files
it installed. Modified files and backup records are retained for manual review.
It leaves directories in place. Symlinked, hardlinked, or group/world-writable
files and directories fail closed instead of being repaired automatically.
Installation records are written before each destination replacement; if an
interrupted update reports a mismatch, review the retained original backup and
installation record before proceeding. If you added the Lua shortcut, remove those two
lines (or restore your previous binding), then reload and check Hyprland.

If you installed the bar plugin, remove it with:

```bash
omarchy plugin remove io.github.radicalgitter.legion-super-key-rgb
```

The installer does not own the udev rule. Remove that rule only if you installed
it for this project and no other RGB tool uses it, then reload udev rules. Existing
keyboard profiles and presets are never removed.

## Troubleshooting and tests

```bash
journalctl --user -u legion-shortcut-lights.service -n 50
/usr/bin/python3 -I tests/test_helper.py
/usr/bin/python3 -I tests/test_install.py
/usr/bin/python3 -I tests/test_safety.py
/usr/bin/python3 -I tests/test_resume.py
/usr/bin/python3 -I tests/test_controller_setup.py
omarchy plugin validate .
```

`check` requires a running Hyprland session; automated tests use mocks and a
temporary home directory, without touching hardware or the running desktop.
`--prefix <test-home> --no-reload` is an installer test mode; it skips systemd
interaction and installed-tool checks, but retains filesystem validation.
A `PermissionError` opening hidraw usually means the udev/seat access setup is
missing. A modifier-query error means the installed Hyprland API is incompatible;
leave the helper off and report your version and the error.

## License and credits

GPL-3.0-only. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
Spectrum protocol and keyboard geometry are derived from
[LenovoLegionToolkit](https://github.com/BartoszCichecki/LenovoLegionToolkit).
Built by RadicalGitter with Codex assistance and tested on the author's laptop.
