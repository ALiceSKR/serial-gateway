import asyncio

from serial import SerialException

from serial_gateway.gateway import SerialGateway
from serial_gateway.models import PortConfig


def test_uart_utf8_survives_every_read_boundary_and_timeouts():
    text = '\x1b[32m中文串口 → ready 😀\x1b[0m\r\n'
    payload = text.encode()

    async def run(chunks):
        events = []

        async def emit(event):
            events.append(event)

        class Serial:
            def read(self, size):
                try:
                    return next(chunks)
                except StopIteration:
                    raise SerialException('test disconnected')

        gateway = SerialGateway(
            PortConfig(id='uart0', name='Test', device='/dev/test', telnet_port=2000), emit
        )
        gateway.serial = Serial()
        await gateway._read_loop()
        return ''.join(event['data'] for event in events if event['source'] == 'UART RX')

    for split in range(len(payload) + 1):
        assert asyncio.run(run(iter([payload[:split], b'', payload[split:]]))) == text
    assert asyncio.run(run(iter(bytes([byte]) for byte in payload))) == text


def test_uart_bytes_reach_raw_sink_without_text_conversion():
    payload = b"\x00\xff\x80\r\n\xf0\x9f\x98\x80"

    async def run():
        raw = []

        async def emit(_event):
            pass

        async def emit_raw(data):
            raw.append(data)

        class Serial:
            def __init__(self):
                self.chunks = iter([payload[:3], payload[3:], SerialException("done")])

            def read(self, _size):
                item = next(self.chunks)
                if isinstance(item, Exception):
                    raise item
                return item

        gateway = SerialGateway(
            PortConfig(id="uart0", name="Test", device="/dev/test", telnet_port=3000),
            emit,
            emit_raw,
        )
        gateway.serial = Serial()
        await gateway._read_loop()
        assert b"".join(raw) == payload

    asyncio.run(run())


def test_usr_vcom_settings_are_applied_to_open_serial_port():
    async def run():
        events = []

        async def emit(event):
            events.append(event)

        class Serial:
            is_open = True
            baudrate = 115200
            bytesize = 8
            parity = "N"
            stopbits = 1

        settings = PortConfig(
            id="uart0", name="Test", device="/dev/test", telnet_port=3000
        )
        gateway = SerialGateway(settings, emit)
        gateway.serial = Serial()
        await gateway.apply_serial_settings(9600, 7, "E", 2)
        assert (gateway.serial.baudrate, gateway.serial.bytesize) == (9600, 7)
        assert (gateway.serial.parity, gateway.serial.stopbits) == ("E", 2)
        assert (settings.baudrate, settings.bytesize, settings.parity, settings.stopbits) == (
            9600,
            7,
            "E",
            2,
        )
        assert "USR-VCOM 已同步串口参数" in events[-1]["data"]

    asyncio.run(run())
