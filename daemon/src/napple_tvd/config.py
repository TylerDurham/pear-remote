"""Daemon configuration: ~/.config/napple-tv/config.toml.

identifier = "AA:BB:CC:DD:EE:FF"   # any pyatv identifier of the device
name       = "Living Room"         # display only
host       = "192.168.1.20"        # optional; skips multicast discovery
port       = 7655                  # HTTP port on 127.0.0.1
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORT = 7655


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "napple-tv"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "napple-tv"


def config_path() -> Path:
    return config_dir() / "config.toml"


@dataclass
class Config:
    identifier: str | None = None
    name: str | None = None
    host: str | None = None
    port: int = DEFAULT_PORT

    @classmethod
    def load(cls) -> Config:
        path = config_path()
        if not path.exists():
            return cls()
        data = tomllib.loads(path.read_text())
        return cls(
            identifier=data.get("identifier"),
            name=data.get("name"),
            host=data.get("host"),
            port=int(data.get("port", DEFAULT_PORT)),
        )

    def save(self) -> Path:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for key in ("identifier", "name", "host"):
            value = getattr(self, key)
            if value:
                escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'{key} = "{escaped}"')
        lines.append(f"port = {self.port}")
        path.write_text("\n".join(lines) + "\n")
        return path
