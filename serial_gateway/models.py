from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SendRequest(BaseModel):
    port_id: str = Field(min_length=1, max_length=64)
    data: str = Field(min_length=1, max_length=65536)
    source: Literal["AI", "WEB"] = "AI"


class SerialSettings(BaseModel):
    device: str = Field(default="/dev/ttyUSB0", min_length=1, max_length=512)
    baudrate: int = Field(default=115200, ge=50, le=4_000_000)
    bytesize: Literal[5, 6, 7, 8] = 8
    parity: Literal["N", "E", "O", "M", "S"] = "N"
    stopbits: Literal[1, 1.5, 2] = 1
    simulated: bool = True
    enabled: bool = True

    @field_validator("device")
    @classmethod
    def validate_device(cls, value: str) -> str:
        if not value.startswith("/dev/"):
            raise ValueError("串口设备必须位于 /dev/ 下")
        return value


class PortConfig(SerialSettings):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    telnet_port: int = Field(ge=1024, le=65535)


class GatewayConfig(BaseModel):
    ports: list[PortConfig] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_values(self):
        ids = [port.id for port in self.ports]
        devices = [port.device for port in self.ports if not port.simulated]
        telnet_ports = [port.telnet_port for port in self.ports]
        if len(ids) != len(set(ids)):
            raise ValueError("通道 ID 不能重复")
        if len(devices) != len(set(devices)):
            raise ValueError("真实串口设备不能重复")
        if len(telnet_ports) != len(set(telnet_ports)):
            raise ValueError("Telnet 端口不能重复")
        return self


class GatewayStatus(BaseModel):
    port_id: str
    enabled: bool
    serial_connected: bool
    simulated: bool
    telnet_clients: int
    last_error: str | None = None


class SerialDevice(BaseModel):
    device: str
    description: str
    display_name: str
    serial_number: str | None = None
    location: str | None = None
    port_name: str | None = None
    available: bool = True
