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


def test_duplicate_network_port_is_rejected():
    with pytest.raises(ValidationError, match="网络端口不能重复"):
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


def test_existing_config_defaults_to_telnet():
    config = port("uart0", "/dev/ttyUSB0", 2000)
    assert config.network_protocol == "telnet"
    assert config.usr_vcom_sync is False


def test_channel_can_select_raw_tcp():
    config = PortConfig(
        id="uart0", name="uart0", device="/dev/ttyUSB0", telnet_port=3000,
        network_protocol="raw_tcp",
    )
    assert config.network_protocol == "raw_tcp"
