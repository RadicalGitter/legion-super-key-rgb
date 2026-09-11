# Attribution

Legion Super Key RGB, copyright 2026 RadicalGitter, is distributed under
GPL-3.0-only. The Spectrum protocol translation and physical LED mapping draw
on the GPLv3 LenovoLegionToolkit project by Bartosz Cichecki and contributors:

- https://github.com/BartoszCichecki/LenovoLegionToolkit/blob/master/LenovoLegionToolkit.Lib/Native.cs
- https://github.com/BartoszCichecki/LenovoLegionToolkit/blob/master/LenovoLegionToolkit.Lib/Controllers/SpectrumKeyboardBacklightController.cs
- https://github.com/BartoszCichecki/LenovoLegionToolkit/blob/master/LenovoLegionToolkit.WPF/Controls/KeyboardBacklight/Spectrum/Device/SpectrumKeyboardISOControl.xaml

These Python implementations adapt the temporary Aurora start/stop, bitmap,
compatibility/profile query, and ISO LED positions to Linux hidraw and Hyprland.
The Omarchy-specific missing-keycode fallback reflects the author's installed
Omarchy 4.0.3 tiling/utilities bindings; it does not execute configuration files.
The optional bar widget uses the public Omarchy Quattro plugin interfaces.
No original Windows preset or upstream C# source files are bundled.
