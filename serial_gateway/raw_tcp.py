import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .telnet import TelnetServer

ApplySettings = Callable[[int, int, str, int], Awaitable[None]]


@dataclass(frozen=True)
class UsrSerialSettings:
    baudrate: int
    bytesize: int
    parity: str
    stopbits: int


class UsrVcomParser:
    """Remove valid USR 'RFC2217-like' frames from a byte stream."""

    HEADER = b"\x55\xaa\x55"

    def __init__(self) -> None:
        self.buffer = bytearray()

    @staticmethod
    def _decode(frame: bytes) -> UsrSerialSettings | None:
        if len(frame) != 8 or frame[:3] != UsrVcomParser.HEADER:
            return None
        if sum(frame[3:7]) & 0xFF != frame[7]:
            return None
        baudrate = int.from_bytes(frame[3:6], "big")
        config = frame[6] & 0x3F  # Older VCOM releases also set reserved bit 7.
        if not 50 <= baudrate <= 4_000_000:
            return None
        bytesize = 5 + (config & 0x03)
        stopbits = 2 if config & 0x04 else 1
        if config & 0x08:
            parity = ("O", "E", "M", "S")[(config >> 4) & 0x03]
        else:
            parity = "N"
        return UsrSerialSettings(baudrate, bytesize, parity, stopbits)

    def feed(self, data: bytes) -> list[bytes | UsrSerialSettings]:
        self.buffer.extend(data)
        events: list[bytes | UsrSerialSettings] = []
        plain = bytearray()
        while self.buffer:
            index = self.buffer.find(self.HEADER)
            if index < 0:
                if self.buffer.endswith(self.HEADER[:2]):
                    keep = 2
                elif self.buffer.endswith(self.HEADER[:1]):
                    keep = 1
                else:
                    keep = 0
                split = len(self.buffer) - keep
                plain.extend(self.buffer[:split])
                del self.buffer[:split]
                break
            plain.extend(self.buffer[:index])
            del self.buffer[:index]
            if len(self.buffer) < 8:
                break
            settings = self._decode(bytes(self.buffer[:8]))
            if settings is None:
                plain.append(self.buffer.pop(0))
                continue
            if plain:
                events.append(bytes(plain))
                plain.clear()
            events.append(settings)
            del self.buffer[:8]
        if plain:
            events.append(bytes(plain))
        return events

    def flush(self) -> bytes:
        remaining = bytes(self.buffer)
        self.buffer.clear()
        return remaining


class RawTcpServer:
    """Expose one serial channel as an unmodified TCP byte stream."""

    def __init__(
        self,
        send_serial: Callable[[bytes, str], Awaitable[None]],
        apply_settings: ApplySettings | None = None,
    ) -> None:
        self.send_serial = send_serial
        self.apply_settings = apply_settings
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
        TelnetServer._configure_keepalive(writer)
        self.clients.add(writer)
        parser = UsrVcomParser() if self.apply_settings else None
        try:
            while data := await reader.read(4096):
                events = parser.feed(data) if parser else [data]
                for event in events:
                    if isinstance(event, UsrSerialSettings):
                        assert self.apply_settings is not None
                        await self.apply_settings(
                            event.baudrate, event.bytesize, event.parity, event.stopbits
                        )
                    elif event:
                        await self.send_serial(event, "RAW TCP TX")
            if parser and (remaining := parser.flush()):
                await self.send_serial(remaining, "RAW TCP TX")
        except (ConnectionError, RuntimeError):
            pass
        finally:
            self.clients.discard(writer)
            writer.close()
            await writer.wait_closed()

    async def broadcast(self, data: bytes) -> None:
        dead = []
        for writer in tuple(self.clients):
            try:
                writer.write(data)
                await asyncio.wait_for(writer.drain(), timeout=5)
            except (ConnectionError, OSError, asyncio.TimeoutError):
                dead.append(writer)
        for writer in dead:
            self.clients.discard(writer)
            writer.close()
