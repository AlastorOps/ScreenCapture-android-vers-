# AndroidLink

Android-to-Windows USB companion and control center. Connects an Android phone to a
Windows PC over USB Type-C for screen casting, remote control, audio, camera/mic
virtual devices, and recording — no Wi-Fi, cloud, or internet required.

This project is being built in phases (see `prompt.md` for the full spec).
Implemented so far:

- **Phase 1: project foundation** — application shell, theming, settings persistence, logging.
- **Phase 2: USB/ADB device detection** — live device list, connect/disconnect.
- **Phase 3: screen casting** — drives a vendored [scrcpy](https://github.com/Genymobile/scrcpy)
  server over ADB and decodes/renders its video stream. The wire protocol and decoder
  are unit-tested against a real H.264 stream, but the end-to-end adb push/reverse
  tunnel/socket path has not been exercised against real hardware (no Android device
  was available during development) — try it with a real device and see
  `androidlink/streaming/transport.py`'s module docstring for details. **Fullscreen mode**
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
  turned off, and that choice persists across restarts like the rest of Phase 9's settings
  persistence.
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
  companion app exists yet to query Android's AudioManager directly, so this is surfaced
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
  to record or screenshot otherwise. Files save to `Videos\AndroidLink` and
  `Pictures\AndroidLink` by default; a Settings UI to change that location isn't built yet
  (deferred to Phase 9's full Settings page). When Android audio is enabled, its decoded
  PCM is muxed into the recording too (AAC), via the same audio already being played back
  — no separate capture path, added to the queue alongside video frames and encoded on the
  same background thread. The encoder-selection/fallback logic and the full
  record-then-decode-back round trip (video and video+audio) are tested against real
  written MP4 files, not mocked.

- **Phase 9 (in progress): polish** — two slices done so far:
  - **Real Diagnostics** (prompt.md sections 20/33/34: never fabricate a performance
    number). The Status panel's Stream FPS, Render FPS, Dropped Frames, Decode Latency,
    Bitrate, Resolution, and Codec readouts are all genuinely measured — decoded-frame
    counting and byte counting in `streaming/transport.py`, a real paint-event counter in
    `streaming/renderer.py`, and process CPU/RAM via `psutil` in `utils/system_stats.py`
    (normalized to 0-100% across all cores). "Dropped frames" comes from a real counter
    added to `LatestValueBox` that tracks values overwritten before ever being read, not a
    guess. GPU usage is left as an honest "—" (with a tooltip explaining why) rather than
    faked — reliable cross-vendor GPU utilization on Windows needs Performance Data Helper
    counter queries, not implemented yet.
  - **Settings persistence** (prompt.md section 29): performance/quality slider, Android
    audio volume/mute, camera selection/FPS, and microphone selection/volume/mute now
    survive a restart, loaded into their panel controls on launch and saved on change
    (slider/volume changes save once on release, not per drag tick, to avoid hammering
    disk). Building this surfaced and fixed two real bugs: populating the camera/FPS
    dropdowns was firing the same "selection changed" signals a real user action would,
    which silently overwrote a just-loaded persisted camera selection before it was ever
    applied — dropdown population is now signal-blocked so only genuine user choices get
    persisted. Recording's save location and "selected device"/reconnect behavior are
    intentionally not persisted yet — the former has no Settings UI to change it yet, and
    the latter interacts with this app's "never auto-connect" principle closely enough
    that it deserves its own design pass; both are left for later rather than half-wired.
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
  - Still open for Phase 9: customizable/savable panel layout, the full multi-section
    Settings page (Streaming/Camera/Recording/Device/Diagnostics), an error message
    catalog, and packaging/troubleshooting docs.

## Development setup

```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## Running

```
python -m androidlink.app.main
```

## Testing

```
pytest
```

## Building a Windows executable

```
pip install -e ".[build]"
pyinstaller packaging/androidlink.spec --distpath dist --workpath build --noconfirm
```

Produces `dist/AndroidLink.exe`, a standalone onefile executable (no Python install
required to run it). The spec bundles the theme's QSS files and the vendored
scrcpy-server jar; later phases that add more vendored binaries (virtual camera/mic
drivers) will extend `packaging/androidlink.spec`'s `datas`/`binaries` accordingly.
