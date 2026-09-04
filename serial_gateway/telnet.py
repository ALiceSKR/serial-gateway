import asyncio
import socket
from collections.abc import Awaitable, Callable


class TelnetDecoder:
    """Decode Telnet commands and NVT input for an interactive serial console."""

    def __init__(self) -> None:
        self.state = "data"
        self.after_cr = False

    def feed(self, data: bytes) -> bytes:
        result = bytearray()
        for byte in data:
            if self.state == "data":
                if byte == 255:
                    self.state = "iac"
                else:
                    result.append(byte)
            elif self.state == "iac":
                if byte == 255:
                    result.append(byte)
                    self.state = "data"
                elif byte in {251, 252, 253, 254}:
                    self.state = "option"
                elif byte == 250:
                    self.state = "subnegotiation"
                else:
                    self.state = "data"
            elif self.state == "option":
                self.state = "data"
            elif self.state == "subnegotiation":
                if byte == 255:
                    self.state = "sub_iac"
            elif self.state == "sub_iac":
                self.state = "data" if byte == 240 else "subnegotiation"
        # No BINARY option is negotiated: RFC 854 encodes Enter as CR LF
        # or CR NUL. Forward CR immediately, then consume its companion even
        # across TCP reads or intervening Telnet commands. Passing NUL to the
        # console can terminate password readers and other interactive tools.
        clean = bytearray()
        for byte in result:
            if self.after_cr and byte in {0, 10}:
                self.after_cr = False
                continue
            clean.append(byte)
            self.after_cr = byte == 13
        return bytes(clean)


class TelnetServer:
    IAC = 255
    NOP = 241
    DO = 253
    DONT = 254
    WILL = 251
    ECHO = 1
    SGA = 3
    LINEMODE = 34

    def __init__(self, send_serial: Callable[[str, str], Awaitable[None]]) -> None:
        self.send_serial = send_serial
        self.server: asyncio.Server | None = None
        self.clients: set[asyncio.StreamWriter] = set()

    async def start(self, host: str = "0.0.0.0", port: int = 2000) -> None:
        self.server = await asyncio.start_server(self._client, host, port)

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for writer in tuple(self.clients):
            writer.close()
        self.clients.clear()

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._configure_keepalive(writer)
        self.clients.add(writer)
        writer.write(
            bytes(
                [
                    self.IAC, self.WILL, self.ECHO,
                    self.IAC, self.WILL, self.SGA,
                    self.IAC, self.DO, self.SGA,
                    self.IAC, self.DONT, self.LINEMODE,
                ]
            )
        )
        writer.write(b"\r\nSerial Gateway connected.\r\n")
        await writer.drain()
        decoder = TelnetDecoder()
        heartbeat = asyncio.create_task(self._heartbeat(writer))
        try:
            while data := await reader.read(4096):
                clean = decoder.feed(data)
                if clean:
                    await self.send_serial(clean.decode("utf-8", errors="replace"), "HUMAN TX")
        except (ConnectionError, RuntimeError):
            pass
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            self.clients.discard(writer)
            writer.close()
            await writer.wait_closed()

    @staticmethod
    def _configure_keepalive(writer: asyncio.StreamWriter) -> None:
        sock = writer.get_extra_info("socket")
        if sock is None:
            return
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        options = (
            ("TCP_KEEPIDLE", 30),
            ("TCP_KEEPINTVL", 10),
            ("TCP_KEEPCNT", 3),
            ("TCP_USER_TIMEOUT", 30_000),
        )
        for name, value in options:
            option = getattr(socket, name, None)
            if option is not None:
                sock.setsockopt(socket.IPPROTO_TCP, option, value)

    async def _heartbeat(self, writer: asyncio.StreamWriter) -> None:
        try:
            while not writer.is_closing():
                await asyncio.sleep(20)
                writer.write(bytes([self.IAC, self.NOP]))
                await asyncio.wait_for(writer.drain(), timeout=5)
        except (ConnectionError, OSError, asyncio.TimeoutError):
            writer.close()

    @classmethod
    def _strip_negotiation(cls, data: bytes) -> bytes:
        return TelnetDecoder().feed(data)

    async def broadcast(self, event: dict) -> None:
        source = event["source"]
        if source == "UART RX":
            payload = event["data"].encode()
        else:
            return
        dead = []
        for writer in tuple(self.clients):
            try:
                writer.write(payload)
                await asyncio.wait_for(writer.drain(), timeout=5)
            except (ConnectionError, OSError, asyncio.TimeoutError):
                dead.append(writer)
        for writer in dead:
            self.clients.discard(writer)
            writer.close()
