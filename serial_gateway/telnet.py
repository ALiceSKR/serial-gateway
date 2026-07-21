import asyncio
from collections.abc import Awaitable, Callable


class TelnetDecoder:
    """Remove Telnet commands while preserving a byte stream across TCP reads."""

    def __init__(self) -> None:
        self.state = "data"

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
        return bytes(result)


class TelnetServer:
    IAC = 255
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
        try:
            while data := await reader.read(4096):
                clean = decoder.feed(data)
                if clean:
                    await self.send_serial(clean.decode("utf-8", errors="replace"), "HUMAN TX")
        except (ConnectionError, RuntimeError):
            pass
        finally:
            self.clients.discard(writer)
            writer.close()
            await writer.wait_closed()

    @classmethod
    def _strip_negotiation(cls, data: bytes) -> bytes:
        return TelnetDecoder().feed(data)

    async def broadcast(self, event: dict) -> None:
        source = event["source"]
        data = self._telnet_newlines(event["data"])
        if source == "UART RX":
            payload = data.encode()
        else:
            return
        dead = []
        for writer in tuple(self.clients):
            try:
                writer.write(payload)
                await writer.drain()
            except ConnectionError:
                dead.append(writer)
        for writer in dead:
            self.clients.discard(writer)

    @staticmethod
    def _telnet_newlines(data: str) -> str:
        return data.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
