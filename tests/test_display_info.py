"""Parser tests for device/display_info.py, using real `adb shell dumpsys
display` output captured from a physical 165Hz-capable device (Lenovo
TB321FU, active mode 120Hz) -- see display_info.py's module docstring."""

from androidlink.device.display_info import DisplayRefreshInfo, parse_dumpsys_display

_REAL_SNIPPET = """
  DisplayDeviceInfo{"Built-in Screen": uniqueId="local:123", 1600 x 2560, modeId 1, renderFrameRate 120.00001, supportedModes [{id=1, width=1600, height=2560, fps=120.00001}], colorMode 0}
    mDisplayModeSpecs={baseModeId=1 allowGroupSwitching=false primary=physical: (0.0 120.0) render:  (0.0 120.0)}
    mSupportedRefreshRates=[120.00001, 165.0, 144.00002, 90.0, 60.000004, 30.000002]
      DisplayMode{id=0, width=1600, height=2560, xDpi=344.406, yDpi=342.231, peakRefreshRate=165.0, vsyncRate=165.0, group=0}
    mActiveSfDisplayMode=DisplayMode{id=0, width=1600, height=2560, xDpi=344.406, yDpi=342.231, peakRefreshRate=120.00001, vsyncRate=120.00001, appVsyncOffsetNanos=1000000, presentationDeadlineNanos=11333333, supportedHdrTypes=[1, 2, 3], group=0}
"""

_60HZ_ONLY_SNIPPET = """
    mSupportedRefreshRates=[60.000004]
    mActiveSfDisplayMode=DisplayMode{id=0, width=1080, height=2400, peakRefreshRate=60.000004, vsyncRate=60.000004, group=0}
"""


def test_parses_real_high_refresh_device_output():
    info = parse_dumpsys_display(_REAL_SNIPPET)
    assert info == DisplayRefreshInfo(active_hz=120, supported_hz=(30, 60, 90, 120, 144, 165))


def test_parses_60hz_only_device():
    info = parse_dumpsys_display(_60HZ_ONLY_SNIPPET)
    assert info == DisplayRefreshInfo(active_hz=60, supported_hz=(60,))


def test_returns_none_for_unrecognized_output_instead_of_guessing():
    assert parse_dumpsys_display("some unrelated OEM dumpsys format\nno matching fields here") is None


def test_returns_none_for_empty_output():
    assert parse_dumpsys_display("") is None
