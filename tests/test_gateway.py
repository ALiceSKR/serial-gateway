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
