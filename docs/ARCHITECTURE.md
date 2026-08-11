# AndroidLink Architecture

This document explains how AndroidLink is put together: the high-level design
decisions, the package structure, the runtime data flow, and the threading model. For
installation steps see [SETUP.md](SETUP.md); for "why is this failing" see
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## No companion Android app

prompt.md's spec allows for an optional Android companion app "if it provides better
[...] camera streaming / microphone capture / audio capture / video transport /
capability detection / performance / reliability" than driving everything through ADB
directly.

AndroidLink does not have one. The architecture decision made early in this project was
to drive the vendored [scrcpy](https://github.com/Genymobile/scrcpy) server directly
over ADB instead (`androidlink/vendor/scrcpy/scrcpy-server-v4.1.jar`, pushed to the
device and launched via `adb shell app_process` — see `streaming/transport.py`,
`camera/camera_session.py`, `audio/mic_session.py`). scrcpy-server already implements
everything the spec's companion app would need to provide — screen capture via
MediaProjection, camera capture via Camera2, microphone capture via AudioRecord,
MediaCodec-based hardware encoding, and a well-defined wire protocol — without
requiring the user to separately install and grant permissions to a second app. Where
this document or the in-app UI (e.g. the Setup Guide's "Companion app" row, or
Settings → Device → Companion App) says "not applicable," this is why: there is nothing
to build, install, or version-match, by design, not an unfinished feature.

The trade-off is that anything scrcpy-server's protocol doesn't expose (e.g. querying
Android's `AudioManager` for per-device microphone capabilities — see
`streaming/protocol.py`'s `MIC_AUDIO_SOURCES` docstring) isn't available either, short
of building that companion app later. If a feature ever needs it badly enough, adding
one remains possible: `device/manager.py` already isolates all device communication
behind ADB, and adding a companion app would mean introducing a new transport (e.g. a
socket over `adb forward`) alongside it, not replacing the existing scrcpy-based
sessions.

## Package structure

```
androidlink/
├── app/          startup sequence, QApplication subclass, uncaught-exception handling
├── ui/           windows, panels, custom widgets, theme QSS, dock-layout persistence
├── device/       ADB discovery, device model, connect/disconnect state
├── streaming/    scrcpy wire protocol, video transport, decoder, renderer, performance
├── audio/        Android audio + microphone: decode, PC playback, virtual-cable output
├── camera/       camera capability listing, camera-mirroring session, virtual webcam
├── input/        mouse/keyboard → Android touch/key event encoding, coordinate mapping
├── recording/    PC-side MP4 recording (background encode thread) and screenshots
├── setup/        first-launch guided setup (live checks + guidance, no silent fixes)
├── settings/     Pydantic settings model + JSON persistence
└── utils/        platform paths, logging, the error message catalog
```

Each of `streaming/`, `camera/`, and `audio/`'s mic path owns an **independent**
scrcpy-server session (its own ADB reverse tunnel, its own socket state machine) rather
than sharing one — Cast+Control+Audio share a single session (video/control/audio all
multiplexed over one scrcpy-server launch, since scrcpy's own protocol supports that
directly), but Camera and Mic are architecturally separate mirroring sessions, matching
how scrcpy itself treats `video_source=camera` and mic `audio_source` values as
distinct from normal screen mirroring. See `device_panel.py`'s module docstring for the
practical consequence: Control and Audio require Cast to be on (they share its
session); Camera and Mic don't (prompt.md section 13: every major feature is
independently toggleable except where the underlying protocol genuinely requires a
dependency, and that dependency is explained in the UI, not hidden).

## Runtime data flow (screen casting)

```
Android device
   │  MediaProjection capture → MediaCodec hardware encode (H.264/HEVC/AV1)
   ▼
scrcpy-server (pushed + launched via ADB, running on-device)
   │  Annex-B video over a TCP socket, tunneled through `adb reverse`
   ▼
ScrcpyVideoClient (streaming/transport.py, worker QThread)
   │  parses scrcpy's packet framing (streaming/protocol.py)
   │  PyAV/FFmpeg decode → RGB24 ndarray (streaming/decoder.py)
   │  written into a LatestValueBox (utils/latest_value_box.py)
   ▼
VideoRenderWidget (streaming/renderer.py, GUI thread)
   │  paints the latest available frame; a real "dropped frames" counter
   │  tracks frames overwritten in the box before ever being read
   ▼
Also fanned out (already-decoded, no extra capture path) to:
   ├── RecordingController → VideoRecorder (background encode thread → MP4)
   └── screenshot capture (single frame → PNG)
```

`LatestValueBox` is the key latency-control primitive (prompt.md section 34: "prioritize
fresh frames over displaying old frames"): it holds exactly one pending frame, and a new
`put()` overwrites whatever hadn't been consumed yet rather than queuing, so the
renderer never falls behind by draining a backlog — it always paints the most recent
frame available, and every overwrite-before-read is counted as a real dropped frame
rather than silently discarded.

Mouse/keyboard input takes the reverse path: Qt input events on `VideoRenderWidget` →
coordinate-mapped against the render widget's actual size (`input/touch_mapper.py`, so
resizing/fullscreen/rotation never desyncs coordinates) → encoded into scrcpy's control
message wire format (`streaming/protocol.py`) → written to the session's control socket.

## Threading model

Nothing that can block — ADB process calls, socket I/O, video/audio decoding — runs on
the GUI thread (prompt.md section 22). Each scrcpy-server session's client class
(`ScrcpyVideoClient`, `CameraClient`, `MicClient`) is moved to its own worker `QThread`
via `moveToThread()`; the GUI-thread-facing `*Session` wrapper classes
(`CastingSession`, `CameraSession`, `MicSession`) only exchange Qt signals with them —
Qt automatically marshals cross-thread signal delivery safely, so no manual locking is
needed in the call sites that use these wrappers.

Recording runs on a third kind of concurrency unit: a plain `threading.Thread` (not a
`QThread`) reading from a bounded `queue.Queue`, since the encode loop is a blocking
`queue.get()` with no need for a Qt event loop of its own — see `recording/recorder.py`'s
module docstring for why mixing that blocking read with a Qt event loop would be the
wrong tool here.

`device/manager.py`'s device polling (`adb devices -l` every 1.5s) runs via async
`QProcess`, never a blocking subprocess call, so it can't stall the GUI even though it
lives on the GUI thread.

## Settings and layout persistence

`settings/manager.py` loads/saves a single `AppSettings` Pydantic model (`settings/models.py`)
as JSON in the platform config directory. Every persisted preference documented in
prompt.md section 29 has a concrete field; UI controllers load their initial value from
it in `__init__` and save on change (debounced to commit-only for continuous controls
like sliders — see e.g. `device_panel.py`'s volume sliders, or the Settings dialog's
equivalents).

The dockable panel layout (prompt.md section 16) piggybacks on the same mechanism:
`ui/windows/main_window.py` wraps each panel in a `QDockWidget`, and
`QMainWindow.saveState()`/`restoreState()` — Qt's own built-in layout serialization —
is base64-encoded into `settings.general.layout_state`. This is why "Restore Default
Layout" simply clears that field and reruns the default `addDockWidget`/
`splitDockWidget` arrangement, rather than needing any bespoke layout-diffing logic.

## Error handling

`utils/errors.py` is a single catalog of `AppError` entries (message + actionable
guidance), referenced by the modules that can actually raise/emit each condition
instead of scattering ad-hoc string literals across `device/manager.py`,
`streaming/transport.py`, `camera/*`, `audio/*`, and `recording/*`. It deliberately
mirrors `setup/checks.py`'s `SetupCheck` shape (short detail + separate guidance) but
serves a different purpose: `setup/checks.py` answers "is the environment ready?"
proactively before anything has gone wrong, while `utils/errors.py` answers "why did
this just fail?" reactively once something has. See prompt.md section 21 for the full
list of scenarios it covers.

## Hardware-verification status

The video/audio/camera/mic wire-protocol parsing, decoders, and the recorder's
encode/mux path are all verified against **real** data — real H.264/Opus fixtures
demuxed from actual encoded files, a real synthetic byte stream built to match exactly
what scrcpy-server sends, real PyAV encode-then-decode round trips for recordings (see
the `tests/test_*_client_state_machine.py` files and `tests/test_recorder.py`). What
has **not** been exercised end-to-end against real hardware during this project's
development is the live path beyond that: an actual `adb push` / `adb reverse` /
`app_process` launch / socket handshake sequence against a physical Android device, and
an actual OBS Virtual Camera / virtual-audio-cable driver receiving real output — no
Android device or those Windows drivers were available in the development environment.
Every module that carries this caveat says so explicitly in its own docstring (e.g.
`streaming/transport.py`, `camera/camera_session.py`, `audio/mic_session.py`) rather
than claiming untested behavior works. If you hit an integration issue that only shows
up against real hardware, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md) and consider
filing it with `Help → Open Logs`' output attached.
