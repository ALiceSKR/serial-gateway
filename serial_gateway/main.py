import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from serial.tools import list_ports

from .auth import require_user, sessions
from .config import ConfigStore
from .gateway import SerialGateway
from .models import GatewayConfig, GatewayStatus, LoginRequest, SendRequest, SerialDevice
from .telnet import TelnetServer

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("SERIAL_GATEWAY_DATA", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[logging.FileHandler(DATA_DIR / "serial-ai.log"), logging.StreamHandler()],
)


class Runtime:
    def __init__(self) -> None:
        self.websockets: set[WebSocket] = set()
        self.store = ConfigStore(DATA_DIR / "config.json")
        self.config = self.store.load()
        self.gateways: dict[str, SerialGateway] = {}
        self.telnet: dict[str, TelnetServer] = {}

    async def start(self) -> None:
        await self.apply_config(self.config, persist=False)

    async def stop(self) -> None:
        await asyncio.gather(*(server.stop() for server in self.telnet.values()))
        await asyncio.gather(*(gateway.stop() for gateway in self.gateways.values()))
        self.telnet.clear()
        self.gateways.clear()

    async def apply_config(self, config: GatewayConfig, persist: bool = True) -> None:
        previous = self.config
        await self.stop()
        self.config = config
        try:
            await self._start_channels(config)
        except Exception:
            await self.stop()
            self.config = previous
            await self._start_channels(previous)
            raise
        if persist:
            self.store.save(config)

    async def _start_channels(self, config: GatewayConfig) -> None:
        for port in config.ports:
            gateway = SerialGateway(port, self.broadcast)
            server = TelnetServer(gateway.send)
            self.gateways[port.id] = gateway
            self.telnet[port.id] = server
            await gateway.start()
            await server.start(port=port.telnet_port)

    async def set_enabled(self, port_id: str, enabled: bool) -> SerialGateway:
        gateway = self.gateways.get(port_id)
        if gateway is None:
            raise KeyError(port_id)
        if enabled == gateway.settings.enabled:
            return gateway
        if enabled:
            gateway.settings.enabled = True
            await gateway.start()
            await gateway.emit("SYSTEM", "串口已打开")
        else:
            await gateway.emit("SYSTEM", "串口已关闭")
            await gateway.stop()
            gateway.settings.enabled = False
        self.store.save(self.config)
        return gateway

    async def broadcast(self, event: dict) -> None:
        telnet = self.telnet.get(event["port_id"])
        if telnet:
            await telnet.broadcast(event)
        dead = []
        for websocket in tuple(self.websockets):
            try:
                await websocket.send_json(event)
            except RuntimeError:
                dead.append(websocket)
        for websocket in dead:
            self.websockets.discard(websocket)


runtime = Runtime()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await runtime.start()
    yield
    await runtime.stop()


app = FastAPI(title="AI Serial Gateway", version="0.1.0", lifespan=lifespan)


