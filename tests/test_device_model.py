from androidlink.device.device_model import (
    AndroidDevice,
    ConnectionState,
    mask_serial,
    parse_connection_state,
)


def test_parse_connection_state_known_values():
    assert parse_connection_state("device") == ConnectionState.DEVICE
    assert parse_connection_state("unauthorized") == ConnectionState.UNAUTHORIZED
    assert parse_connection_state("offline") == ConnectionState.OFFLINE


def test_parse_connection_state_unknown_value_falls_back():
    assert parse_connection_state("bootloader") == ConnectionState.UNKNOWN


def test_mask_serial_masks_long_serials():
    assert mask_serial("R58N123ABCDE") == "R58N···BCDE"


def test_mask_serial_leaves_short_serials_unmasked():
    assert mask_serial("abcd1234") == "abcd1234"


def test_android_device_display_name_prefers_model():
    device = AndroidDevice(
        serial="R58N123ABCDE", connection_state=ConnectionState.DEVICE, model="Galaxy S24"
    )
    assert device.display_name == "Galaxy S24"


def test_android_device_display_name_falls_back_to_masked_serial():
    device = AndroidDevice(serial="R58N123ABCDE", connection_state=ConnectionState.DEVICE)
    assert device.display_name == "R58N···BCDE"
