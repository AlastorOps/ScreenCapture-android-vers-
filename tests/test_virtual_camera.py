import pytest

from androidlink.camera.virtual_camera import VirtualCameraSink, VirtualCameraUnavailableError


def test_raises_clear_error_when_no_backend_available():
    """This machine has neither OBS Virtual Camera nor Unity Capture
    installed, so this genuinely exercises the real no-backend failure path
    end-to-end rather than mocking it."""
    with pytest.raises(VirtualCameraUnavailableError) as exc_info:
        VirtualCameraSink(640, 480, 30)

    message = str(exc_info.value)
    assert "obs" in message.lower() or "unitycapture" in message.lower()
