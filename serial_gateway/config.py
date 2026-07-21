import json
from pathlib import Path

from .models import GatewayConfig, PortConfig


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> GatewayConfig:
        if not self.path.exists():
            config = GatewayConfig(
                ports=[
                    PortConfig(
                        id="uart0", name="Console UART", device="/dev/ttyUSB0",
                        telnet_port=2000, simulated=True,
                    )
                ]
            )
            self.save(config)
            return config
        return GatewayConfig.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, config: GatewayConfig) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(config.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