@app.post("/api/login")
async def login(body: LoginRequest, response: Response):
    if not sessions.authenticate(body.username, body.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    response.set_cookie(
        "serial_gateway_session",
        sessions.create(),
        httponly=True,
        samesite="strict",
        max_age=sessions.ttl,
    )
    return {"username": body.username}


@app.post("/api/logout")
async def logout(response: Response):
    response.delete_cookie("serial_gateway_session")
    return {"ok": True}


@app.get("/api/me")
async def me(username: str = Depends(require_user)):
    return {"username": username}


@app.get("/api/settings", response_model=GatewayConfig)
async def get_settings(_: str = Depends(require_user)):
    return runtime.config


@app.get("/api/devices", response_model=list[SerialDevice])
async def get_devices(_: str = Depends(require_user)):
    detected = {}
    for item in list_ports.comports():
        port_name = None
        usb_location = item.location.split(":", 1)[0] if item.location else None
        if item.vid == 0x0403 and item.pid == 0x6011 and item.location:
            try:
                interface_number = int(item.location.rsplit(".", 1)[1])
                if 0 <= interface_number < 26:
                    port_name = f"Port {chr(ord('A') + interface_number)}"
            except (ValueError, IndexError):
                pass
        details = [item.device]
        if port_name:
            details.append(port_name)
        elif item.interface:
            details.append(item.interface)
        if usb_location:
            details.append(f"USB {usb_location}")
        if item.serial_number:
            details.append(f"SN {item.serial_number}")
        detected[item.device] = SerialDevice(
            device=item.device,
            description=item.description or item.device,
            display_name=" · ".join(details),
            serial_number=item.serial_number,
            location=item.location,
            port_name=port_name,
            available=True,
        )
    for port in runtime.config.ports:
        if port.device not in detected:
            detected[port.device] = SerialDevice(
                device=port.device,
                description="已配置（当前未检测到）",
                display_name=f"{port.device} · 已配置（当前未检测到）",
                available=False,
            )
    return sorted(detected.values(), key=lambda item: item.device)


@app.put("/api/settings", response_model=GatewayConfig)
async def put_settings(config: GatewayConfig, _: str = Depends(require_user)):
    try:
        await runtime.apply_config(config)
    except OSError as exc:
        raise HTTPException(status_code=409, detail=f"Telnet 端口监听失败：{exc}") from exc
    return runtime.config


@app.get("/api/status", response_model=list[GatewayStatus])
async def status(_: str = Depends(require_user)):
    return [
        GatewayStatus(
            port_id=port.id,
            enabled=port.enabled,
            serial_connected=runtime.gateways[port.id].connected,
            simulated=port.simulated,
            telnet_clients=len(runtime.telnet[port.id].clients),
            last_error=runtime.gateways[port.id].last_error,
        )
        for port in runtime.config.ports
    ]


@app.post("/api/ports/{port_id}/open")
async def open_port(port_id: str, _: str = Depends(require_user)):
    try:
        gateway = await runtime.set_enabled(port_id, True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="串口通道不存在") from exc
    return {"ok": True, "connected": gateway.connected, "error": gateway.last_error}


@app.post("/api/ports/{port_id}/close")
async def close_port(port_id: str, _: str = Depends(require_user)):
    try:
        await runtime.set_enabled(port_id, False)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="串口通道不存在") from exc
    return {"ok": True, "connected": False}


@app.post("/api/send")
async def send(body: SendRequest, _: str = Depends(require_user)):
    gateway = runtime.gateways.get(body.port_id)
    if not gateway:
        raise HTTPException(status_code=404, detail="串口通道不存在")
    try:
        await gateway.send(body.data, f"{body.source} TX")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True}


@app.websocket("/ws/terminal")
async def terminal(websocket: WebSocket):
    try:
        sessions.validate(websocket.cookies.get("serial_gateway_session"))
    except HTTPException:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    runtime.websockets.add(websocket)
    try:
        await websocket.send_json(
            {"timestamp": "", "port_id": "*", "port_name": "SYSTEM", "source": "SYSTEM", "data": "Web Terminal 已连接"}
        )
        while True:
            message = await websocket.receive_json()
            port_id = message.get("port_id")
            data = message.get("data")
            gateway = runtime.gateways.get(port_id)
            if gateway is None:
                await websocket.send_json(
                    {"timestamp": "", "port_id": port_id or "*", "port_name": "SYSTEM", "source": "ERROR", "data": "串口通道不存在"}
                )
                continue
            if not isinstance(data, str) or not data or len(data) > 65536:
                continue
            try:
                await gateway.send(data, "WEB TX")
            except RuntimeError as exc:
                await websocket.send_json(
                    {"timestamp": "", "port_id": port_id, "port_name": gateway.settings.name, "source": "ERROR", "data": str(exc)}
                )
    except WebSocketDisconnect:
        pass
    finally:
        runtime.websockets.discard(websocket)


DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    async def frontend(path: str):
        candidate = (DIST / path).resolve()
        if path and candidate.is_relative_to(DIST) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")
