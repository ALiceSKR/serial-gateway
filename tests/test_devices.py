from serial_gateway.models import SerialDevice


def test_serial_device_can_represent_offline_configuration():
    device = SerialDevice(
        device="/dev/ttyUSB0",
        description="已配置（当前未检测到）",
        display_name="/dev/ttyUSB0 · 已配置（当前未检测到）",
        available=False,
    )
    assert device.device == "/dev/ttyUSB0"
    assert device.available is False
