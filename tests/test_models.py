import pytest
from pydantic import ValidationError

from serial_gateway.models import GatewayConfig, PortConfig


def port(identifier: str, device: str, telnet_port: int, simulated: bool = False):
    return PortConfig(
        id=identifier,
        name=identifier,
        device=device,
        telnet_port=telnet_port,
        simulated=simulated,
    )


def test_two_independent_ports_are_valid():
    config = GatewayConfig(
        ports=[port("uart0", "/dev/ttyUSB0", 2000), port("uart1", "/dev/ttyUSB1", 2001)]
    )
    assert len(config.ports) == 2
    assert config.ports[0].enabled is True


def test_duplicate_telnet_port_is_rejected():
    with pytest.raises(ValidationError, match="Telnet 端口不能重复"):
        GatewayConfig(
            ports=[port("uart0", "/dev/ttyUSB0", 2000), port("uart1", "/dev/ttyUSB1", 2000)]
        )


def test_duplicate_real_device_is_rejected():
    with pytest.raises(ValidationError, match="真实串口设备不能重复"):
        GatewayConfig(
            ports=[port("uart0", "/dev/ttyUSB0", 2000), port("uart1", "/dev/ttyUSB0", 2001)]
        )


def test_simulated_channels_may_share_placeholder_device():
    config = GatewayConfig(
        ports=[
            port("uart0", "/dev/ttyUSB0", 2000, simulated=True),
            port("uart1", "/dev/ttyUSB0", 2001, simulated=True),
        ]
    )
    assert len(config.ports) == 2
