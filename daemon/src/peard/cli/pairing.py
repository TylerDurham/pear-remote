"""Interactive pairing with an Apple TV over the Companion and AirPlay protocols."""

import asyncio
import contextlib
import re
import traceback

import pyatv
from pyatv.const import PairingRequirement, Protocol
from pyatv.interface import BaseConfig, Storage
from peard.cli.utils import async_ask

PAIR_PROTOCOLS = (Protocol.Companion, Protocol.AirPlay)
NEEDS_PAIRING = (PairingRequirement.Mandatory, PairingRequirement.Optional)
MAX_ATTEMPTS = 3


def is_pairable(c: BaseConfig):
    """Simple function that returns `True` if the device can be paired, `False` if not."""
    svc = c.get_service(Protocol.Companion)
    return svc is not None and svc.pairing not in {
        PairingRequirement.Unsupported,
        PairingRequirement.Disabled,
    }


async def pair_device(
    tv: BaseConfig,
    loop: asyncio.AbstractEventLoop,
    storage: Storage,
    force: bool | None = False,
    verbose: bool | None = False,
) -> bool:
    """Pair every protocol in PAIR_PROTOCOLS that needs it, retrying each up to
    MAX_ATTEMPTS times. Credentials are saved to `storage` as each protocol succeeds.

    Returns `True` if at least one protocol is paired (newly or already).
    """
    paired_any = False
    for protocol in PAIR_PROTOCOLS:
        service = tv.get_service(protocol)
        if service is None:
            continue
        if service.pairing not in NEEDS_PAIRING:
            print(f"  {protocol.name}: {service.pairing.name}, skipping")
            continue
        if service.credentials and not force:
            print(f"  {protocol.name}: already paired (use --force to redo)")
            paired_any = True
            continue
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if await pair(tv, protocol, loop, storage, verbose):
                await storage.save()  # persist each protocol as soon as it succeeds
                paired_any = True
                break
            if attempt < MAX_ATTEMPTS:
                print(
                    f"  {protocol.name}: retrying ({attempt + 1}/{MAX_ATTEMPTS})"
                    " - a new PIN will appear on the TV"
                )
        else:
            print(
                f"  {protocol.name}: giving up. Re-run with -v for pyatv debug output."
            )
    return paired_any


async def pair(
    conf: BaseConfig,
    proto: Protocol,
    loop: asyncio.AbstractEventLoop,
    storage: Storage,
    verbose: bool | None = False,
) -> bool:
    """One pairing attempt for one protocol; reports errors instead of raising."""
    handler = await pyatv.pair(conf, proto, loop, storage=storage)
    try:
        await handler.begin()
        if handler.device_provides_pin:
            raw = await async_ask(f"  {proto.name}: enter the PIN shown on the TV: ")
            digits = "".join(ch for ch in raw if ch.isdigit())
            if not digits:
                print(f"  {proto.name}: no digits entered")
                return False

            handler.pin(int(digits))
        else:
            handler.pin(1234)
            await async_ask(
                f"  {proto.name}: enter PIN 1234 on the TV, then press Enter"
            )
        await handler.finish()
        if handler.has_paired:
            print(f"  {proto.name}: paired")
            return True
        print(f"  {proto.name}: device did not accept pairing")
        return False

    except Exception as exc:  # noqa: BLE001 - surface any pairing failure and let the caller retry
        print(
            f"  {proto.name}: pairing failed: {type(exc).__name__}: {exc or 'no details'}"
        )
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
