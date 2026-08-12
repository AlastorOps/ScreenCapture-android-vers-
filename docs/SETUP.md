# AndroidLink Setup Guide

This guide covers getting AndroidLink running end-to-end: Android-side setup, PC-side
installation, and the optional Windows virtual camera/microphone backends. For "it's not
working" scenarios once everything is installed, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
For how the pieces fit together, see [ARCHITECTURE.md](ARCHITECTURE.md).

## 1. Requirements

* Windows 10 or 11, 64-bit.
* An Android phone running Android 10 (API 29) or newer.
* A USB Type-C (or micro-USB, depending on the phone) data cable — not a charge-only
  cable. Prefer a short, good-quality cable directly into a PC port rather than a hub;
  see [TROUBLESHOOTING.md](TROUBLESHOOTING.md#usb-bandwidth-instability) if you see
  stutter or disconnects.
* [Android Platform Tools](https://developer.android.com/tools/releases/platform-tools)
  (`adb`), on your PATH. AndroidLink drives the phone entirely over ADB — there is no
  separate Android companion app to install (see
  [ARCHITECTURE.md](ARCHITECTURE.md#no-companion-android-app) for why).
* Optional, only if you want the corresponding feature:
  * [OBS Studio](https://obsproject.com/) (bundles OBS Virtual Camera) or
    [Unity Capture](https://github.com/schellingb/UnityCapture) — for the phone camera
    as a Windows webcam.
  * [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) or
    [VoiceMeeter](https://vb-audio.com/Voicemeeter/) — for the phone microphone as a
    Windows input device.

No internet connection is required to run AndroidLink; everything happens locally over
USB (see prompt.md section 26). No telemetry is collected.

## 2. Installing ADB

1. Download **Platform-Tools for Windows** from the link above and unzip it somewhere
   permanent (e.g. `C:\platform-tools`).
2. Add that folder to your `PATH` (Windows Settings → search "Environment Variables" →
   edit the `Path` user variable → add the folder).
3. Open a new terminal and confirm it works:

   ```
   adb version
   ```

AndroidLink also checks a couple of common SDK install locations automatically (see
`device/adb.py`'s `find_adb_executable()`), so if you already have Android Studio
installed, `adb` may already be found without a PATH change.

## 3. Android-side setup (USB debugging)

1. On the phone: **Settings → About phone**, tap **Build number** 7 times to unlock
   **Developer options**.
2. **Settings → System → Developer options**, enable **USB debugging**.
3. Plug the phone into the PC with a data-capable USB cable.
4. Select **File Transfer (MTP)** (or any data mode) in the USB notification on the
   phone, not "Charging only" — some phones default to charge-only, which prevents ADB
   from seeing the device at all.
5. A dialog appears on the phone: **"Allow USB debugging?"** — check "Always allow from
   this computer" and tap **Allow**. This must be accepted on the phone itself;
   AndroidLink cannot do this for you and never attempts to bypass it (prompt.md
   section 25).

Repeat step 5 (accepting the prompt) after unplugging/reconnecting only if the phone
revokes authorization, which some manufacturers' ROMs do more aggressively than stock
Android.

## 4. Installing AndroidLink

### Option A — Windows Installer (.msi)

Download or build `AndroidLink.msi` (see
[Building the Windows Installer](#6b-building-the-windows-installer-msi) if you're
building it yourself) and run it. It's a short wizard — an information page explaining
what AndroidLink is, an important-notice page, a features page, an installation-
requirements page, an install-location page (with an optional Desktop shortcut
checkbox), and a confirmation page — before anything is written to disk. It installs to
`Program Files\AndroidLink`, adds Start Menu and Desktop shortcuts, registers a normal
Add/Remove Programs entry, and drops a real `Uninstall.exe` into the install folder as a
second way to uninstall later. Because it installs per-machine, Windows will prompt for
administrator permission (UAC) — that's expected, not a sign anything is wrong. Windows
SmartScreen may also warn about an unsigned installer from an unknown publisher the
first time; this is expected for an unsigned indie build.

### Option B — prebuilt executable (no installer)

Download `AndroidLink.exe` (see [Building the Windows executable](#6-building-the-windows-executable)
if you're building it yourself) and run it directly from wherever you put it — no
install step, no Python required, nothing added to Start Menu/Add-Remove-Programs.
Same SmartScreen note as above applies.

### Option C — running from source (development)

```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

Requires Python 3.11+.

## 5. Running in development

```
python -m androidlink.app.main
```

Run the test suite with:

```
pytest
```

## 6. Building the Windows executable

```
pip install -e ".[build]"
pyinstaller packaging/androidlink.spec --distpath dist --workpath build --noconfirm
```

This produces `dist/AndroidLink.exe`, a standalone onefile executable. The spec bundles
the theme's QSS files and the vendored scrcpy-server jar (`packaging/androidlink.spec`'s
`datas`); it does not bundle `adb.exe`, OBS, or a virtual-audio-cable driver — those
remain separate installs per section 1, so their licensing stays with their own
projects and AndroidLink never silently installs a system driver on your behalf
(prompt.md section 25).

There is no separate "build the Android companion" step, because there is no companion
Android app in this project (see
[ARCHITECTURE.md](ARCHITECTURE.md#no-companion-android-app)).

## 6b. Building the Windows Installer (.msi)

Build the exe first (section 6 above), then:

```
python packaging/build_msi.py
```

This produces `dist/AndroidLink.msi` by wrapping the already-built `dist/AndroidLink.exe`
— it doesn't rebuild the app itself, so re-run section 6 first if you've changed any
code. Built with the [WiX Toolset](https://wixtoolset.org/) v3; `build_msi.py` downloads
WiX's standalone binaries automatically into `packaging/.wix-tools/` on first run (a
one-time ~40MB download, no installation, nothing added to PATH or the registry). It
also builds a small `Uninstall.exe` from `packaging/uninstall_stub.py`, installed
alongside the app.

The resulting installer is a short wizard (see section 4, Option A, for what each page
covers) that does a per-machine install to `Program Files\AndroidLink` (UAC prompt
expected), adds Start Menu and Desktop shortcuts, registers a standard Add/Remove
Programs entry, and installs a real `Uninstall.exe` into the install folder. Installing a
newer build over an older one is handled automatically (WiX's `<MajorUpgrade>` removes
the old version as part of installing the new one). See `packaging/androidlink.wxs` and
`packaging/build_msi.py`'s module docstrings for more detail.

## 7. Virtual webcam setup (phone camera → Windows apps)

The Camera feature (prompt.md section 11) exposes the phone's camera as a real Windows
video capture device other applications can select, via
[pyvirtualcam](https://github.com/letmaik/pyvirtualcam). pyvirtualcam drives an
*existing* virtual-camera backend — it doesn't install one itself, so you need one of:

* **OBS Studio** — installing OBS also installs "OBS Virtual Camera"; you don't need to
  run OBS itself, just have it installed.
* **[Unity Capture](https://github.com/schellingb/UnityCapture)** — a lighter-weight
  alternative if you don't want OBS.

Once installed, enable **Camera** from AndroidLink's Device panel (select which camera
first if the phone has more than one) — Discord, Zoom, Teams, OBS, and Windows Camera
can then select the resulting device the same as any other webcam. If AndroidLink
reports no virtual camera backend was found, re-check that one of the above is actually
installed (the Setup Guide's checklist, Help → Setup Guide, verifies this live).

## 8. Virtual microphone setup (phone mic → Windows apps)

Windows has no first-party "virtual microphone" API the way it does for webcams, so the
Microphone feature (prompt.md section 12) uses the standard workaround: a third-party
virtual-audio-cable driver that exposes a loopback pair of devices — audio AndroidLink
writes to the cable's playback endpoint reappears on its matching recording endpoint,
which other apps see as a microphone. Install one of:

* **[VB-Audio Virtual Cable](https://vb-audio.com/Cable/)** (free, simplest) — after
  installing, Windows gains a "CABLE Input" playback device and "CABLE Output" recording
  device.
* **[VoiceMeeter](https://vb-audio.com/Voicemeeter/)** (free, more routing options) if
  you want more control over mixing multiple audio sources.

Once installed, enable **Mic** from the Device panel. Other applications (Discord, OBS,
Zoom, Teams) should then list "CABLE Output" (or VoiceMeeter's equivalent input) as a
selectable microphone.

> **Note:** installing a virtual-audio-cable driver can silently change *Windows'*
> system-wide default playback device to the cable itself, which makes the separate
> Android Audio feature (phone system audio → PC speakers) go silent even though it's
> working correctly — see
> [TROUBLESHOOTING.md](TROUBLESHOOTING.md#no-sound-after-installing-a-virtual-audio-cable-driver).
> Settings → Audio's **Output Device** picker lets you pin Android Audio to your real
> speakers regardless of the Windows default, and **Also Output To** lets you send it to
> *both* your speakers and the cable at once if you want another app to pick it up too.

## 9. Next steps

* Something not working? See [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
* Curious how the pieces fit together? See [ARCHITECTURE.md](ARCHITECTURE.md).
* The in-app **Help → Setup Guide** runs the same checks described here live against
  your actual machine and device, and can be reopened any time.
