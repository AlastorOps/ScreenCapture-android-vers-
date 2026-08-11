# Vendored: scrcpy-server

- Source: https://github.com/Genymobile/scrcpy
- Version: v4.1
- File: `scrcpy-server-v4.1.jar`
- Downloaded from: https://github.com/Genymobile/scrcpy/releases/download/v4.1/scrcpy-server-v4.1
- SHA-256: `deacb991ed2509715160ffdc7907e47b4160eb30d1566217e9047fd5b8850cae`
  (verified against the release's `SHA256SUMS.txt`)
- License: Apache License 2.0 (see https://github.com/Genymobile/scrcpy/blob/v4.1/LICENSE)

This is the unmodified, official prebuilt server component that scrcpy pushes
to the Android device over ADB. AndroidLink drives it directly (video only,
audio/control disabled) rather than reimplementing on-device screen capture.
The device-side wire protocol (video socket handshake, frame/session framing)
implemented in `androidlink/streaming/protocol.py` was derived by reading this
exact version's source (`server/src/main/java/com/genymobile/scrcpy/device/DesktopConnection.java`
and `Streamer.java`) to ensure byte-for-byte compatibility.
