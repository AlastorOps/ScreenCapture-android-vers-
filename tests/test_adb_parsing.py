from androidlink.device.adb import RawDeviceEntry, parse_devices_output, parse_getprop_output


def test_parse_devices_output_authorized_device_with_l_flag():
    output = (
        "List of devices attached\n"
        "R58N123ABCD            device usb:1-1 product:d2q model:SM_S921U "
        "device:d2q transport_id:3\n"
    )

    entries = parse_devices_output(output)

    assert entries == [
        RawDeviceEntry(
            serial="R58N123ABCD",
            state="device",
            extra={
                "usb": "1-1",
                "product": "d2q",
                "model": "SM_S921U",
                "device": "d2q",
                "transport_id": "3",
            },
        )
    ]


def test_parse_devices_output_unauthorized_and_offline():
    output = (
        "List of devices attached\n"
        "ABC123    unauthorized usb:1-1\n"
        "emulator-5554    offline\n"
    )

    entries = parse_devices_output(output)

    assert [e.serial for e in entries] == ["ABC123", "emulator-5554"]
    assert [e.state for e in entries] == ["unauthorized", "offline"]


def test_parse_devices_output_empty_when_no_devices():
    output = "List of devices attached\n\n"

    assert parse_devices_output(output) == []


def test_parse_devices_output_ignores_daemon_startup_lines():
    output = (
        "* daemon not running; starting now at tcp:5037\n"
        "* daemon started successfully\n"
        "List of devices attached\n"
        "SERIAL123    device\n"
    )

    entries = parse_devices_output(output)

    assert len(entries) == 1
    assert entries[0].serial == "SERIAL123"


def test_parse_getprop_output():
    output = (
        "[ro.product.model]: [SM-S921U]\n"
        "[ro.product.manufacturer]: [samsung]\n"
        "[ro.build.version.release]: [15]\n"
        "[ro.build.version.sdk]: [35]\n"
    )

    props = parse_getprop_output(output)

    assert props == {
        "ro.product.model": "SM-S921U",
        "ro.product.manufacturer": "samsung",
        "ro.build.version.release": "15",
        "ro.build.version.sdk": "35",
    }


def test_parse_getprop_output_ignores_malformed_lines():
    output = "not a prop line\n[ro.product.model]: [Pixel 9]\n"

    props = parse_getprop_output(output)

    assert props == {"ro.product.model": "Pixel 9"}
