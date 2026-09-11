# Legion Super Key RGB

**Hold Super. See what you can press.**

Turn a Lenovo Legion RGB keyboard into a shortcut guide for Omarchy / Hyprland.
Available shortcut keys glow pink, modifiers glow blue, and releasing Super
restores your existing hardware lighting and animations.

- Add Shift, Ctrl, or Alt to show shortcuts for that exact combination.
- Empty workspaces stay dark; moving a window to an empty workspace stays available.
- Reads live bindings every five seconds and workspace occupancy every 100 ms.
- Checks modifiers every 20 ms. Restoring the profile includes a 50 ms firmware query.
- Optional Omarchy bar button, terminal toggle, and Super+Alt+K binding.
- Off by default, no login autostart, no compositor hooks or monkey-patching.

## Compatibility

**Experimental; tested on one machine:** Lenovo Legion 7 16IRX9, ISO Swedish
keyboard, USB Spectrum controller **048d:c997**, Omarchy **4.0.3**, Hyprland
**0.56.2**. Other Legion models, ANSI keyboards, and other Hyprland versions are
not verified. This is not a generic OpenRGB plugin or a four-zone RGB driver.
The helper refuses a different controller ID.

The hardware overlay, release restoration, CLI toggle and workspace filtering
were tested on that laptop. The optional bar widget has manifest and static QML
validation; visual bar testing is still pending.

Requires Linux, Python 3.10+, systemd user services, libxkbcommon, and a Hyprland
build exposing `repl`, `hl.is_key_down`, and `hl.get_current_submap`. Notifications
use `notify-send` (Arch package `libnotify`). The bar widget additionally requires
Omarchy Quattro's Quickshell shell. The helper works independently of which shell
is visible, including when using Caelestia on the tested Omarchy installation.

## Install the helper

Clone and inspect the repository, then run the installer as your normal user:

```bash
git clone https://github.com/RadicalGitter/legion-super-key-rgb.git
cd legion-super-key-rgb
python3 install.py
```

This installs a command in `~/.local/bin`, two Python files in
`~/.local/share/legion-super-key-rgb`, and a user service. It backs up any existing
files it replaces and refuses updates over locally modified installed files.
It stops an already-running helper and leaves it **off**. It does not edit your
Hyprland configuration, change the bar, install packages, run privileged commands,
or write any keyboard effect profiles. Ensure `~/.local/bin` is on your PATH.

### Controller access (one-time, only if not already configured)

Inspect `packaging/70-legion-spectrum-rgb.rules` before installing it. It grants
the active local user access to the matching controller's raw HID interface;
that device interface also belongs to the keyboard, so this is broader than
permission to change individual LED colors. The helper itself does not read
input-event devices or log ordinary keystrokes.

If `/etc/udev/rules.d/70-legion-spectrum-rgb.rules` already exists, compare it
and keep it if equivalent. Do not overwrite another rule without reviewing it.
Otherwise, from an interactive terminal:

```bash
sudo install -Dm644 packaging/70-legion-spectrum-rgb.rules /etc/udev/rules.d/70-legion-spectrum-rgb.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw
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
The shortcut only starts/stops the external helper. Nothing runs at login.

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
Hyprland callbacks, replaces `hl.bind`, or reads `/dev/input`. An IPC failure
stops the helper and clears the overlay. Systemd also runs cleanup after an
unexpected service exit. There is no automatic restart loop.

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

## Update / remove

To update, pull a reviewed version in this checkout and rerun `python3 install.py`.
It leaves lighting off. The bar plugin is managed separately by Omarchy.

To remove the helper:

```bash
legion-shortcut-lights off
python3 install.py --uninstall
```

Uninstall restores files that predated installation and removes unchanged files
it installed. Modified files and backup records are retained for manual review.
It leaves directories in place. If you added the Lua shortcut, remove those two
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
python3 tests/test_helper.py
python3 tests/test_install.py
omarchy plugin validate .
```

`check` requires a running Hyprland session; automated tests use mocks and a
temporary home directory, without touching hardware or the running desktop.
A `PermissionError` opening hidraw usually means the udev/seat access setup is
missing. A modifier-query error means the installed Hyprland API is incompatible;
leave the helper off and report your version and the error.

## License and credits

GPL-3.0-only. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
Spectrum protocol and keyboard geometry are derived from
[LenovoLegionToolkit](https://github.com/BartoszCichecki/LenovoLegionToolkit).
Built by RadicalGitter with Codex assistance and tested on the author's laptop.
