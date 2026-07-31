import asyncio
import socket

from serial_gateway.telnet import TelnetDecoder, TelnetServer


def test_strips_telnet_negotiation_and_keeps_text():
    data = bytes([255, 253, 3]) + b"printenv\r\n"
    assert TelnetServer._strip_negotiation(data) == b"printenv\r\n"


def test_escaped_iac_is_preserved():
    assert TelnetServer._strip_negotiation(bytes([255, 255])) == bytes([255])


def test_negotiation_split_across_tcp_reads():
    decoder = TelnetDecoder()
    assert decoder.feed(b"ls" + bytes([255, 253])) == b"ls"
    assert decoder.feed(bytes([3]) + b"\t") == b"\t"


def test_subnegotiation_is_removed():
    decoder = TelnetDecoder()
    data = bytes([255, 250, 31, 0, 80, 0, 24, 255, 240]) + b"pwd\r"
    assert decoder.feed(data) == b"pwd\r"


def test_keepalive_uses_short_linux_timeouts():
    class Socket:
        def __init__(self):
            self.options = []

        def setsockopt(self, level, option, value):
            self.options.append((level, option, value))

    class Writer:
        def __init__(self):
            self.socket = Socket()

        def get_extra_info(self, name):
            return self.socket if name == "socket" else None

    writer = Writer()
    TelnetServer._configure_keepalive(writer)
    assert (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1) in writer.socket.options
    if hasattr(socket, "TCP_KEEPIDLE"):
        assert (socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30) in writer.socket.options


def test_only_uart_output_is_sent_to_telnet_clients():
    class Writer:
        def __init__(self):
            self.data = bytearray()

        def write(self, data):
            self.data.extend(data)

        async def drain(self):
            pass

    async def run():
        server = TelnetServer(lambda *_: None)
        writer = Writer()
        server.clients.add(writer)
        for source in ("WEB TX", "AI TX", "HUMAN TX", "SYSTEM", "ERROR"):
            await server.broadcast({"source": source, "data": "hidden"})
        assert writer.data == b""
        output = "Update full flash image ... 53%\rUpdate full flash image ... 54%"
        await server.broadcast({"source": "UART RX", "data": output})
        assert writer.data == output.encode()

    asyncio.run(run())
