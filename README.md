# AndroidLink

Android-to-Windows USB companion and control center. Connects an Android phone to a
Windows PC over USB Type-C for screen casting, remote mouse/keyboard control, Android
audio playback, a phone-camera-as-Windows-webcam and phone-mic-as-Windows-microphone,
and PC-side recording/screenshots — no Wi-Fi, cloud, or internet required, and nothing
leaves the machine over USB.

Every feature above is independently toggleable (Control and Audio require Screen Cast
to be on, since they share its underlying session — explained in the UI itself; Camera
and Mic don't). The UI is a dark, compact, dockable-panel desktop app built with
PySide6, driving a vendored [scrcpy](https://github.com/Genymobile/scrcpy) server
directly over ADB — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for why there's no
separate Android companion app to build or install.

**Documentation:**
[Setup Guide](docs/SETUP.md) ·
[Troubleshooting](docs/TROUBLESHOOTING.md) ·
[Architecture](docs/ARCHITECTURE.md)
(the in-app **Help → Setup Guide** also runs live checks against your actual machine)

## Requirements

* Windows 10/11, 64-bit.
* An Android phone, Android 10 (API 29) or newer, with a data-capable USB cable.
* [Android Platform Tools](https://developer.android.com/tools/releases/platform-tools) (`adb`) on your PATH.
* Optional: [OBS Studio](https://obsproject.com/)/[Unity Capture](https://github.com/schellingb/UnityCapture)
  for the Camera → virtual webcam feature; [VB-Audio Virtual Cable](https://vb-audio.com/Cable/)/
  [VoiceMeeter](https://vb-audio.com/Voicemeeter/) for the Mic → virtual microphone feature.

Full step-by-step instructions (including enabling USB debugging on the phone) are in
[docs/SETUP.md](docs/SETUP.md).

## Installation & running

**Installer:** download/build `AndroidLink.msi` (see
[Building the Windows Installer](#building-the-windows-installer-msi) below) and run it —
a full wizard (what AndroidLink is, an important-notice page, a features page, an
install-requirements page, install location, confirmation) installs to Program Files
with Start Menu/Desktop shortcuts, a normal Add/Remove Programs entry, and a real
`Uninstall.exe` in the install folder. No Python required.

**Prebuilt exe (no installer):** download/build `AndroidLink.exe` (see
[Building the Windows executable](#building-the-windows-executable) below) and run it
directly from wherever you put it — no install step, no Python required.

**From source (development):**

```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python -m androidlink.app.main
```

**Testing:**

```
pytest
```

**Building the Windows executable:**

```
pip install -e ".[build]"
pyinstaller packaging/androidlink.spec --distpath dist --workpath build --noconfirm
```

Produces `dist/AndroidLink.exe`, a standalone onefile executable (no Python install
required to run it). The spec bundles the theme's QSS files and the vendored
scrcpy-server jar. There is no separate "build the Android companion app" step —
AndroidLink has no companion Android app in its architecture; see
[docs/ARCHITECTURE.md § No companion Android app](docs/ARCHITECTURE.md#no-companion-android-app)
for why.

**Building the Windows Installer (.msi):**

```
pip install -e ".[build]"
pyinstaller packaging/androidlink.spec --distpath dist --workpath build --noconfirm
python packaging/build_msi.py
```

Produces `dist/AndroidLink.msi` from the `AndroidLink.exe` built by the step above (build
the exe first — `build_msi.py` wraps it, it doesn't rebuild the app itself). Built with
the [WiX Toolset](https://wixtoolset.org/) v3, whose standalone binaries (candle.exe/
light.exe) `build_msi.py` downloads automatically into `packaging/.wix-tools/` on first
run — no separate install, nothing added to PATH or the registry. `build_msi.py` also
builds a small `Uninstall.exe` (from `packaging/uninstall_stub.py`) that gets installed
alongside the app.

The installer is a full wizard, not a silent drop: an Installer Information page
explaining what AndroidLink is, an Important Notice page (USB/ADB, permissions,
resource-usage warnings), a Features page (with a Camera Performance Notice), an
Installation Requirements page, an install-location picker (with an optional Desktop
shortcut checkbox), and a Ready to Install confirmation before anything is written to
disk. It's a real Windows Installer package: per-machine install to
`Program Files\AndroidLink` (a UAC prompt is expected), Start Menu and Desktop
shortcuts, a standard Add/Remove Programs entry, and a real `Uninstall.exe` inside the
install folder as a second way to uninstall. `<MajorUpgrade>` handles installing a
newer build over an older one automatically (the old version is removed as part of
installing the new one) — see `packaging/androidlink.wxs` and
`packaging/build_msi.py`'s module docstrings for the full detail, including exactly
which parts of the wizard's dialog wiring were cross-checked against WiX's own real
source rather than assumed from memory.

## Virtual webcam / virtual microphone

The Camera feature exposes the phone's camera as a real Windows video-capture device
(via [pyvirtualcam](https://github.com/letmaik/pyvirtualcam), backed by an existing OBS
Virtual Camera or Unity Capture install — neither is bundled). The Mic feature exposes
the phone's microphone as a real Windows input device via a virtual-audio-cable driver
(e.g. VB-Audio Virtual Cable — Windows has no first-party "virtual microphone" API the
way it does for webcams). Neither backend is installed automatically (prompt.md section
25: never silently install drivers) — if AndroidLink reports one missing, it names
exactly what to install. Full instructions:
[docs/SETUP.md § 7](docs/SETUP.md#7-virtual-webcam-setup-phone-camera--windows-apps) and
[§ 8](docs/SETUP.md#8-virtual-microphone-setup-phone-mic--windows-apps).

## Troubleshooting & known hardware limitations

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for device/USB/ADB issues, codec
and decoder errors, camera/microphone permission and virtual-device problems, and
recording failures — every in-app error message is written to explain what's wrong and
what to do about it (never a bare "Error: subprocess failed"), and that document expands
on each one. It also lists known hardware limitations (no GPU usage metric, no camera
resolution selection, no automatic reconnect-on-launch, etc.) that are deliberate
platform/scope constraints, not bugs.

## Development phases

This project was built in phases (see `prompt.md` for the full spec). All 11 phases are
now implemented:

- **Phase 1: project foundation** — application shell, theming, settings persistence, logging.
- **Phase 2: USB/ADB device detection** — live device list, connect/disconnect.
- **Phase 3: screen casting** — drives a vendored [scrcpy](https://github.com/Genymobile/scrcpy)
  server over ADB and decodes/renders its video stream. The wire protocol and decoder
  are unit-tested against a real H.264 stream, but the end-to-end adb push/reverse
  tunnel/socket path has not been exercised against real hardware (no Android device
  was available during development) — try it with a real device and see
  `androidlink/streaming/transport.py`'s module docstring, or
  [docs/ARCHITECTURE.md § Hardware-verification status](docs/ARCHITECTURE.md#hardware-verification-status),
  for details. **Fullscreen mode**
  (prompt.md section 8) is available via the Screen panel's Fullscreen button, the F11 key,
  or Escape to exit — it hides everything but the Android screen mirror. Mouse/touch
  coordinate mapping already keys off the render widget's own size rather than a fixed
  panel size, so it stays correct in fullscreen with no special-casing needed.
- **Phase 4: remote control** — PC mouse (tap/drag/swipe/scroll) and keyboard forwarded
  to the device over scrcpy's control socket. The Control toggle requires Cast to be
  enabled first (the control socket is part of the same scrcpy-server session as
  video). Mouse/keyboard-to-wire-protocol encoding is unit-tested with real Qt events;
  the control socket itself carries the same hardware-unverified caveat as Phase 3.
- **Phase 5: Android audio → PC** — plays the device's audio (Opus by default) through
  the default Windows output device via QAudioSink, with PC-side volume/mute. The
  Audio toggle also requires Cast to be enabled first — in this implementation audio
  shares one scrcpy-server session with video/control rather than opening a second
  independent session, which is a practical trade-off (avoids a second ADB tunnel and
  state machine), not a hard protocol requirement — scrcpy itself supports audio-only
  mirroring. Device-side audio capture failures are detected and surfaced in the UI
  (Audio toggle is forced off with an explanation) rather than failing silently.
  Decode is unit-tested against a real Opus stream; the audio socket itself carries
  the same hardware-unverified caveat as Phases 3-4. **Audio defaults to enabled**
  (`settings.audio.enabled`, defaults `true`) — most people casting the screen also want
  to hear the device, so Cast turning on requests audio automatically unless previously
  turned off, and that choice persists across restarts.
- **Phase 6: Android camera → Windows virtual webcam** — mirrors a device camera into
  a real Windows virtual camera device via
  [pyvirtualcam](https://github.com/letmaik/pyvirtualcam) (OBS Virtual Camera or Unity
  Capture backend — neither is bundled or auto-installed; if neither is present the
  Camera toggle shows a clear "no virtual camera backend found" message rather than
  failing silently). Unlike Control/Audio, this is a genuinely independent scrcpy-server
  session (its own ADB tunnel, no shared state with screen casting), matching how
  camera mirroring actually works in scrcpy. Camera detection (`list_cameras=true`)
  and the wire-protocol parsing are unit-tested against real data; the live camera
  socket and actual virtual-camera output are hardware-unverified, same caveat as
  Phases 3-5 — no Android camera stream or virtual camera backend was available to
  test end-to-end during development. Per-resolution selection isn't implemented yet
  (device default is always used); FPS selection uses real per-camera options from
  device capability detection.
- **Phase 7: Android microphone → Windows microphone** — mirrors the device's microphone
  into a Windows input device that apps like Discord/OBS/Zoom/Teams can select as a mic,
  via a virtual-audio-cable driver (e.g. [VB-Audio Virtual
  Cable](https://vb-audio.com/Cable/), or VoiceMeeter) — Windows has no first-party
  "virtual microphone" API the way pyvirtualcam covers webcams, so this is the standard
  approach: decoded PCM is written to the cable's playback endpoint via QAudioSink, and
  the cable's matching recording endpoint is what other apps see as a microphone. Like
  Camera, this is a genuinely independent scrcpy-server session — video is disabled
  entirely rather than sharing Cast's session, since mic capture has nothing to do with
  screen mirroring. Supports mute/unmute and PC-side input volume, and an Input source
  selector exposing scrcpy's protocol-level `audio_source` values (mic,
  mic-unprocessed, mic-voice-communication, mic-voice-recognition, mic-camcorder) — these
  are the sources scrcpy itself supports, not per-device detected capabilities (no
  companion app exists to query Android's AudioManager directly, so this is surfaced
  honestly as a fixed protocol list rather than faked detection). If no virtual-audio-cable
  driver is installed, the Mic toggle shows a clear message naming what to install rather
  than failing silently or faking output. Device-side mic capture failures are detected
  and surfaced the same way as Phase 5's audio (Mic toggle forced off with an explanation).
  The device-name-then-audio-header handshake and packet parsing are unit-tested against a
  real Opus stream; the live mic socket and actual virtual-cable output are
  hardware-unverified, same caveat as Phases 3-6 — no Android mic stream or virtual-cable
  driver was available to test end-to-end during development.
- **Phase 8: PC-side recording** — records the live cast to an MP4 file entirely on the PC
  (prompt.md section 14: never require the Android device to do the recording). Encoding
  runs on its own background thread, fed the same already-decoded frames being rendered
  (no separate capture path), so it never adds latency to live casting or the GUI; a
  bounded frame queue drops the oldest frame if the encoder ever falls behind rather than
  blocking the app. Hardware encoding (NVENC/QSV/AMF) is tried first and automatically
  falls back to libx264 — verified for real on this dev machine, which has no hardware
  encoder available, so it genuinely exercises the fallback path every time. Supports
  start/stop/pause/resume, a live recording status and timer, and PC-side screenshots
  (PNG) — all in the Status panel, enabled only while Cast is active since there's nothing
  to record or screenshot otherwise. Save location, format, and quality are configurable
  from Settings → Recording (Phase 9). When Android audio is enabled, its decoded
  PCM is muxed into the recording too (AAC), via the same audio already being played back
  — no separate capture path, added to the queue alongside video frames and encoded on the
  same background thread. The encoder-selection/fallback logic and the full
  record-then-decode-back round trip (video and video+audio) are tested against real
  written MP4 files, not mocked.
- **Phase 9: polish** — complete:
  - **Customizable/savable panel layout** (prompt.md section 16): Device/Screen/Status
    are now `QDockWidget`s, so show/hide, rearrange, float, and resize all come from
    Qt's native dock machinery — a View menu exposes a checkable toggle per panel plus
    "Restore Default Layout," and the arrangement (`QMainWindow.saveState()`, base64-
    encoded) persists to `settings.general.layout_state` across restarts. The
    Performance/Quality slider stayed fixed as a non-movable bottom toolbar, not a
    dockable panel, per the spec at the time — **superseded in Phase 11**, where it
    moved into the Device panel (see Phase 11 below). The slider snaps to discrete levels of 10 as you
    drag it (`ui/widgets/slider_labeled.py`'s `snap_value()`, with tick marks showing
    where it'll land) rather than stopping at an arbitrary pixel-derived value, and
    shows a live resolution readout next to it (e.g. "~1080p (1920px)") reflecting the
    real profile `resolve_streaming_profile()` would use for the next cast —
    deliberately approximate ("~") since the exact output depends on the connected
    device's real aspect ratio, not a fabricated exact WxH
    (`streaming/performance.py`'s `describe_resolution()`); both the snapping and the
    readout are mirrored in the Settings dialog's copy of the slider.
  - **Full multi-section Settings page** (prompt.md section 27): General, Streaming
    (performance/quality default + resolution/FPS/bitrate advanced overrides — codec
    forcing is greyed out, since scrcpy always auto-selects the device's codec), Audio
    (enabled/volume/output device — real device picker via `QMediaDevices`), Camera and
    Microphone (selection/resolution/FPS/input source shown as read-only summaries
    pointing at the Device panel, where the live, device-dependent controls actually
    live — volume/mute are directly editable), Recording (save location via a real
    folder picker overriding the default Videos/Pictures folders, quality → target
    bitrate; format is MP4-only and greyed out), Device (connected device, and a
    permanently-disabled "auto-reconnect" checkbox explaining why — it would violate
    the app's "never auto-connect" principle), and Diagnostics (logging level, debug
    mode, both applied live). Every control is either wired to a real settings field or
    visibly disabled with a tooltip explaining why, matching the honesty pattern
    established in `device_panel.py`.
  - **Error message catalog** (prompt.md section 21): `androidlink/utils/errors.py`
    centralizes every user-facing failure (ADB unavailable, device unauthorized/offline/
    disconnected, unsupported codec, camera/microphone permission denied, virtual
    camera/microphone unavailable, decoder/encoder failure, USB bandwidth problems, and
    more) as a message + actionable guidance pair, referenced from
    `device/manager.py`, `streaming/transport.py`, `camera/*`, `audio/*`, and
    `recording/*` instead of the ad-hoc strings that used to be scattered across them.
    Auditing this also found and fixed two real gaps: an unsupported video/audio codec
    (e.g. a device sending VP8/VP9, or an unrecognized audio codec id) could previously
    escape as an unhandled exception inside a Qt slot instead of being caught and
    surfaced as a connection failure — now guarded the same way nearby malformed-data
    cases already were, with regression tests.
  - **Real Diagnostics** (prompt.md sections 20/33/34: never fabricate a performance
    number). The Status panel's Stream FPS, Render FPS, Dropped Frames, Decode Latency,
    Bitrate, Resolution, and Codec readouts are all genuinely measured — decoded-frame
    counting and byte counting in `streaming/transport.py`, a real paint-event counter in
    `streaming/renderer.py`, and process CPU/RAM via `psutil` in `utils/system_stats.py`
    (normalized to 0-100% across all cores). "Dropped frames" comes from a real counter
    added to `LatestValueBox` that tracks values overwritten before ever being read, not a
    guess. GPU usage is left as an honest "—" (with a tooltip explaining why) rather than
    faked — reliable cross-vendor GPU utilization on Windows needs Performance Data
    Helper counter queries, not implemented yet.
  - **Settings persistence** (prompt.md section 29): performance/quality slider (plus
    Phase 9's resolution/FPS/bitrate advanced overrides), Android audio volume/mute/output
    device, camera selection/FPS, microphone selection/volume/mute, recording save
    location/format/quality, and logging level/debug mode now all survive a restart,
    loaded into their controls on launch and saved on change (slider/volume changes save
    once on release, not per drag tick, to avoid hammering disk). Building this surfaced
    and fixed two real bugs: populating the camera/FPS dropdowns was firing the same
    "selection changed" signals a real user action would, which silently overwrote a
    just-loaded persisted camera selection before it was ever applied — dropdown
    population is now signal-blocked so only genuine user choices get persisted.
    "Selected device"/reconnect behavior is intentionally not persisted — it interacts
    with this app's "never auto-connect" principle closely enough that it's a
    permanently-disabled, explained setting rather than a half-built one.
  - **Setup wizard** (prompt.md section 18): a guided-setup dialog (`setup/wizard.py`,
    `setup/checks.py`) that runs automatically on first launch (and any time after via
    Help → Setup Guide) checking ADB availability, USB device detection, USB debugging
    authorization, Android version, the virtual webcam backend, and the virtual
    microphone driver — all against real live state (`DeviceManager`, the same
    non-invasive backend probes the Camera/Mic features already use), updating live as
    devices connect/disconnect while the dialog is open. Camera/microphone permission and
    "required companion app" can't be meaningfully checked ahead of time (no companion app
    exists in this project's actual architecture — it drives scrcpy directly — and Android
    doesn't expose a way to query a not-yet-running process's future runtime permissions),
    so those rows say so honestly instead of faking a pass/fail. Deliberately has no "Fix
    Automatically" button: every real fix here is either installing third-party software
    or a physical action on the phone itself, neither of which this app should do silently
    (prompt.md sections 25/37) — a "Recheck" button re-runs the real checks instead.
  - **Packaging & troubleshooting docs**: [docs/SETUP.md](docs/SETUP.md),
    [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md), and
    [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), linked from this README.
  - **Real-hardware bug fix**: extended live testing against a real device (this
    project's first, once one was actually available) surfaced a genuine adb-server
    stability bug that manifested as Android Audio/Screen Cast/Camera unexpectedly
    disconnecting mid-session. `device/manager.py`'s device-info polling could
    re-spawn an `adb shell getprop` call for the same device on every single 1.5s
    poll tick indefinitely whenever the previous one never completed (including a
    separate, real "Internal C++ object already deleted" PySide6/Qt race that could
    crash the device-list poll handler entirely on Windows) — under sustained real
    use this measurably destabilized the local adb server (`adb devices` starts
    returning empty despite the device staying physically connected) enough to drop
    active `adb reverse` tunnels, which is exactly what scrcpy-server sessions
    depend on. Both handlers are now guarded against the crash, and a device's info
    is only ever fetched once at a time. See
    [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md#the-connection-to-the-device-was-lost-mid-session).
  - **Silent-audio trap fix**: the same real-hardware session also found that
    installing a virtual-audio-cable driver (e.g. VB-Audio Virtual Cable, to use the
    Mic feature) can silently become *Windows'* system-wide default playback device
    — which makes Android Audio's "System Default" output setting decode and play
    successfully into the cable instead of real speakers, with no error anywhere in
    the pipeline, just silence. Settings → Audio now detects this
    (`audio/virtual_audio.py`'s `is_likely_virtual_cable()`) and shows an explicit
    warning naming the actual device in use, with the fix (pick a real output device
    there, or change the Windows default) — matching prompt.md section 21/33's "never
    fail silently."
  - **Dual audio output**: since a virtual-audio-cable driver is often installed
    specifically so another app (Discord/OBS/etc.) can pick up the device's audio, not
    just to avoid it, `AudioPlayback` (audio/playback.py) can now play Android's audio
    to a *second* output device at the same time as the primary one — e.g. real
    speakers so you can hear it, and a virtual-audio-cable at once so another app can
    too, rather than an either/or choice. Settings → Audio's new "Also Output To"
    picker controls it (`settings.audio.secondary_output_device_id`); picking the same
    device as the primary output, or a device that's no longer present, degrades
    gracefully to the primary-only behavior rather than erroring. Verified end-to-end
    against real hardware: audio streamed continuously to both a real output device and
    a real VB-Audio Virtual Cable device at once with no drops.
  - **Settings apply live, not just "next time"**: changing Streaming's Resolution/FPS/
    Bitrate overrides, the Performance/Quality default, or Audio's Output Device/Also
    Output To in the Settings dialog now restarts an already-active cast session
    automatically (`CastingController.restart_if_casting()`) instead of leaving the
    change stuck until the user manually toggles Cast off and back on — the same way
    Control/Audio already had to, since scrcpy has no way to change these on a running
    session. Audio and Microphone Volume/Mute go a step further and apply directly to
    the live session (no restart, no glitch) via new `apply_audio_volume()`/
    `apply_audio_muted()`/`apply_volume()`/`apply_muted()` methods on
    `CastingController`/`MicController`. Verified against real hardware: changing the
    Resolution override in Settings while actively casting restarted the session with
    the new resolution automatically, with no manual reconnect.
  - **Fixed a real race in every restart-on-setting-change path**: the first version of
    the above (and the pre-existing Control/Audio-toggle and Camera/Mic-selection
    restarts, which share the same code shape) called `stop()` immediately followed by
    `start()`. `*Session.stop()` posts a *queued* call to its worker thread, so it
    returns before the old scrcpy-server process -- and the device's hardware video
    encoder it's holding -- has actually been torn down. Confirmed directly against real
    hardware: this let a "new" session start while the old one was still shutting down,
    silently keeping the old resolution active instead of applying the change (a second
    `cast_session_started` did fire, but with the *old* dimensions). `CastingController`,
    `CameraController`, and `MicController` now wait for the old session's `stopped`
    signal (only emitted once its worker thread has fully unwound) before starting the
    replacement. Re-verified against real hardware after the fix: the second session
    genuinely came back at the new resolution (1920×1200 → 1280×800).
  - **Performance/Quality slider gets its own Refresh button**: the main window's
    slider bar (unlike the Settings dialog's copy, which restarts automatically the
    moment you release it) never auto-restarts on drag — doing so on every drag tick
    would be far more disruptive than useful. Instead, a new "↻ Refresh" button next to
    the resolution readout applies the current slider position to an already-active
    cast session on demand (`CastingController.restart_if_casting()`), enabled only
    while actually casting. Verified against real hardware: dragging the slider alone
    left the session untouched; clicking Refresh restarted it and the device genuinely
    switched resolution (1920×1200 → 1280×800). **Superseded in Phase 11**: this
    dedicated slider+Refresh-button toolbar was removed entirely when the slider moved
    into the Device panel and started applying live on release instead (no separate
    button needed any more) — see Phase 11 below.
- **Phase 10: theme system fix, uncapped FPS, and pipeline performance** — complete:
  - **Theme fix**: the Theme dropdown in Settings → General was permanently disabled
    ("Dark" only) and, more importantly, changing the accent color never actually
    reached every control — `ToggleSwitch` (the Cast/Audio/Mic/Debug Mode toggles
    throughout the app) hand-paints itself and had captured `palette.DEFAULT_ACCENT`
    once at construction time, so it stayed the default blue forever regardless of the
    user's chosen accent, even freshly after picking a custom color. The matching QSS
    rule for it (`ToggleSwitch[checked="true"]`) was dead code — a hand-painted
    `QWidget` doesn't apply stylesheet `background-color` from a property selector.
    Root cause fixed at the architecture level: `ui/themes/palette.py` now holds
    mutable Dark/Light `Palette` instances plus the current accent as live module
    state (`palette.current()`/`palette.current_accent()`), and every hand-painted
    widget (`ToggleSwitch`, `StatusDot`, `VideoRenderWidget`'s letterbox background)
    reads it fresh inside `paintEvent()` instead of caching a color — so a theme
    change reaches them with zero per-widget wiring, and a widget created *after* a
    theme switch already paints correctly. A real Light theme is now implemented (not
    just scaffolded): `ThemeManager.apply_theme(accent, mode)` builds the app-wide QSS
    from templated `base.qss.tmpl`/`accent.qss.tmpl` files against whichever palette is
    active, and `.update()`s every existing widget so hand-painted ones repaint
    immediately too. Both dark/light mode and the custom accent color persist across
    restarts (`settings.general.theme`/`accent_color`). Verified: dark→light switch,
    custom accent reaching a `ToggleSwitch` live, and both surviving a simulated
    restart.
  - **Follow-up fix: Settings dialog stayed white regardless of theme.** Caught by
    actually rendering and inspecting screenshots of the dialog in both modes (not
    just checking hex values) — the Settings dialog's tab content area (every
    `QTabWidget` page) stayed a light/white panel in Dark mode too, because on
    Windows a plain `QWidget` used as a tab page is painted by the native style using
    the system window color instead of inheriting the `QDialog { background-color:
    ... }` rule above it. Fixed with explicit `QTabWidget::pane`/`QTabBar::tab`/
    `QTabWidget QWidget` rules in `base.qss.tmpl`. Re-verified visually across the
    General and Streaming tabs in both themes after the fix.
  - **More theme presets, not just Dark/Light**: `ui/themes/palette.py` is now an open
    registry (`palette.PRESETS`, keyed by preset id) instead of two hardcoded
    `Palette` constants — Settings → General's Theme dropdown is built directly from
    that registry, so adding a new preset is just adding another `Palette(...)` there,
    nothing else in the app needs to change. Four new presets ship alongside Dark/
    Light: **Midnight** (a deeper navy-black dark variant), **Nord**, **Solarized
    Dark**, and **Solarized Light** (the latter two using the real published Nord/
    Solarized color values, not approximations). `GeneralSettings.theme` is a plain
    `str` rather than a fixed `Literal` for the same reason — an unrecognized/removed
    preset id falls back to Dark (`palette.set_theme()`) rather than failing
    validation. Verified by rendering and inspecting actual screenshots of the
    Settings dialog and main window under Nord, Solarized Light, and Midnight, not
    just checking hex values.
  - **Removed the hardcoded 60fps cap**: `streaming/performance.py` unconditionally
    requested `max_fps=60` for every session regardless of what the device's screen
    could actually do, and Settings → Streaming's FPS dropdown only ever offered
    "Automatic (60)" / 30 / 60 — so even a 90/120/144Hz device was silently capped.
    A new `device/display_info.py` parses `adb shell dumpsys display` (the same
    source every other screen-mirroring tool ultimately reads) for the device's real
    active and hardware-supported refresh rates, fetched once per connection by
    `DeviceManager` alongside the existing model/Android-version lookup (with the same
    "never retry a permanent parse failure every poll" guard that a previous real bug
    in this codebase needed). "Automatic" FPS now targets that detected rate instead
    of a fixed number; Settings → Streaming's FPS dropdown is now built dynamically
    from the connected device's actual supported list, and the main window/Settings
    resolution readouts both show the live `@ N fps` target. Verified against a real
    165Hz-capable device (Lenovo TB321FU, currently running at 120Hz): detection
    reported `120Hz active, supports (30, 60, 90, 120, 144, 165)`, and a live cast
    session genuinely requested and started at `max_fps=120` (previously always 60).
  - **Real hardware-accelerated video decode**: `streaming/decoder.py`'s docstring
    claimed FFmpeg picks a hardware decoder (D3D11VA/DXVA2/NVDEC) automatically —
    checked directly against this project's actual PyAV 18 install and that turned out
    to be false: `av.CodecContext.create()` alone always decodes in software, and
    `CodecContext.hwaccel` isn't even settable after construction. Fixed by requesting
    D3D11VA (falling back to the older DXVA2, then software) explicitly via
    `CodecContext.create(..., hwaccel=HWAccel(...))`, decided once at session start —
    verified against this project's own real H.264 fixture that both backends decode
    correctly and `frame.to_ndarray()` transparently downloads/converts the GPU-
    resident frame, so nothing downstream needed to change. `hardware_accelerated` is
    exposed per-session and shown in the Status panel's Codec readout as "H264 (HW)"/
    "(SW)". A first attempt also retried a failed decode by rebuilding the codec
    context in software mid-session — reverted after it broke a real regression test
    (`test_recovers_from_a_corrupt_packet_without_desyncing`): rebuilding the context
    to retry discarded the decoder's reference-frame state, so the *next legitimate*
    frame after a single bad packet silently failed too. The existing per-packet
    exception handling in `streaming/transport.py` already recovers from a bad packet
    correctly without that risk, so hw/software is now decided once at construction
    and left alone. Verified live: `Video decode: using hardware acceleration
    (d3d11va)` logged and confirmed on a real cast session.
  - **Latency: TCP_NODELAY on every streaming socket**: none of the video/audio/
    control sockets (`streaming/transport.py`, `camera/camera_session.py`,
    `audio/mic_session.py`) had ever disabled Nagle's algorithm, which can batch small
    writes for tens of milliseconds waiting for a full segment or peer ACK — latency a
    real-time control/video/audio socket shouldn't be paying, on a loopback `adb
    reverse` connection same as a real network one. All now set Qt's
    `LowDelayOption` (`TCP_NODELAY`) right after accepting the connection.
  - **Frame queue / low-latency delivery** (prompt.md sections 11/34) was already
    correctly architected before this phase and didn't need changing: `LatestValueBox`
    holds at most one pending frame, so a consumer that falls behind gets the newest
    frame instead of an accumulating backlog, with a genuine dropped-frame counter
    (not fabricated) surfaced in Diagnostics.
  - **FPS is deliberately not traded off by the Performance/Quality slider**: only
    resolution and bitrate move along it now (previously all three anchor profiles
    hardcoded the same 60). Automatic FPS targets the same detected device rate at
    every slider position; a lighter resolution/bitrate budget at the Performance end
    make a high frame rate easier to sustain in practice than the number "60" ever
    did on its own, matching prompt.md section 12's Performance-favors-FPS /
    Quality-favors-resolution intent without inventing an unmeasured FPS-vs-quality
    tradeoff curve.
  - Diagnostics continue to report only genuinely measured values — the live run that
    verified all of the above requested 120fps at 1920×1200 and *measured* 88fps
    actually decoded, which is reported as-is rather than rounded up to the target;
    the real bottleneck at that combination is the device's own encoder/USB throughput,
    not anything left uncapped in this app's Python/Qt pipeline.
- **Phase 11: 165fps ceiling with Automatic FPS, crash-safety hardening, and camera UI
  overhaul** — complete:
  - **165fps ceiling + Automatic FPS mode**: `MAX_STREAM_FPS` is now a hard 165 (never
    higher, regardless of how fast a connected panel actually is), with Automatic mode
    starting optimistic — it targets the device's highest *supported* refresh rate
    (`device.supported_refresh_rates_hz`), not just whatever it's *actively* running at
    right now, since many Android devices idle at a lower rate than their panel actually
    supports. A new `streaming/fps_stability.py` watches real delivered-FPS and
    dropped-frame samples over rolling multi-second windows (`WINDOW_SAMPLES = 8`,
    roughly 8 seconds per window at the existing 1-sample/s diagnostics cadence) and only
    calls a target genuinely "unstable" once `CONSECUTIVE_UNSTABLE_WINDOWS_REQUIRED = 2`
    windows in a row look bad — hysteresis specifically added after an early version
    falsely flagged ordinary startup jitter and dropped straight from 165→30 within a
    couple of seconds. **Currently measure-and-log only**: `streaming/controller.py`'s
    `AUTO_FPS_RESTART_ENABLED` is deliberately `False` — a decision made while chasing
    the crash described below (to rule out the FPS controller as the cause without an
    always-on auto-restart complicating the picture) and not yet turned back on, so
    Automatic FPS currently reports what it *would* do in the logs/Diagnostics rather
    than actually restarting the stream. Re-enabling it is a one-line flag flip once
    it's been exercised more on real hardware.
  - **Performance/Quality slider moved into the Device panel**: the Phase 9 fixed
    bottom-toolbar-with-its-own-Refresh-button design (see the superseded bullets above)
    is gone — there is now exactly one copy of the slider, living in the Device panel
    under Microphone, which applies live the moment you release it
    (`performance_slider_committed` → `CastingController.commit_slider_value()`,
    restarting an already-active session) rather than needing a separate manual
    Refresh click.
  - **Real Camera Live Preview and Mic Input Level meter**: the Device panel's Camera
    and Microphone sections got genuine, non-simulated monitoring — a live decoded-frame
    preview for Camera (`camera_controller.py`'s `_on_frame_available()`, never a
    placeholder image) and a real RMS input-level meter for Mic, both showing an honest
    Active/Connecting/Disabled/Disconnected/No Signal status derived from whether frames
    or audio are actually arriving, not just whether the feature is toggled on.
  - **Crash-safety and session-lifecycle hardening**: real-device testing surfaced a
    hard native crash ("QThread: Destroyed while thread is still running", not a
    catchable Python exception) triggered by toggling Control, traced to
    `CastingSession`/`CameraSession`/`MicSession` each owning an un-parented worker
    `QThread` that could still be mid-teardown when the wrapper object was
    `deleteLater()`'d on an immediate 0ms timer. Fixed by tying `deleteLater()` to each
    session's own `stopped` signal instead (which only fires once the worker thread has
    genuinely finished), across all three controllers. Alongside that: duplicate-session
    guards (`_start_casting()`/`_start_camera()`/`_start_mic()` now safely restart rather
    than silently running two sessions at once), idempotent `stop()` on every client, and
    a new `utils/crash_state.py` + top-level `sys.excepthook`/`threading.excepthook` pair
    in `app/application.py` that logs full crash context (current streaming/FPS/device
    state) instead of the app just disappearing — collecting diagnostics only, never
    suppressing or auto-restarting past a genuine bug.
  - **Camera Live Preview relocated, enlarged, and orientation-corrected**: the preview
    moved from the Device panel to the Status panel's right-side bar (directly under
    Screenshot), grew substantially (no fixed height cap any more — `Expanding` size
    policy on both axes with only a 220px floor, so it fills whatever space the dock
    actually has and scales as it's resized, verified with a real offscreen-Qt layout
    resize test), and gained rotation correction: `camera/camera_orientation.py` combines
    the camera's fixed `CameraCharacteristics.SENSOR_ORIENTATION` (queried once via `adb
    shell dumpsys media.camera`) with the phone's *live* display rotation (polled every
    2s via `adb shell dumpsys input`/`dumpsys window displays`, since a camera-mirroring
    session runs with `control=false` and has no live wire-protocol channel to push a
    rotation-changed event) using the standard Camera2 orientation formula, so the
    preview keeps adapting as the phone is physically turned without restarting the
    camera session. **Not verified against real hardware** — no Android device was
    available for this specific change, and OEM `dumpsys` output isn't guaranteed
    identical across Android versions; every parsing step degrades to "apply no
    rotation" (never a guessed fixed value) if a device's real output doesn't match, and
    the raw `dumpsys` text is logged on a parse failure to make fixing it against real
    data straightforward. A small always-visible notice under the preview reads
    "Camera preview may affect performance when used with screen casting."
  - **Removed the Device panel's top-left "⟳ Refresh" button**: it re-ran ADB device
    detection on demand, but that already happens automatically on `DeviceManager`'s own
    poll timer, making the manual button mostly a redundant no-op in practice — removed
    along with its click handler; `DeviceManager.refresh_now()` itself (and automatic
    polling) is untouched.
  - **Windows Installer (.msi) packaging, first pass**: `packaging/build_msi.py` wrapped
    the PyInstaller `AndroidLink.exe` in a real `.msi` using Python's stdlib `msilib` (no
    external toolset needed) — per-machine install to Program Files, Start Menu/Desktop
    shortcuts, a standard Add/Remove Programs entry. Building it for real (not just
    assuming the table shapes were right) caught two genuine authoring bugs via an actual
    `msiexec /a` administrative-extraction test: a registry-keyed shortcut Component
    needs the `msidbComponentAttributesRegistryKeyPath` flag or Windows Installer
    misreads the KeyPath as a File-table reference, and the cabinet's internal logical
    filename has to match the File table's primary key, not the display filename.
    **Superseded in the professional-installer pass below** — kept here as a record of a
    real, load-bearing MSI-authoring bug hunt in case `msilib` is ever revisited.
  - **Professional wizard-driven Windows Installer, rebuilt on WiX**: replaced the
    `msilib`-based installer above with a proper multi-page wizard authored in WiX
    Toolset v3 (`packaging/androidlink.wxs`), matching a much more detailed spec: an
    Installer Information page, an Important Notice page (USB/ADB, permissions,
    resource-usage warnings), a Features page (with a Camera Performance Notice), an
    Installation Requirements page, an install-location picker with an optional Desktop
    shortcut checkbox, and a Ready to Install confirmation — all before anything is
    written to disk. `packaging/build_msi.py` now downloads WiX's standalone binaries
    automatically (no install, nothing added to PATH), and also builds a small
    `Uninstall.exe` (`packaging/uninstall_stub.py`) dropped into the install folder,
    which looks up its own installation's real `UninstallString` from the Windows
    registry at runtime and re-runs it — so uninstalling still goes through the genuine
    MSI uninstall sequence rather than reimplementing file/registry cleanup by hand. Adds
    `<MajorUpgrade>` support (a real WiX one-liner), fixing the previous version's "no
    upgrade in place" limitation. The custom dialog wiring (which button goes to which
    page, how the standard Progress/Exit dialogs get triggered automatically, how the
    disk-space-aware Install button behaves) was authored by fetching and reading
    WixUIExtension's own real source (wixtoolset/wix3 on GitHub) rather than reconstructed
    from memory, specifically because a subtly wrong interactive wizard flow is very hard
    to catch without a human clicking through it. Two more real bugs surfaced building
    this for real: custom dialog IDs colliding with dialogs WixUIExtension already ships
    under the same names (`FeaturesDlg`/`InstallDirDlg`/`VerifyReadyDlg`/`ExitDialog`,
    renamed to `AL`-prefixed IDs), and `ProgramFilesFolder` not actually resolving to the
    native 64-bit Program Files under `-arch x64` the way a first pass assumed (fixed by
    referencing `ProgramFiles64Folder` explicitly, caught via WiX's own ICE80 validation).
    Verified via a real `msiexec /a` administrative extraction (both `AndroidLink.exe`
    and `Uninstall.exe` placed correctly) and a real `msiexec /i` quiet-install attempt
    that clears LaunchConditions/CostFinalize/InstallValidate cleanly (the only remaining
    failure is Windows correctly refusing a per-machine install from this automated,
    non-elevated environment) — the interactive wizard's page-by-page click-through has
    **not** been verified by an actual human yet. See
    [Building the Windows Installer](#building-the-windows-installer-msi) below.
  - **Fixed a real button-overlap bug on the Ready to Install page**: reported as "the
    UAC shield icon overlaps the Install text." The actual cause wasn't shield rendering
    at all — the Install button is intentionally 80 dialog units wide (24 wider than a
    normal 56-unit button, to leave room for the `ElevationShield="yes"` UAC glyph
    WixUIExtension itself draws to the left of the label) and sits 24 units further left
    than a normal action button to stay right-aligned, but this page's Back button was
    still authored at the generic X=180 every *other* page uses instead of the X=156
    that specific width/position combination requires — so Back's own button face
    overlapped Install's left 24 units, which is what actually looked like "the icon
    covering the text." Confirmed and fixed against WixUIExtension's own real
    VerifyReadyDlg.wxs source (same one already cited above), which uses this exact
    X=156/212 pairing for the same reason. On DPI scaling: every control in
    `androidlink.wxs` is already authored in MSI dialog units (not pixels), which is the
    actual mechanism that makes Windows Installer dialogs render correctly across
    100–200% scaling — there was no pixel-based sizing to fix. This environment can't
    drive a live interactive dialog at a specific Windows display-scaling percentage to
    screenshot-verify each one directly.