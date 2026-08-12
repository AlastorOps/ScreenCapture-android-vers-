# Build a Full Android-to-Windows USB Connectivity Desktop Application

## Role

You are a senior software architect and full-stack systems engineer specializing in:

* Python desktop applications
* Windows multimedia APIs
* Android ADB/USB communication
* Low-latency video streaming
* Hardware-accelerated video encoding/decoding
* Android Camera2/CameraX
* Android audio capture
* Windows virtual camera devices
* Windows virtual audio devices
* Real-time input injection
* Desktop UI/UX
* Performance optimization

Your task is to design and implement a **production-quality Windows desktop application** that connects an Android device to a Windows PC over **USB Type-C**.

This is not a simple proof of concept. Build the project as a properly structured, maintainable desktop application with a modular architecture, robust error handling, diagnostics, automatic capability detection, and a polished user interface.

---

# 1. Product Concept

Create a desktop application that acts as an **Android-to-PC USB companion and control center**.

The application must allow a user to connect an Android phone to a Windows PC through USB Type-C and selectively enable:

1. Android screen casting → PC
2. PC mouse control → Android
3. PC keyboard input → Android
4. Android audio → PC
5. Android camera → Windows virtual webcam
6. Android microphone → Windows virtual microphone
7. PC-side screenshots
8. PC-side screen/cast recording

Every major feature must be independently toggleable.

The application should feel like a polished native desktop utility rather than a command-line wrapper.

---

# 2. Supported Platforms

## PC

Primary target:

* Windows 10 64-bit
* Windows 11 64-bit

Design the architecture so Linux/macOS support could potentially be added later, but do not sacrifice Windows functionality to achieve cross-platform compatibility.

## Android

Minimum:

* Android 10 / API 29

Target:

* Latest stable Android SDK

Use runtime capability detection rather than assuming every Android device supports every feature.

If a device cannot support a particular feature, clearly show:

* Unsupported
* Why it is unsupported
* What alternative is available

Do not silently fail.

---

# 3. USB Connection

USB is the only transport.

Do NOT require:

* Wi-Fi
* Internet
* Bluetooth
* Cloud services

The normal architecture should use:

* USB
* ADB
* Android USB debugging
* ADB port forwarding/reverse where appropriate
* A companion Android application when it provides better functionality

The PC application should control the connection.

## Device discovery

When Android devices are connected:

* Detect them automatically.
* Display connected devices.
* Show device model.
* Show manufacturer.
* Show Android version.
* Show device serial/identifier in a safe user-facing form.
* Show connection state.
* Show available capabilities.

Do not automatically take control of a device.

The user must explicitly click:

**Connect**

Support multiple connected Android devices where practical.

Example:

```text
ANDROID DEVICES

● Samsung Galaxy S24
  Android 15
  USB Connected

                     [ CONNECT ]

○ Xiaomi 14
  Android 14
  USB Connected

                     [ CONNECT ]
```

After connecting, provide:

* Disconnect
* Reconnect
* Device information
* Diagnostics

Handle USB disconnects gracefully.

---

# 4. Android Companion Application

You may create a small Android companion application if it provides better:

* camera streaming
* microphone capture
* audio capture
* video transport
* device capability detection
* performance
* reliability

Do not force all functionality through ADB if that would significantly reduce quality.

The architecture should be:

```text
Windows Desktop Application
          │
          │ USB
          │
       ADB / USB
          │
          ▼
Android Companion Service/App
          │
          ├── Screen
          ├── Touch/Input
          ├── Camera
          ├── Microphone
          └── Audio
```

Use ADB-only functionality where it is technically superior.

The Android companion must request permissions correctly and explain why each permission is needed.

---

# 5. Screen Casting

The core feature is:

**Android screen → Windows PC**

The screen should be rendered inside the desktop application.

## Performance requirements

Performance is a major priority.

Target:

* Automatic mode: the highest stable FPS up to a hard ceiling of **165 FPS**, matching the Android device's own detected refresh rate (never artificially capped at 60 for a more capable device, and never requested above 165 even for a 240Hz-class panel)
* 1080p/60 and 1440p/60 at minimum where supported
* Higher resolution/FPS when the device genuinely supports it, subject to the 165 FPS ceiling

Supported manual FPS target modes: 30 / 60 / 90 / 120 / 144 / 165. The application must never request or target anything above 165 FPS, regardless of what the connected device's panel is capable of.

