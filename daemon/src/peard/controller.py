"""Long-lived pyatv connection, state snapshot, and command dispatch."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import logging
import time
from typing import Any

import pyatv
from pyatv.const import FeatureName, FeatureState, InputAction, PowerState
from pyatv.interface import (
    AppleTV,
    AudioListener,
    DeviceListener,
    KeyboardListener,
    Playing,
    PowerListener,
    PushListener,
)
from pyatv.storage.file_storage import FileStorage

from .config import Config, cache_dir

log = logging.getLogger(__name__)

# Commands on atv.remote_control that the HTTP API exposes as /key/<name>.
REMOTE_KEYS = frozenset(
    {
        "up", "down", "left", "right", "select", "menu", "home", "home_hold",
        "top_menu", "control_center", "play_pause", "play", "pause", "stop",
        "next", "previous", "skip_forward", "skip_backward", "screensaver",
        "channel_up", "channel_down", "guide",
    }
)
AUDIO_KEYS = frozenset({"volume_up", "volume_down"})
STABLE_AFTER_S = 30  # a connection this old resets the reconnect backoff

ACTIONS = {"tap": InputAction.SingleTap, "double": InputAction.DoubleTap, "hold": InputAction.Hold}

FEATURES = {
    "volume": (FeatureName.VolumeUp,),
    "setVolume": (FeatureName.SetVolume,),
    "keyboard": (FeatureName.TextSet,),
    "apps": (FeatureName.AppList, FeatureName.LaunchApp),
    "power": (FeatureName.TurnOn, FeatureName.TurnOff),
    "seek": (FeatureName.SetPosition,),
}


class NotConnected(Exception):
    pass


class UnknownCommand(Exception):
    pass


def _blank_playing() -> dict[str, Any]:
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


class Hub:
    """Fan-out of state snapshots to SSE clients; slow clients only see the latest."""

    def __init__(self) -> None:
        self._subs: set[asyncio.Queue[dict[str, Any] | None]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any] | None]:
        q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=1)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any] | None]) -> None:
        self._subs.discard(q)

    def publish(self, item: dict[str, Any] | None) -> None:
        for q in self._subs:
            if q.full():
                q.get_nowait()
            q.put_nowait(item)

    def close(self) -> None:
        self.publish(None)


class Controller(PushListener, PowerListener, AudioListener, KeyboardListener, DeviceListener):
    def __init__(self, config: Config) -> None:
        self.config = config
        self.hub = Hub()
        self.atv: AppleTV | None = None
        current = config.current
        self.state: dict[str, Any] = {
            "connected": False,
            "device": current.name if current else None,
            "deviceId": current.identifier if current else None,
            "error": None,
            "power": "unknown",
            "volume": None,
            "keyboard": "unknown",
            "features": {k: False for k in FEATURES},
            **_blank_playing(),
        }
        self._storage: FileStorage | None = None
        # Set when the connection drops or a device switch is requested.
        self._wake = asyncio.Event()
        self._switch = False
        self._artwork_id: str | None = None
        self._artwork_task: asyncio.Task[None] | None = None
        self._apps: list[dict[str, str]] | None = None
        self._kb_lock = asyncio.Lock()
        self._kb_latest: str | None = None
        self._art_dir = cache_dir()

    # ── state ────────────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        return dict(self.state, features=dict(self.state["features"]))

    def _set(self, **changes: Any) -> None:
        changed = False
        for key, value in changes.items():
            if self.state.get(key) != value:
                self.state[key] = value
                changed = True
        if changed:
            self.hub.publish(self.snapshot())

    def _features(self) -> dict[str, bool]:
        atv = self.atv
        if atv is None:
            return {k: False for k in FEATURES}
        return {
            key: atv.features.in_state(FeatureState.Available, *names)
            for key, names in FEATURES.items()
        }

    # ── connection lifecycle ─────────────────────────────────────────────────

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        self._storage = FileStorage.default_storage(loop)
        backoff = 2.0
        while True:
            self._switch = False
            try:
                await self._connect()
                started = time.monotonic()
                if not self._switch:  # a switch may have been requested mid-connect
                    await self._wake.wait()
                if not self._switch:
                    lasted = time.monotonic() - started
                    if lasted >= STABLE_AFTER_S:
                        backoff = 2.0
                    else:
                        # Dropped right away: commonly a second client using the same
                        # pairing (another peard) and the TV kicking one of them.
                        log.warning("connection dropped after %.0fs; is another peard "
                                    "connected to this TV?", lasted)
                    log.warning("connection to Apple TV ended; reconnecting in %.0fs", backoff)
            except asyncio.CancelledError:
                await self._teardown()
                raise
            except Exception as exc:  # noqa: BLE001 - keep retrying whatever went wrong
                log.warning("connect failed: %s", exc)
                self._set(connected=False, error=str(exc) or type(exc).__name__)
            await self._teardown()
            if self._switch:
                backoff = 2.0
                continue  # reconnect to the newly selected TV right away
            # Back off, but let a device switch cut the wait short.
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), backoff)
            backoff = min(backoff * 2, 60.0)

    async def _connect(self) -> None:
        # Re-read each attempt: picks up `peard pair` / `use` done while running.
        self.config = Config.load()
        dev = self.config.current
        if dev is None:
            raise RuntimeError("no Apple TV configured; run `peard pair`")
        self._set(device=dev.name, deviceId=dev.identifier)
        loop = asyncio.get_running_loop()
        await self._storage.load()  # credentials may have been added by `peard pair`
        confs = []
        if dev.host:
            # Unicast first: needs no multicast replies, so it works behind a firewall.
            confs = await pyatv.scan(loop, hosts=[dev.host], storage=self._storage, timeout=5)
            confs = [c for c in confs if dev.identifier in c.all_identifiers]
        if not confs:
            # IP changed (DHCP)? Fall back to multicast discovery by identifier.
            confs = await pyatv.scan(loop, identifier=dev.identifier, storage=self._storage, timeout=5)
        if not confs:
            raise LookupError(f"{dev.name or dev.identifier} not found (host={dev.host}); "
                              "re-run `peard pair --host <ip>`")
        conf = confs[0]
        log.info("connecting to %s (%s)", conf.name, conf.address)
        atv = await pyatv.connect(conf, loop, storage=self._storage)
        self.atv = atv
        self._wake.clear()  # drop close callbacks from the previous connection

        atv.listener = self
        atv.push_updater.listener = self
        atv.power.listener = self
        atv.audio.listener = self
        atv.keyboard.listener = self
        atv.push_updater.start()

        features = self._features()
        self._set(
            connected=True,
            error=None,
            features=features,
            power=self._safe(lambda: atv.power.power_state.name.lower(), "unknown"),
            volume=self._safe(lambda: round(atv.audio.volume), None) if features["setVolume"] else None,
            keyboard=self._safe(lambda: atv.keyboard.text_focus_state.name.lower(), "unknown"),
        )
        log.info("connected to %s", conf.name)

    async def _teardown(self) -> None:
        atv, self.atv = self.atv, None
        if self._artwork_task:
            self._artwork_task.cancel()
            self._artwork_task = None
        self._artwork_id = None
        self._apps = None
        if atv is not None:
            with contextlib.suppress(Exception):
                atv.push_updater.stop()
            with contextlib.suppress(Exception):
                pending = atv.close()
                if pending:
                    await asyncio.wait(pending, timeout=5)
        self._set(connected=False, power="unknown", volume=None, keyboard="unknown",
                  features={k: False for k in FEATURES}, **_blank_playing())

    @staticmethod
    def _safe(fn: Any, default: Any) -> Any:
        try:
            return fn()
        except Exception:  # noqa: BLE001 - feature reads raise when unsupported
            return default

    # ── pyatv listeners ──────────────────────────────────────────────────────

    def playstatus_update(self, updater: Any, playstatus: Playing) -> None:
        atv = self.atv
        if atv is None:
            return
        app = self._safe(lambda: atv.metadata.app, None)
        self._set(
            state=playstatus.device_state.name.lower(),
            title=playstatus.title,
            artist=playstatus.artist,
            album=playstatus.album,
            series=playstatus.series_name,
            season=playstatus.season_number,
            episode=playstatus.episode_number,
            mediaType=playstatus.media_type.name.lower(),
            position=playstatus.position,
            total=playstatus.total_time,
            positionAt=int(time.time() * 1000),
            app=app.name if app else None,
            appId=app.identifier if app else None,
            features=self._features(),
        )
        self._refresh_artwork()

    def playstatus_error(self, updater: Any, exception: Exception) -> None:
        log.warning("push update error: %s", exception)

    def powerstate_update(self, old_state: PowerState, new_state: PowerState) -> None:
        self._set(power=new_state.name.lower())

    def volume_update(self, old_level: float, new_level: float) -> None:
        self._set(volume=round(new_level))

    def volume_device_update(self, output_device: Any, old_level: float, new_level: float) -> None:
        pass

    def outputdevices_update(self, old_devices: Any, new_devices: Any) -> None:
        pass

    def focusstate_update(self, old_state: Any, new_state: Any) -> None:
        self._set(keyboard=new_state.name.lower())

    def connection_lost(self, exception: Exception) -> None:
        self._set(error=str(exception) or "connection lost")
        self._wake.set()

    def connection_closed(self) -> None:
        self._wake.set()

    # ── artwork ──────────────────────────────────────────────────────────────

    def _refresh_artwork(self) -> None:
        atv = self.atv
        if atv is None:
            return
        art_id = self._safe(lambda: atv.metadata.artwork_id, None)
        if art_id == self._artwork_id:
            return
        self._artwork_id = art_id
        if self._artwork_task:
            self._artwork_task.cancel()
        self._artwork_task = asyncio.create_task(self._fetch_artwork(atv, art_id))

    async def _fetch_artwork(self, atv: AppleTV, art_id: str | None) -> None:
        path_str = None
        try:
            art = await atv.metadata.artwork(width=256) if art_id else None
            if art and art.bytes:
                ext = "png" if "png" in (art.mimetype or "") else "jpg"
                digest = hashlib.sha1(art_id.encode() if art_id else art.bytes).hexdigest()[:16]
                self._art_dir.mkdir(parents=True, exist_ok=True)
                path = self._art_dir / f"artwork-{digest}.{ext}"
                path.write_bytes(art.bytes)
                path_str = str(path)
                for old in self._art_dir.glob("artwork-*"):
                    if old != path:
                        old.unlink(missing_ok=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.debug("artwork fetch failed: %s", exc)
        self._set(artwork=path_str)

    # ── devices ──────────────────────────────────────────────────────────────

    def devices(self) -> dict[str, Any]:
        cfg = Config.load()
        current = cfg.current
        return {
            "active": current.identifier if current else None,
            "devices": [d.as_json() for d in cfg.devices],
        }

    async def select_device(self, key: str) -> dict[str, Any]:
        """Make a paired TV the active one and reconnect to it (persisted in config)."""
        cfg = Config.load()
        dev = cfg.find(key)
        if dev is None:
            raise UnknownCommand(f"no paired device matches {key!r}; run `peard pair --host <ip>`")
        if cfg.active != dev.identifier:
            cfg.active = dev.identifier
            cfg.save()
        if not (self.state.get("deviceId") == dev.identifier and self.atv is not None):
            log.info("switching to %s", dev.name or dev.identifier)
            self._switch = True
            self._set(device=dev.name, deviceId=dev.identifier, error=None)
            self._wake.set()
        return dev.as_json()

    # ── commands ─────────────────────────────────────────────────────────────

    def _require(self) -> AppleTV:
        if self.atv is None:
            raise NotConnected(self.state.get("error") or "not connected to Apple TV")
        return self.atv

    async def key(self, name: str, action: str | None = None) -> None:
        atv = self._require()
        if name in REMOTE_KEYS:
            fn = getattr(atv.remote_control, name)
        elif name in AUDIO_KEYS:
            fn = getattr(atv.audio, name)
        else:
            raise UnknownCommand(f"unknown key: {name}")
        kwargs = {}
        if action:
            if action not in ACTIONS:
                raise UnknownCommand(f"unknown action: {action}")
            if "action" not in inspect.signature(fn).parameters:
                raise UnknownCommand(f"{name} does not take an action")
            kwargs["action"] = ACTIONS[action]
        await fn(**kwargs)

    async def set_volume(self, level: float) -> None:
        await self._require().audio.set_volume(max(0.0, min(100.0, float(level))))

    async def set_position(self, seconds: int) -> None:
        await self._require().remote_control.set_position(max(0, int(seconds)))

    async def power(self, op: str) -> None:
        atv = self._require()
        if op == "toggle":
            op = "off" if atv.power.power_state == PowerState.On else "on"
        if op == "on":
            await atv.power.turn_on()
        elif op == "off":
            await atv.power.turn_off()
        else:
            raise UnknownCommand(f"unknown power op: {op}")

    async def keyboard(self, op: str, text: str = "") -> None:
        atv = self._require()
        if op == "set":
            # Latest wins: a burst of keystrokes collapses to the newest text.
            self._kb_latest = text
            async with self._kb_lock:
                if self._kb_latest != text:
                    return
                await atv.keyboard.text_set(text)
        elif op == "append":
            await atv.keyboard.text_append(text)
        elif op == "clear":
            self._kb_latest = ""
            await atv.keyboard.text_clear()
        else:
            raise UnknownCommand(f"unknown keyboard op: {op}")

    async def apps(self, refresh: bool = False) -> list[dict[str, str]]:
        atv = self._require()
        if self._apps is None or refresh:
            apps = await atv.apps.app_list()
            self._apps = sorted(
                ({"name": a.name or a.identifier, "id": a.identifier} for a in apps),
                key=lambda a: a["name"].casefold(),
            )
        return self._apps

    async def launch(self, bundle_id: str) -> None:
        await self._require().apps.launch_app(bundle_id)
