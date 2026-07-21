import asyncio

from serial_gateway.telnet import TelnetDecoder, TelnetServer


def test_strips_telnet_negotiation_and_keeps_text():
    data = bytes([255, 253, 3]) + b"printenv\r\n"
    assert TelnetServer._strip_negotiation(data) == b"printenv\r\n"


def test_escaped_iac_is_preserved():
    assert TelnetServer._strip_negotiation(bytes([255, 255])) == bytes([255])


def test_telnet_newlines_are_normalized():
    assert TelnetServer._telnet_newlines("a\nb\r\nc\r") == "a\r\nb\r\nc\r\n"


def test_negotiation_split_across_tcp_reads():
    decoder = TelnetDecoder()
    assert decoder.feed(b"ls" + bytes([255, 253])) == b"ls"
    assert decoder.feed(bytes([3]) + b"\t") == b"\t"


def test_subnegotiation_is_removed():
    decoder = TelnetDecoder()
    data = bytes([255, 250, 31, 0, 80, 0, 24, 255, 240]) + b"pwd\r"
    assert decoder.feed(data) == b"pwd\r"


def test_web_input_is_not_annotated_to_telnet_clients():
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
        await server.broadcast({"source": "WEB TX", "data": "\r"})
        assert writer.data == b""

    asyncio.run(run())