The application should automatically detect:

* Android display resolution
* Refresh rate
* Encoder capabilities
* Codec support
* USB transport performance
* PC decoding capabilities
* Windows monitor refresh rate, where possible (informational -- does not itself lower the FPS target, since requesting more frames than the monitor can display costs a little extra encode/decode work but never adds latency or duplicates frames)
* GPU capabilities

Then select the highest practical configuration.

Do not blindly request the highest possible resolution if it causes instability. The same applies to FPS: if 165 FPS proves unstable, dynamically fall back to the next lower standard tier (e.g. 144) rather than forcing 165 or collapsing straight to 60.

Prioritize:

1. Smoothness
2. Low latency
3. Stable frame delivery
4. Image quality

The application must aggressively minimize:

* frame drops
* unnecessary buffering
* jitter
* latency
* CPU overhead
* memory copies

Do not promise mathematically zero latency or zero frame drops. Instead engineer for the lowest practical latency and stable frame delivery.

---

# 6. Performance / Quality Slider

Provide a simple user-facing slider:

```text
PERFORMANCE ◄──────────────► QUALITY
```

The slider should automatically modify internal streaming parameters.

For example:

### Performance mode

Prioritize:

* lowest latency
* high FPS
* lower buffering
* efficient encoding
* stable frame delivery

### Balanced mode

Balance:

* quality
* latency
* FPS
* USB bandwidth

### Quality mode

Prioritize:

* higher resolution
* higher bitrate
* image quality

The user should not need to manually configure complicated codec parameters unless they open an Advanced Settings section.

