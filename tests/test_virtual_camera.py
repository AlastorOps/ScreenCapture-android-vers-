import pyvirtualcam
import pytest

from androidlink.camera.virtual_camera import VirtualCameraSink, VirtualCameraUnavailableError


def test_raises_clear_error_when_no_backend_available(monkeypatch):
    """Forces pyvirtualcam's real "no backend" failure (rather than relying
    on this machine happening to have none of OBS Virtual Camera/Unity
    Capture installed, which stopped being true once one was installed to
    test the Camera feature for real) by monkeypatching pyvirtualcam.Camera
    itself to raise the same RuntimeError it raises when no backend is
    found -- everything below that boundary (VirtualCameraSink's own
    exception translation) still runs for real, unmocked."""

    def _raise(*_args, **_kwargs):
        raise RuntimeError(
            "Could not run virtual camera: no output found. "
            "Try to install OBS Studio or Unity Capture."
        )

    monkeypatch.setattr(pyvirtualcam, "Camera", _raise)

    with pytest.raises(VirtualCameraUnavailableError) as exc_info:
        VirtualCameraSink(640, 480, 30)

    message = str(exc_info.value)
    assert "obs" in message.lower() or "unitycapture" in message.lower() or "unity capture" in message.lower()


def test_opens_successfully_when_a_backend_is_available():
    """The inverse case, run unconditionally for real: if this machine has
    OBS Virtual Camera/Unity Capture installed, VirtualCameraSink must
    actually open it rather than raising -- skipped (not failed) if this
    machine genuinely has neither installed, since there's nothing real to
    verify against in that case."""
    try:
        sink = VirtualCameraSink(64, 64, 30)
    except VirtualCameraUnavailableError:
        pytest.skip("No virtual camera backend installed on this machine")
    else:
        assert sink.backend_device_name
        sink.close()
