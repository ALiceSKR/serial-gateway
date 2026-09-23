import asyncio

from serial_gateway.raw_tcp import RawTcpServer, UsrSerialSettings, UsrVcomParser


class Writer:
    def __init__(self):
        self.data = bytearray()

    def get_extra_info(self, _name):
        return None

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass


def test_raw_tcp_input_is_forwarded_byte_for_byte_without_banner():
    class Reader:
        def __init__(self):
            self.chunks = iter([b"\x00\xff", b"\x80\r\x00", b""])

        async def read(self, _size):
            return next(self.chunks)

    async def run():
        received = []

        async def send(data, source):
            received.append((data, source))

        writer = Writer()
        await RawTcpServer(send)._client(Reader(), writer)
        assert writer.data == b""
        assert received == [
            (b"\x00\xff", "RAW TCP TX"),
            (b"\x80\r\x00", "RAW TCP TX"),
        ]

    asyncio.run(run())


def test_raw_tcp_uart_output_is_broadcast_byte_for_byte():
    async def run():
        server = RawTcpServer(lambda *_: None)
        first, second = Writer(), Writer()
        server.clients.update((first, second))
        payload = b"\x00\xff\x80\r\n"
        await server.broadcast(payload)
        assert first.data == payload
        assert second.data == payload

    asyncio.run(run())


def test_usr_vcom_parser_accepts_old_and_new_control_frames_across_boundaries():
    frames = (
        b"\x55\xaa\x55\x01\xc2\x00\x03\xc6",
        b"\x55\xaa\x55\x01\xc2\x00\x83\x46",
    )
    for frame in frames:
        for split in range(len(frame) + 1):
            parser = UsrVcomParser()
            events = parser.feed(b"before" + frame[:split]) + parser.feed(frame[split:] + b"after")
            assert events == [
                b"before",
                UsrSerialSettings(115200, 8, "N", 1),
                b"after",
            ]


def test_usr_vcom_parser_preserves_invalid_frames():
    payload = b"data\x55\xaa\x55\x01\xc2\x00\x03\x00tail"
    parser = UsrVcomParser()
    assert b"".join(item for item in parser.feed(payload) + [parser.flush()] if isinstance(item, bytes)) == payload


def test_raw_tcp_consumes_sync_frame_and_applies_settings():
    class Reader:
        def __init__(self):
            self.chunks = iter([b"abc\x55\xaa", b"\x55\x00\x25\x80\x1b\xc0def", b""])

        async def read(self, _size):
            return next(self.chunks)

    async def run():
        received, settings = [], []

        async def send(data, source):
            received.append((data, source))

        async def apply(*values):
            settings.append(values)

        await RawTcpServer(send, apply)._client(Reader(), Writer())
        assert received == [(b"abc", "RAW TCP TX"), (b"def", "RAW TCP TX")]
        assert settings == [(9600, 8, "E", 1)]

    asyncio.run(run())
