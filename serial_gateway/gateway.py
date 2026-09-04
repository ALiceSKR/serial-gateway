import asyncio
import codecs
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

import serial
from serial import SerialException

from .models import PortConfig

EventSink = Callable[[dict], Awaitable[None]]


class SerialGateway:
    def __init__(self, settings: PortConfig, event_sink: EventSink) -> None:
        self.settings = settings
        self.event_sink = event_sink
        self.serial: serial.Serial | None = None
        self.reader_task: asyncio.Task | None = None
        self.write_lock = asyncio.Lock()
        self.last_error: str | None = None
        self.logger = logging.getLogger("serial_gateway.events")

    @property
    def connected(self) -> bool:
        return self.settings.enabled and (
            self.settings.simulated or bool(self.serial and self.serial.is_open)
        )

    async def start(self) -> None:
        await self._open()

    async def stop(self) -> None:
        if self.reader_task:
            self.reader_task.cancel()
            await asyncio.gather(self.reader_task, return_exceptions=True)
            self.reader_task = None
        if self.serial and self.serial.is_open:
            self.serial.close()
        self.serial = None

    async def _open(self) -> None:
        self.last_error = None
        if not self.settings.enabled:
            return
        if self.settings.simulated:
            await self.emit("SYSTEM", f"模拟串口已连接：{self.describe()}")
            return
        try:
            self.serial = serial.Serial(
                port=self.settings.device,
                baudrate=self.settings.baudrate,
                bytesize=self.settings.bytesize,
                parity=self.settings.parity,
                stopbits=self.settings.stopbits,
                timeout=0.1,
            )
            self.reader_task = asyncio.create_task(self._read_loop())
            await self.emit("SYSTEM", f"串口已连接：{self.describe()}")
        except (SerialException, OSError) as exc:
            self.last_error = str(exc)
            self.serial = None
            await self.emit("ERROR", f"串口连接失败：{exc}")

    async def _read_loop(self) -> None:
        assert self.serial is not None
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while True:
            try:
                data = await asyncio.to_thread(self.serial.read, 4096)
                if data:
                    decoded = decoder.decode(data)
                    if "\ufffd" in decoded:
                        self.logger.warning(
                            "[%s RAW HEX] %s",
                            self.settings.id,
                            data.hex(" "),
                        )
                    if decoded:
                        await self.emit("UART RX", decoded)
            except (SerialException, OSError) as exc:
                self.last_error = str(exc)
                await self.emit("ERROR", f"串口读取失败：{exc}")
                return

    async def send(self, data: str, source: str) -> None:
        encoded = data.encode("utf-8")
        async with self.write_lock:
            if not self.settings.enabled:
                raise RuntimeError("串口已关闭")
            if self.settings.simulated:
                await self.emit(source, data)
                await asyncio.sleep(0.03)
                await self.emit("UART RX", f"[模拟设备响应] {data}")
                return
            if not self.serial or not self.serial.is_open:
                raise RuntimeError(self.last_error or "串口未连接")
            await asyncio.to_thread(self.serial.write, encoded)
            await asyncio.to_thread(self.serial.flush)
            await self.emit(source, data)

    async def emit(self, source: str, data: str) -> None:
        event = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "port_id": self.settings.id,
            "port_name": self.settings.name,
            "source": source,
            "data": data,
        }
        self.logger.info("[%s]\n%s", source, data.rstrip())
        await self.event_sink(event)

    def describe(self) -> str:
        mode = "（模拟）" if self.settings.simulated else ""
        return (
            f"{self.settings.name} · {self.settings.device} {self.settings.baudrate} "
            f"{self.settings.bytesize}{self.settings.parity}{self.settings.stopbits}{mode}"
        )
