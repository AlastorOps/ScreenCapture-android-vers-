"""Color tokens for the app's theme presets.

Each named preset is a `Palette` instance registered in `PRESETS` (keyed by
its own `id`); `current()`/`current_accent()` expose whichever one is active
right now, and `set_theme()`/`set_accent()` (called by
ThemeManager.apply_theme(), the only intended caller) switch it. Adding a
new preset is just adding another `Palette(...)` below and registering it in
`PRESETS` -- nothing else in the app needs to change: the Settings dialog's
Theme dropdown is built from `PRESETS` directly (ui/windows/settings_dialog.py),
and every color consumer (the QSS templates, and the hand-painted widgets
below) already reads through `current()` rather than hardcoding a specific
preset.

Widgets that hand-paint themselves instead of relying on Qt stylesheets
(ToggleSwitch, StatusDot, VideoRenderWidget) read `current()`/
`current_accent()` *inside paintEvent()* rather than caching a color at
construction time -- that's what makes a theme change reach them without
each one needing its own signal/slot wiring: ThemeManager just calls
.update() on every widget after switching the module state, and the next
paint naturally picks up the new colors.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    id: str
    label: str
    is_dark: bool  # drives ThemeManager's hover-lighten-vs-darken and contrast-text fallback
    bg_window: str
    bg_panel: str
    bg_elevated: str
    border: str
    text_primary: str
    text_secondary: str
    text_muted: str
    success: str
    warning: str
    error: str


DARK = Palette(
    id="dark",
    label="Dark",
    is_dark=True,
    bg_window="#0e0f12",
    bg_panel="#15171b",
    bg_elevated="#1b1e23",
    border="#262a31",
    text_primary="#e6e6e6",
    text_secondary="#9aa0a8",
    text_muted="#5c6470",
    success="#89d99a",
    warning="#e0b25a",
    error="#e0645a",
)

LIGHT = Palette(
    id="light",
    label="Light",
    is_dark=False,
    bg_window="#f4f5f7",
    bg_panel="#ffffff",
    bg_elevated="#eceef1",
    border="#d7dbe0",
    text_primary="#1b1e23",
    text_secondary="#4a525c",
    text_muted="#828a94",
    success="#1f8a4c",
    warning="#93650d",
    error="#c23b30",
)

# A deeper, more blue-black dark preset than DARK -- distinct hue family
# (navy-tinted neutrals) rather than just a darker version of the same gray.
MIDNIGHT = Palette(
    id="midnight",
    label="Midnight",
    is_dark=True,
    bg_window="#05070d",
    bg_panel="#0a0e1a",
    bg_elevated="#111726",
    border="#1f2740",
    text_primary="#e8ecf5",
    text_secondary="#8b93ab",
    text_muted="#4d5570",
    success="#6ee7a8",
    warning="#f5c26b",
    error="#f2606a",
)

# Real Nord palette values (nordtheme.com) -- nord0-3 for backgrounds/
# borders, nord4/6 for text, nord11/13/14 for error/warning/success.
NORD = Palette(
    id="nord",
    label="Nord",
    is_dark=True,
    bg_window="#2e3440",
    bg_panel="#3b4252",
    bg_elevated="#434c5e",
    border="#4c566a",
    text_primary="#eceff4",
    text_secondary="#d8dee9",
    text_muted="#8792a6",
    success="#a3be8c",
    warning="#ebcb8b",
    error="#bf616a",
)

# Real Solarized palette values (ethanschoonover.com/solarized) -- base03/02
# for dark backgrounds, base1/0/01 for text, shared accent hues across both
# the dark and light variant (a defining trait of the actual Solarized spec).
SOLARIZED_DARK = Palette(
    id="solarized_dark",
    label="Solarized Dark",
    is_dark=True,
    bg_window="#002b36",
    bg_panel="#073642",
    bg_elevated="#0a4552",
    border="#586e75",
    text_primary="#93a1a1",
    text_secondary="#839496",
    text_muted="#657b83",
    success="#859900",
    warning="#b58900",
    error="#dc322f",
)

SOLARIZED_LIGHT = Palette(
    id="solarized_light",
    label="Solarized Light",
    is_dark=False,
    bg_window="#fdf6e3",
    bg_panel="#eee8d5",
    bg_elevated="#e4ddc4",
    border="#93a1a1",
    text_primary="#073642",
    text_secondary="#586e75",
    text_muted="#839496",
    success="#859900",
    warning="#b58900",
    error="#dc322f",
)

PRESETS: dict[str, Palette] = {
    p.id: p for p in (DARK, LIGHT, MIDNIGHT, NORD, SOLARIZED_DARK, SOLARIZED_LIGHT)
}

DEFAULT_ACCENT = "#7aa2f7"

FONT_MONO = "Cascadia Code, Consolas, monospace"
FONT_SANS = "Segoe UI Variable, Segoe UI, sans-serif"

_current_palette: Palette = DARK
_current_accent: str = DEFAULT_ACCENT


def current() -> Palette:
    return _current_palette


def current_accent() -> str:
    return _current_accent


def set_theme(theme_id: str) -> None:
    """Unknown ids (e.g. a persisted setting from before a preset existed,
    or a preset that got removed) fall back to DARK rather than raising --
    a theme id is user-facing config, not a programming contract."""
    global _current_palette
    _current_palette = PRESETS.get(theme_id, DARK)


def set_accent(accent_hex: str) -> None:
    global _current_accent
    _current_accent = accent_hex
