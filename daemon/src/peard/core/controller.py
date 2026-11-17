from dataclasses import dataclass

import pyatv
from peard.core.config import Config
from pyatv.interface import AppleTV

from typing import Any


def _blank_now_playing() -> dict[str, Any]:
    return {
        "state": "idle",
        "title": None,
        "artist": None,
        "album": None,
        "series": None,
        "season": None,
        "episode": None,
        "mediaType": None,
        "position": None,
        "total": None,
        "positionAt": None,
        "app": None,
        "appId": None,
        "artwork": None,
    }


# @dataclass()
# class NowPlaying():
#     album: str = None
#     app: str = None
#     appId: str = None
#     artist: str = None
#     artwork: str = None
#     episode: int = None
#     mediaType: str = None
#     position: int = None
#     positionAt: int = None
#     series: str = None
#     state: str = "idle"
#     title: str = None
#     total: int = None


class Controller:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.atv: AppleTV | None = None
        self._state: dict[str, Any] = {
            "connected": False,
            "device": None,
            "device-id": None,
            "error": None,
            "power": "unknown",
            "volume": None,
            "keyboard": "unknown",
            **_blank_now_playing(),
        }

    async def key(self, name: str, action: str):

        print(f"name: {name}")
        print(f"action: {action}")

    async def state(self) -> dict[str, Any]:
        return dict(self._state)
