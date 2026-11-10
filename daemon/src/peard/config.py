"""Daemon configuration: ~/.config/pear-remote/config.toml.

port   = 7655                 # HTTP port on 127.0.0.1
active = "BA:12:7D:02:43:7F"  # identifier of the TV to control

[[devices]]                   # one per paired Apple TV (added by `peard pair`)
identifier = "BA:12:7D:02:43:7F"
name       = "Sydney's Room (2)"
host       = "192.168.1.157"  # connect by unicast first; multicast fallback

The old single-device layout (top-level identifier/name/host) is still read and
is rewritten in this form on the next save.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PORT = 7655


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "pear-remote"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "pear-remote"


def config_path() -> Path:
    return config_dir() / "config.toml"


def _q(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class Device:
    identifier: str
    name: str | None = None
    host: str | None = None

    def as_json(self) -> dict[str, str | None]:
        return {"id": self.identifier, "name": self.name or self.identifier, "host": self.host}


@dataclass
class Config:
    devices: list[Device] = field(default_factory=list)
    active: str | None = None
    port: int = DEFAULT_PORT

    @classmethod
    def load(cls) -> Config:
        path = config_path()
        if not path.exists():
            return cls()
        data = tomllib.loads(path.read_text())
        devices = [
            Device(str(d["identifier"]), d.get("name"), d.get("host"))
            for d in data.get("devices", [])
            if d.get("identifier")
        ]
        active = data.get("active")
        if data.get("identifier"):  # legacy single-device layout
            legacy = Device(str(data["identifier"]), data.get("name"), data.get("host"))
            if not any(d.identifier == legacy.identifier for d in devices):
                devices.insert(0, legacy)
            active = active or legacy.identifier
        return cls(devices=devices, active=active, port=int(data.get("port", DEFAULT_PORT)))

    @property
    def current(self) -> Device | None:
        for d in self.devices:
            if d.identifier == self.active:
                return d
        return self.devices[0] if self.devices else None

    def find(self, key: str) -> Device | None:
        """Look up by identifier, exact name, or unambiguous case-insensitive name prefix."""
        for d in self.devices:
            if key in (d.identifier, d.name):
                return d
        matches = [d for d in self.devices if d.name and d.name.casefold().startswith(key.casefold())]
        return matches[0] if len(matches) == 1 else None

    def upsert(self, device: Device) -> None:
        for i, d in enumerate(self.devices):
            if d.identifier == device.identifier:
                self.devices[i] = device
                return
        self.devices.append(device)

    def save(self) -> Path:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"port = {self.port}"]
        if self.active:
            lines.append(f"active = {_q(self.active)}")
        for d in self.devices:
            lines += ["", "[[devices]]", f"identifier = {_q(d.identifier)}"]
            if d.name:
                lines.append(f"name = {_q(d.name)}")
            if d.host:
                lines.append(f"host = {_q(d.host)}")
        path.write_text("\n".join(lines) + "\n")
        return path