The slider must actually reach the streaming pipeline, not just its own displayed position/label. Concretely it drives resolution and bitrate (the two real levers a fixed-protocol encoder session exposes -- see streaming/performance.py's resolve_streaming_profile()); FPS stays targeted at the highest practical rate at every position (capped at the FPS ceiling in section 5), since a lighter Performance-end frame budget is what actually makes a high FPS easier to sustain, not a lower FPS target. Releasing the slider applies the new position immediately to an already-active cast session by restarting the streaming session -- the Android device itself stays connected throughout; only the next time Cast is turned on is not an acceptable place for a change to first take effect.

There is exactly one copy of this slider in the app (Device panel, directly under Microphone -- see section 17).

---

# 7. Video Codec Architecture

Implement codec abstraction so the application can use the best available codec.

Potential codecs:

* H.264
* H.265/HEVC
* AV1 where genuinely supported

Detect capabilities dynamically.

Do not force AV1 or HEVC if the Android device or Windows PC cannot decode it efficiently.

Prefer hardware-accelerated decoding on Windows when available.

Avoid unnecessary:

```text
Android
→ decode
→ convert
→ copy
→ encode
→ decode
→ render
```

when a more efficient pipeline is possible.

Use zero-copy or low-copy paths where practical.

---

# 8. Screen Display

The Android screen must be displayed inside the application.

Requirements:

* Freely resizable
* Preserve correct aspect ratio
* Portrait support
* Landscape support
* Device rotation handling
* Fullscreen mode
* Smooth scaling
* Optional zoom
* No stretching by default
* Smooth rendering
* Avoid UI-thread blocking

The main screen renderer should be independent from the rest of the UI.

The video rendering pipeline must not run expensive operations on the UI thread.

---

# 9. Remote Android Control

The PC must be able to control the Android device.

## Mouse

Mouse input should translate into Android touch input.

Support:

* Tap
* Double tap
* Press
* Drag
* Swipe
* Scroll
* Touch-like gestures

Coordinate mapping must remain correct when:

* window is resized
* aspect ratio changes
* device rotates
* zoom changes
* fullscreen is enabled

## Keyboard

When the user types into the Android screen:

* Forward keyboard input to Android.
* Support normal text entry.
* Handle modifier keys appropriately.
* Avoid typing into the desktop application's own controls when the Android display has focus.

The user specifically wants:

> Mouse for control, keyboard when typing.

Do not build an unnecessary gamepad/controller system.

---

# 10. Android Audio → PC

The application must support:

**Android audio → Windows PC**

The audio system should be independently toggleable.

Example:

```text
ANDROID AUDIO

[ ● ON ]

Volume
────────●──────

Mute [ OFF ]
```

Requirements:

* Low latency
* Stable audio
* Avoid unnecessary buffering
* Detect Android audio capability
* Handle audio disconnects
* Synchronize reasonably with screen video
* Use appropriate sample rate/channel configuration
* Avoid audio glitches where possible

Allow PC-side volume and mute control.

---

# 11. Android Camera → Windows Webcam

The Android phone should be usable as a webcam.

The feature must be independently toggleable:

```text
CAMERA

[ ON / OFF ]

Camera:
[ Rear Camera ▼ ]

Resolution:
[ Automatic ▼ ]

FPS:
[ Automatic ▼ ]
```

Detect all available cameras.

Allow the PC user to select:

* Front camera
* Rear camera
* Other cameras when available

The camera must be capable of being exposed to Windows as a **virtual camera device**, so applications such as:

* OBS
* Discord
* Zoom
* Microsoft Teams
* Windows Camera
* Other Windows applications

can potentially select it as a camera source.

Use an appropriate Windows virtual-camera architecture.

Do not fake this by merely displaying the camera preview inside the application.

It should function as an actual Windows camera device where technically supported.

---

# 12. Android Microphone → Windows Microphone

The Android microphone must be independently toggleable.

Example:

```text
MICROPHONE

[ ON / OFF ]

Input:
[ Default Mic ▼ ]

Volume:
────────●──────

Mute:
[ OFF ]
```

Detect available Android audio input sources where practical.

Allow selection.

Support:

* Mute/unmute
* Input volume
* Stable low-latency streaming
* Sample-rate negotiation
* Proper buffering

Expose the stream as a **Windows virtual microphone/audio input device** where technically supported.

The goal is for applications such as:

* Discord
* OBS
* Zoom
* Teams
* Windows applications

to be able to select the Android microphone as an input device.

---

# 13. Independent Feature Toggles

Every major feature must work independently.

Example:

```text
SCREEN CAST      ● ON
REMOTE CONTROL   ● ON
ANDROID AUDIO    ● ON
WEBCAM           ○ OFF
MICROPHONE       ○ OFF
```

Another valid configuration:

```text
SCREEN CAST      ○ OFF
REMOTE CONTROL   ○ OFF
ANDROID AUDIO    ○ OFF
WEBCAM           ● ON
MICROPHONE       ● ON
```

Do not make unrelated features dependent on each other unless the underlying Android/Windows architecture technically requires it.

If a dependency exists, clearly explain it in the UI.

---

# 14. PC-Side Recording

Recording is handled by the PC.

Do not require Android to perform the recording.

The PC should be able to record the rendered/cast content.

Requirements:

* PC-side recording
* Local file storage
* Start
* Stop
* Pause/resume if practical
* Recording status
* Recording timer
* Hardware encoding where available
* Avoid unnecessarily degrading live casting performance

Support screenshots from the PC side.

Use sensible default recording formats, but structure the recording subsystem so additional formats can be added later.

---

# 15. UI / UX

The application needs a complete interactive desktop UI.

Do NOT build a basic Tkinter-looking utility.

The design should be inspired by:

**https://github.com/nekonako/dotfiles**

Use the repository as visual inspiration for:

* dark Linux-rice aesthetic
* compact panels
* custom typography
* minimal visual clutter
* strong contrast
* modern widgets
* highly customized desktop-tool appearance

Do not blindly copy code or assets from the repository.

Translate the aesthetic into a polished Windows desktop application.

## Default theme

* Dark
* Minimal
* Modern
* Technical
* Compact
* High information density
* Subtle animations
* Clear status indicators

Allow customizable accent color.

---

# 16. Customizable UI Layout

The UI layout must be customizable.

Allow users to:

* Show/hide panels
* Rearrange panels
* Resize panels
* Customize dashboard layout
* Save layout
* Restore default layout

Potential panels:

```text
Device
Screen
Performance
Audio
Camera
Microphone
Controls
Recording
Diagnostics
Settings
```

Do not make the interface unnecessarily complicated.

Provide a clean default layout.

---

# 17. Suggested UI Structure

Use a structure similar to:

```text
┌──────────────────────────────────────────────────────┐
│ AndroidLink                              ● USB       │
├───────────────┬──────────────────────────┬───────────┤
│               │                          │           │
│ DEVICE        │                          │ STATUS    │
│               │                          │           │
│ Galaxy S24    │                          │ Target FPS│
│ Android 15    │      ANDROID SCREEN      │ 120       │
│               │                          │ Stream FPS│
│ [Disconnect]  │                          │ 118.4     │
│               │                          │ Latency   │
│ FEATURES      │                          │ 18 ms     │
│               │                          │           │
│ Cast     ●    │                          │           │
│ Control  ●    │                          │           │
│ Audio    ●    │                          │           │
│ Camera   ○    │                          │           │
│ Mic      ○    │                          │           │
│               │                          │           │
│ PERFORMANCE / │                          │           │
│ QUALITY       │                          │           │
│ Perf ●── Qual │                          │           │
│      70%      │                          │           │
└───────────────┴──────────────────────────┴───────────┘
```

The Performance/Quality slider lives in the Device panel, directly under
Microphone -- there is exactly one copy of it in the app. It applies
immediately to an already-active cast session (by restarting the streaming
session, not by disconnecting the Android device), never just its own
displayed label. This is only a conceptual layout; the actual UI should be
visually polished.

---

# 18. Setup Wizard

When the application is first launched, provide a guided setup.

Check:

* ADB availability
* USB drivers
* Android device detection
* USB debugging
* Android version
* Required permissions
* Camera permission
* Microphone permission
* Required companion app
* Windows virtual device dependencies

Example:

```text
ANDROID SETUP

✓ ADB installed
✓ USB device detected
✓ USB debugging enabled
✓ Device authorized
⚠ Camera permission required
⚠ Microphone permission required

[ Fix Automatically ]

[ Setup Guide ]
```

Where Android requires physical user confirmation, explain exactly what the user must do.

Never silently modify security-sensitive Android settings.

---

# 19. Device Capability Detection

After connecting, create a capability profile.

Detect where possible:

* Android version
* Device model
* Display resolution
* Display refresh rate
* Video encoder capabilities
* Supported codecs
* Camera list
* Camera resolutions
* Camera FPS capabilities
* Microphone/audio capabilities
* USB connection state
* Device performance characteristics

Use these capabilities to dynamically configure the application.

---

# 20. Diagnostics

Provide a diagnostics page.

Display:

* USB status
* ADB status
* Device status
* Video FPS
* Render FPS
* Dropped frames
* Decode latency
* End-to-end latency estimate
* Bitrate
* Resolution
* Codec
* CPU usage
* GPU usage where available
* RAM usage
* Audio latency
* Camera status
* Microphone status

Use these metrics to help troubleshoot performance problems.

Example:

```text
PERFORMANCE

Display Refresh  165 Hz
Target FPS       165
Render FPS       164.2
Stream FPS       164.7
Dropped Frames   0
Resolution       2560 × 1440
Bitrate          35 Mbps
Codec            H.264
Decode           Hardware
Latency          ~18 ms
CPU              12%
GPU              18%
```

Target FPS is what's actually requested from the encoder (never shown as if it were a measurement); Display Refresh, Render FPS, Stream FPS, Dropped Frames, Resolution, Bitrate, and Codec are all genuinely measured values, never fabricated.

---

# 21. Error Handling

Errors must be understandable.

Never display only:

```text
Error: subprocess failed
```

Instead explain:

```text
USB debugging authorization is required.

Unlock your Android phone and accept:
"Allow USB debugging?"

[ Retry ]
[ Setup Guide ]
```

Handle:

* Device disconnected
* ADB unavailable
* USB debugging disabled
* Device unauthorized
* Device offline
* Unsupported Android version
* Unsupported codec
* Camera permission denied
* Microphone permission denied
* Virtual camera unavailable
* Virtual microphone unavailable
* Decoder failure
* Encoder failure
* USB bandwidth problems
* Companion application unavailable

---

# 22. Performance Architecture

Use asynchronous/non-blocking architecture.

Do not block the main UI thread with:

* ADB commands
* video decoding
* audio processing
* camera processing
* device discovery
* file I/O

Use appropriate concurrency mechanisms such as:

* asyncio
* worker threads
* multiprocessing
* native libraries

where appropriate.

The architecture should separate:

```text
UI
│
├── Device Manager
│
├── ADB Transport
│
├── Android Companion Manager
│
├── Video Pipeline
│   ├── Capture
│   ├── Decode
│   └── Render
│
├── Audio Pipeline
│
├── Input Controller
│
├── Camera Pipeline
│
├── Microphone Pipeline
│
├── Virtual Device Manager
│
├── Recorder
│
├── Performance Monitor
│
└── Settings Manager
```

---

# 23. Recommended Python Architecture

Use a maintainable package structure.

Example:

```text
androidlink/
│
├── app/
│   ├── main.py
│   ├── application.py
│   └── lifecycle.py
│
├── ui/
│   ├── windows/
│   ├── panels/
│   ├── widgets/
│   ├── themes/
│   └── layout/
│
├── device/
│   ├── manager.py
│   ├── adb.py
│   ├── capabilities.py
│   └── device_model.py
│
├── streaming/
│   ├── video.py
│   ├── decoder.py
│   ├── renderer.py
│   ├── transport.py
│   └── performance.py
│
├── audio/
│   ├── android_audio.py
│   ├── audio_pipeline.py
│   └── virtual_audio.py
│
├── camera/
│   ├── camera_manager.py
│   ├── camera_pipeline.py
│   └── virtual_camera.py
│
├── input/
│   ├── mouse.py
│   ├── keyboard.py
│   └── touch_mapper.py
│
├── recording/
│   ├── recorder.py
│   └── screenshots.py
│
├── setup/
│   ├── wizard.py
│   ├── permissions.py
│   └── diagnostics.py
│
├── settings/
│   ├── manager.py
│   └── models.py
│
└── utils/
    ├── logging.py
    ├── platform.py
    └── errors.py
```

The exact structure can change if a better architecture is justified.

---

# 24. Technology Selection

Choose technologies based on actual technical suitability.

Do not automatically choose Tkinter.

Evaluate appropriate modern Python desktop UI frameworks such as:

* PySide6 / Qt
* PyQt
* another suitable framework

Prefer **PySide6** if it satisfies the requirements.

For video:

Evaluate suitable technologies such as:

* FFmpeg
* PyAV
* GStreamer
* native Windows Media Foundation
* Direct3D/OpenGL/Vulkan-backed rendering
* hardware acceleration

Choose the most reliable architecture.

For Android:

* ADB
* Android SDK
* Kotlin/Java companion application if needed
* Camera2/CameraX
* MediaCodec
* AudioRecord
* MediaProjection where appropriate

For Windows virtual camera/audio functionality, investigate the correct modern Windows-supported architecture rather than creating a fake preview device.

---

# 25. Security

The application must not require unnecessary elevated privileges.

Do not:

* bypass Android security
* disable Windows security
* silently install suspicious drivers
* transmit data over the Internet
* upload user media
* collect telemetry by default

All Android ↔ PC communication should remain local over USB.

Clearly explain any Windows driver or virtual-device installation requirement.

---

# 26. Offline Operation

The application should work without Internet after installation.

Runtime requirements:

```text
Android
   │
   │ USB Type-C
   ▼
Windows PC
```

No cloud server should be required.

No Internet connection should be required for:

* screen casting
* control
* audio
* webcam
* microphone
* recording

---

# 27. Settings

Create a proper Settings page.

Sections:

### General

* Start behavior
* Theme
* Accent color
* Layout
* Language if implemented

### Streaming

* Performance/Quality
* Resolution
* FPS
* Codec
* Bitrate
* Advanced options

### Audio

* Android audio
* Volume
* Output device

### Camera

* Camera selection
* Resolution
* FPS

### Microphone

* Input selection
* Volume
* Mute

### Recording

* Save location
* Format
* Quality

### Device

* Connected device
* Reconnect behavior
* Companion app settings

### Diagnostics

* Logging
* Debug mode
* Performance metrics

---

# 28. Logging

Implement structured logging.

Logs should help diagnose:

* ADB failures
* USB connection problems
* codec errors
* frame drops
* audio problems
* camera failures
* virtual-device failures

Do not log sensitive user content unnecessarily.

Provide:

**Open Logs**

from the application.

---

# 29. Configuration Persistence

Persist:

* selected device
* theme
* accent color
* UI layout
* performance/quality setting
* camera selection
* microphone selection
* audio volume
* recording directory
* other user preferences

Use a proper configuration model.

Do not hardcode settings throughout the application.

---

# 30. Testing

Create tests for:

* device detection
* ADB communication
* capability detection
* configuration persistence
* UI state
* coordinate mapping
* reconnect logic
* stream state management
* error handling

Where hardware is unavailable, create mock interfaces so software components can be tested independently.

---

# 31. Build and Packaging

The final application should be distributable as a Windows application.

Provide a reliable build process.

Prefer:

* PyInstaller
* or another suitable Windows packaging system

The final package should not require the user to manually install Python.

Document:

* development setup
* build process
* dependencies
* ADB requirements
* Android companion installation
* Windows virtual device requirements

---

# 32. Development Process

Do NOT generate the entire application as one giant unstructured file.

Implement in stages:

### Phase 1

Project foundation:

* Python environment
* UI
* theme
* configuration
* logging

### Phase 2

USB/ADB:

* device detection
* device selection
* connect/disconnect
* diagnostics

### Phase 3

Screen casting:

* video transport
* decoder
* renderer
* FPS monitoring
* performance slider

### Phase 4

Remote control:

* mouse
* keyboard
* coordinate mapping

### Phase 5

Android audio:

* audio transport
* playback
* volume/mute

### Phase 6

Camera:

* Android camera capture
* PC preview
* Windows virtual camera

### Phase 7

Microphone:

* Android microphone capture
* PC monitoring
* Windows virtual microphone

### Phase 8

Recording:

* PC-side recording
* screenshots

### Phase 9

Polish:

* customizable layout
* animations
* diagnostics
* error handling
* setup wizard
* packaging

At the end of each phase, ensure the application still runs.

---

# 33. Critical Engineering Rule

Do not pretend a feature is implemented when the underlying Windows/Android APIs do not support it.

For technically difficult features such as:

* Windows virtual webcam
* Windows virtual microphone
* ultra-low-latency video
* hardware-accelerated decoding

research the actual implementation requirements and use appropriate native components when necessary.

Python may act as the orchestration/UI layer while performance-critical components can use:

* C/C++
* Rust
* Kotlin
* Java
* native Windows APIs
* FFmpeg
* Media Foundation

if necessary.

The goal is a **working application**, not a Python-only constraint.

---

# 34. Important Performance Principle

The application should measure actual performance rather than claiming:

> "0 ms latency"

or

> "0 dropped frames"

Instead show real measurements.

Optimize the pipeline for:

```text
Android capture
      ↓
Hardware encoder
      ↓
USB transport
      ↓
Hardware decoder
      ↓
GPU rendering
      ↓
Windows display
```

Minimize:

* copies
* conversions
* buffering
* synchronization delays
* unnecessary encoding steps

Use frame queues carefully to prevent latency from accumulating.

If frames fall behind, prioritize **fresh frames over displaying old frames** when appropriate.

---

# 35. Final User Experience

The finished application should feel like:

> A professional Android USB control center for Windows.

The user should be able to:

1. Plug Android into USB Type-C.
2. Open the application.
3. See the phone.
4. Select it.
5. Click Connect.
6. See the Android screen.
7. Control it with the mouse.
8. Type using the keyboard.
9. Enable Android audio.
10. Enable the phone camera as a Windows webcam.
11. Enable the phone microphone as a Windows microphone.
12. Adjust Performance ↔ Quality.
13. Resize the Android display freely.
14. Customize the application layout.
15. Record from the PC.
16. Disconnect safely.

Everything should be understandable without reading technical documentation.

---

# 36. Deliverables

Produce:

1. Complete source code
2. Windows build configuration
3. Android companion project if required
4. Requirements/dependency files
5. Build scripts
6. Configuration system
7. Tests
8. README
9. Setup guide
10. Troubleshooting guide
11. Architecture documentation

The README must explain:

* What the application does
* Requirements
* Android setup
* USB debugging setup
* Installation
* Running in development
* Building Windows executable
* Building Android companion
* Virtual webcam setup
* Virtual microphone setup
* Troubleshooting
* Known hardware limitations

---

# 37. Final Instruction

Before implementing any major subsystem, explain the chosen technical approach briefly and why it is appropriate.

Do not use placeholder implementations for core functionality.

Do not create fake buttons that do nothing.

If a requested feature requires a native Windows component or Android companion application, implement the required component or clearly isolate it behind an interface and explain the build requirement.

Prioritize:

**Reliability > Low latency > Smoothness > Image quality > Convenience**

while still providing the highest practical quality supported by the connected hardware.

The final result must be a cohesive desktop product, not a collection of unrelated scripts.
