"""napple-tvd: Apple TV bridge for the napple-tv Noctalia plugin.

  napple-tvd scan               list Apple TVs on the network
  napple-tvd pair [--host IP]   pick a device, pair Companion + AirPlay, save config
  napple-tvd serve [--port N]   run the HTTP/SSE bridge (what the systemd unit runs)
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import re
import signal
import threading
import traceback
import sys

import pyatv
from pyatv.const import PairingRequirement, Protocol
from pyatv.storage.file_storage import FileStorage

from .config import Config, config_path
from .controller import Controller
from .server import serve

PAIR_PROTOCOLS = (Protocol.Companion, Protocol.AirPlay)
NEEDS_PAIRING = (PairingRequirement.Mandatory, PairingRequirement.Optional)


async def ask(prompt: str = "") -> str:
    """input() without blocking the loop or its shutdown.

    asyncio.to_thread uses the default executor, which asyncio.run() joins on exit,
    so an unanswered prompt would hang shutdown after any error. A daemon thread
    is simply abandoned instead.
    """
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[str] = loop.create_future()

    def deliver(setter, value) -> None:
        if not fut.done():
            setter(value)

    def run() -> None:
        try:
            value = input(prompt)
        except BaseException as exc:  # noqa: BLE001 - EOFError/KeyboardInterrupt go to the awaiter
            loop.call_soon_threadsafe(deliver, fut.set_exception, exc)
        else:
            loop.call_soon_threadsafe(deliver, fut.set_result, value)

    threading.Thread(target=run, daemon=True).start()
    return await fut


async def _scan(host: str | None) -> list[pyatv.interface.BaseConfig]:
    loop = asyncio.get_running_loop()
    confs = await pyatv.scan(loop, hosts=[host] if host else None, timeout=5)
    # Apple TVs offer a pairable Companion service; HomePods (Companion "Unsupported")
    # and AirPlay-only speakers/soundbars can't be driven as a remote.
    def is_tv(c: pyatv.interface.BaseConfig) -> bool:
        svc = c.get_service(Protocol.Companion)
        return svc is not None and svc.pairing not in (PairingRequirement.Unsupported, PairingRequirement.Disabled)

    return [c for c in confs if is_tv(c)]


def _describe(conf: pyatv.interface.BaseConfig) -> str:
    services = ", ".join(
        f"{s.protocol.name}({s.pairing.name})" for s in conf.services if s.protocol in PAIR_PROTOCOLS
    )
    return f"{conf.name}  {conf.address}  {conf.device_info.model_str}  id={conf.identifier}  [{services}]"


async def cmd_scan(args: argparse.Namespace) -> int:
    confs = await _scan(args.host)
    if not confs:
        print("No Apple TVs found.")
        return 1
    for conf in confs:
        print(_describe(conf))
    return 0


async def _pair_one(conf, proto: Protocol, loop, storage, verbose: bool) -> bool:
    """One pairing attempt for one protocol; reports errors instead of raising."""
    handler = await pyatv.pair(conf, proto, loop, storage=storage)
    try:
        await handler.begin()
        if handler.device_provides_pin:
            raw = await ask(f"  {proto.name}: enter the PIN shown on the TV: ")
            digits = "".join(ch for ch in raw if ch.isdigit())
            if not digits:
                print(f"  {proto.name}: no digits entered")
                return False
            handler.pin(int(digits))
        else:
            handler.pin(1234)
            await ask(f"  {proto.name}: enter PIN 1234 on the TV, then press Enter")
        await handler.finish()
        if handler.has_paired:
            print(f"  {proto.name}: paired")
            return True
        print(f"  {proto.name}: device did not accept pairing")
        return False
    except Exception as exc:  # noqa: BLE001 - surface any pairing failure and let the caller retry
        print(f"  {proto.name}: pairing failed: {type(exc).__name__}: {exc or 'no details'}")
        if verbose:
            traceback.print_exc()
        # After a failed attempt the TV rate-limits ("Error=BackOff, BackOff=12s"); honor it.
        if m := re.search(r"BackOff=(\d+)s", str(exc)):
            wait = int(m.group(1)) + 2
            print(f"  {proto.name}: TV asked to back off; waiting {wait}s")
            await asyncio.sleep(wait)
        return False
    finally:
        with contextlib.suppress(Exception):
            await handler.close()


async def cmd_pair(args: argparse.Namespace) -> int:
    loop = asyncio.get_running_loop()
    confs = await _scan(args.host)
    if not confs:
        print("No Apple TVs found. Multicast replies may be firewalled; try --host <ip>.")
        return 1
    if len(confs) == 1:
        conf = confs[0]
    else:
        for i, c in enumerate(confs, 1):
            print(f"{i}) {_describe(c)}")
        choice = await ask("Device number: ")
        conf = confs[int(choice) - 1]
    print(f"Pairing with {conf.name} ({conf.address})")

    storage = FileStorage.default_storage(loop)
    await storage.load()
    # Re-scan with storage so existing credentials are applied and skipped.
    conf = (await pyatv.scan(loop, identifier=conf.identifier, hosts=[str(conf.address)],
                             storage=storage, timeout=5))[0]

    paired_any = False
    for proto in PAIR_PROTOCOLS:
        service = conf.get_service(proto)
        if service is None:
            continue
        if service.pairing not in NEEDS_PAIRING:
            print(f"  {proto.name}: {service.pairing.name}, skipping")
            continue
        if service.credentials and not args.force:
            print(f"  {proto.name}: already paired (use --force to redo)")
            paired_any = True
            continue
        for attempt in range(1, 4):
            if await _pair_one(conf, proto, loop, storage, args.verbose):
                await storage.save()  # persist each protocol as soon as it succeeds
                paired_any = True
                break
            if attempt < 3:
                print(f"  {proto.name}: retrying ({attempt + 1}/3) - a new PIN will appear on the TV")
        else:
            print(f"  {proto.name}: giving up. Re-run with -v for pyatv debug output.")

    if not paired_any:
        return 1

    cfg = Config.load()
    cfg.identifier = conf.identifier
    cfg.name = conf.name
    cfg.host = str(conf.address)  # serve connects by unicast first (works behind ufw)
    print(f"Saved {cfg.save()}  (credentials in pyatv storage)")
    return 0


async def cmd_serve(args: argparse.Namespace) -> int:
    cfg = Config.load()
    if args.port:
        cfg.port = args.port
    if not cfg.identifier and not cfg.host:
        logging.warning("no device in %s yet; run `napple-tvd pair`. Serving anyway.", config_path())
    task = asyncio.create_task(serve(Controller(cfg), cfg.port))
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, task.cancel)
    with contextlib.suppress(asyncio.CancelledError):
        await task
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="napple-tvd", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan", help="list Apple TVs")
    p.add_argument("--host", help="scan a single IP (unicast) instead of multicast")
    p.set_defaults(fn=cmd_scan)

    p = sub.add_parser("pair", help="pair and save device to config")
    p.add_argument("--host", help="device IP, if multicast discovery doesn't find it")
    p.add_argument("--force", action="store_true", help="re-pair protocols that already have credentials")
    p.set_defaults(fn=cmd_pair)

    p = sub.add_parser("serve", help="run the bridge")
    p.add_argument("--port", type=int)
    p.set_defaults(fn=cmd_serve)

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if not args.verbose:
        logging.getLogger("pyatv").setLevel(logging.WARNING)
    try:
        sys.exit(asyncio.run(args.fn(args)))
    except KeyboardInterrupt:
        print("\ninterrupted")
        sys.exit(130)
