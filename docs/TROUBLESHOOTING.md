# AndroidLink Troubleshooting Guide

Most in-app error messages already explain what's wrong and what to do about it (see
`androidlink/utils/errors.py`) — this guide goes into more depth on the scenarios
listed there, plus known hardware limitations that aren't really "bugs" so much as
platform constraints. If you haven't done first-time setup yet, start with
[SETUP.md](SETUP.md) instead.

The in-app **Help → Setup Guide** (also shown automatically on first launch) re-runs
live checks for most of the environment-level issues below (ADB, USB debugging, virtual
device backends) against your actual machine — it's the fastest way to narrow down
which of these applies.

## Device / USB / ADB

### "ADB was not found"

`adb` isn't on your PATH and wasn't found in a common SDK install location. See
[SETUP.md § Installing ADB](SETUP.md#2-installing-adb). After installing/fixing PATH,
either restart AndroidLink or click **Recheck** in the Setup Guide — it re-probes
rather than caching the first failed lookup.

### Device doesn't appear in the Device panel at all

* Confirm the cable is a **data** cable, not charge-only (some cheap or charging-brick
  cables have no data lines at all).
* Check the phone's USB notification is set to a data mode (File Transfer/MTP), not
  "Charging only."
* Try a different USB port — front-panel/hub ports are more likely to have power or
  signal issues than a rear I/O port.
* Run `adb devices` in a terminal directly; if it also shows nothing, the problem is at
  the ADB/USB level, not AndroidLink.

### "USB debugging authorization is required" / device shows as unauthorized

Unlock the phone — there should be an **"Allow USB debugging?"** dialog waiting. If you
don't see it, toggle USB debugging off and back on in Developer Options, or revoke USB
debugging authorizations (Developer Options → "Revoke USB debugging authorizations")
and reconnect to get a fresh prompt.

### Device shows as offline

The device is visible to ADB but not responding. Unplug and reconnect the cable; if it
persists, run `adb kill-server` in a terminal and let AndroidLink's next poll restart
it, or restart the phone.

### "The connection to the device was lost" mid-session

The scrcpy-server socket disconnected unexpectedly — usually a flaky USB connection
(cable, port, or a hub in between). Reconnect the cable and start the feature again. If
it happens repeatedly on the same cable/port, try a different one.

A specific variant that's fixed as of this build: if `adb devices` starts returning an
empty list while the device is still physically connected (confirm with `adb devices`
in a terminal — if it's empty there too, this is it, not a AndroidLink-specific
display bug), the local adb server itself has become unresponsive rather than the USB
link actually dropping — `adb kill-server` followed by AndroidLink's next poll (or a
manual `adb start-server`) recovers it immediately. `device/manager.py`'s device-info
polling used to be able to re-spawn an `adb shell getprop` call for the same device on
every single 1.5-second poll tick indefinitely (if the previous one never completed),
which under sustained real use could destabilize the adb server enough to drop any
active `adb reverse` tunnels — exactly the scrcpy-server sessions Screen Cast/Camera/Mic
depend on. If you still see this after updating, it's worth filing with `Help → Open
Logs`' output attached.

### USB bandwidth / instability (stutter, dropped frames, disconnects under load)

Running Screen Cast + Camera + Mic simultaneously, especially at the Quality end of the
Performance/Quality slider, pushes real USB bandwidth and CPU load on both ends. If you
see stutter, dropped frames (see the Status panel's real Dropped Frames counter), or
disconnects:

* Move the Performance/Quality slider toward Performance.
* Disable features you're not actively using (every feature is independently
  toggleable — prompt.md section 13).
* Use a shorter, higher-quality cable, and a direct PC port rather than a hub.
* USB 2.0 ports/cables have materially less bandwidth than USB 3.x; if your phone and
  cable support it, make sure you're on a USB 3.x port.

## Codecs / decoding

### "This PC cannot decode" a video or audio codec

The device's encoder picked a codec (this can happen with less common vp8/vp9 video, or
uncommon audio codecs) that this PC's FFmpeg/PyAV build doesn't have a decoder for. This
is a decoder capability limit on the PC side, not something AndroidLink can silently
work around — for video, casting can't continue for that session; for audio, the
session continues, just without sound. This is rare in practice since scrcpy's default
codec selection strongly prefers H.264, which is close to universally hardware-decodable.

### "The video/audio decoder (PyAV/FFmpeg) is not installed"

Only relevant when running from source without the full dependency set installed (the
packaged `AndroidLink.exe` always bundles PyAV). Run `pip install -e ".[dev]"` again, or
directly `pip install av`.

## Camera / Microphone

### Camera or Mic permission denied on the device

Android will prompt for Camera/Microphone permission the first time you enable the
corresponding feature (scrcpy-server requests it as part of starting that
mirroring session). If you previously denied it, re-enable the permission manually:
phone **Settings → Apps → (the permission is granted to the shell/system context scrcpy
runs under, not a regular app you'll find in this list on most ROMs)** — in practice,
the more reliable fix is toggling the feature off and on again in AndroidLink, which
re-triggers the request, or checking Settings → Privacy → Permission manager on the
phone for anything related to "shell" or "scrcpy."

### "No Windows virtual camera backend was found" / "No virtual audio cable driver was found"

Neither pyvirtualcam (Camera) nor a virtual-audio-cable driver (Mic) is bundled or
auto-installed — see [SETUP.md § 7](SETUP.md#7-virtual-webcam-setup-phone-camera--windows-apps)
and [§ 8](SETUP.md#8-virtual-microphone-setup-phone-mic--windows-apps) for what to
install. This is a deliberate design choice (prompt.md section 25: never silently
install drivers), not a bug.

### The virtual camera/microphone shows up in Windows but other apps don't see any
### signal, or the app itself doesn't fully work

Android Audio and Mic have both since been verified end-to-end against a real device
and a real VB-Audio Virtual Cable install; Camera's virtual-webcam output has not been
(see [ARCHITECTURE.md § Hardware-verification
status](ARCHITECTURE.md#hardware-verification-status)). If you hit an integration issue
a real device surfaces that unit tests can't catch (device-specific quirks, driver
version differences, etc.), check **Help → Open Logs** for the actual failure and
consider filing it with the log attached.

### No sound after installing a virtual-audio-cable driver

Installing VB-Audio Virtual Cable, VoiceMeeter, or a similar driver (usually to set up
the Mic feature — see [SETUP.md § 8](SETUP.md#8-virtual-microphone-setup-phone-mic--windows-apps))
can silently change *Windows'* system-wide default playback device to the cable itself.
Since Android Audio's "System Default" output setting plays through whatever Windows
currently calls default, this makes it decode and play successfully into the cable
instead of your speakers — you hear nothing, with no error anywhere, because nothing is
actually broken; the audio is just going somewhere nobody's listening.

Confirm this is what's happening: Windows Settings → System → Sound → Output — if it
shows something like "CABLE Input" instead of your speakers/headphones, that's it.
AndroidLink's Settings → Audio tab detects this automatically and shows a warning
naming the actual device in use, with two fixes:

* **Settings → Audio → Output Device**: pick your real speakers/headphones explicitly.
  This overrides the Windows default for AndroidLink only.
* **Settings → Audio → Also Output To**: keep "System Default" (or your real device) as
  the primary output, and additionally select the virtual-cable device here — Android's
  audio then plays to *both* at once, so you hear it **and** another app (Discord, OBS,
  etc.) can still pick it up from the cable, rather than an either/or choice.
* Alternatively, change the Windows default back in Settings → Sound → Output, which
  fixes it system-wide for every app, not just AndroidLink.

## Recording

### "There's no active cast session to record" / screenshot button does nothing

Recording and screenshots both require Screen Cast to be active first (there's nothing
to record otherwise) — enable Cast from the Device panel, then Record/Screenshot from
the Status panel.

### "Could not start recording" / recording fails immediately

Usually a permissions or disk-space problem at the save location (Settings → Recording
→ Save Location). Check the folder is writable and there's free disk space; the error
message includes the underlying exception detail.

## Diagnostics

* **Help → Open Logs** opens the folder containing `androidlink.log` (rotated, 5 files ×
  5MB). Settings → Diagnostics lets you raise the logging level to DEBUG for more detail
  while reproducing an issue, or toggle Debug Mode as a one-click equivalent.
* The Status panel's numbers (FPS, dropped frames, decode latency, bitrate, CPU/RAM) are
  all genuinely measured, never fabricated placeholders — if something reads "—" it
  means that metric genuinely isn't being produced right now (e.g. no active cast
  session), not that it's broken.

## Known hardware limitations

* **GPU usage isn't shown** in the Status panel (reads "—" with an explanatory
  tooltip) — reliable cross-vendor GPU utilization on Windows needs Performance Data
  Helper counter queries, which aren't implemented.
* **Camera resolution selection isn't implemented** — the device's own default
  resolution is always used; only FPS is user-selectable per camera.
* **No per-device query of microphone capabilities** — the Mic "Input" source list is
  the fixed set scrcpy's protocol supports (mic, mic-unprocessed, mic-voice-*,
  mic-camcorder), not detected per-device, since there's no companion app to ask
  Android's AudioManager directly.
* **No automatic reconnect** to the last device on launch, by design — AndroidLink never
  takes control of a device without an explicit Connect click (prompt.md section 3),
  even across restarts.
* **Latency and dropped frames are never zero by design claim** — the app reports real
  measured numbers, and some non-zero latency/occasional drops are inherent to any
  USB + software-decode video pipeline, not a defect to "fix to zero."
