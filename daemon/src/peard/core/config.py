from pathlib import Path


from dataclasses import dataclass, field
import tomllib
from typing import List

DEFAULT_DIR_NAME = "peard-remote"
DEFAULT_PORT = 7655

import os


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / DEFAULT_DIR_NAME


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / DEFAULT_DIR_NAME


def config_path() -> Path:
    return config_dir() / "config.toml"


def _q(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass()
class Device:
    identifier: str
    name: str | None = None
    host: str | None = None


@dataclass()
class Config:
    devices: List[Device] = field(default_factory=list)
    active: str | None = None
    port: int = DEFAULT_PORT

    @classmethod
    def load(cls):
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

        return cls(devices=devices, active=active, port=int(data.get("port", DEFAULT_PORT)))

    @property
    def current(self) -> Device | None:
        for d in self.devices:
            if d.identifier == self.active:
                return d

        return self.devices[0] if self.devices else None
            

    def find(self, key: str) -> Device | None:

        # exact match on identifier or name
        for d in self.devices:
            if key in (d.identifier, d.name):
                return d

        # fuzzier matches
        matches = [d for d in self.devices if d.name and d.name.casefold().startswith(key.casefold())]
        return matches[0] if len(matches) == 1 else None

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
