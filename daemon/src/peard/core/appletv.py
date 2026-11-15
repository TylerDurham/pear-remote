
from __future__ import annotations
import asyncio
from typing import List
import pyatv
from pyatv.const import Protocol
from pyatv.const import PairingRequirement, Protocol

async def scan(hosts: List[str] | None, timeout: int = 5) -> list[pyatv.interface.BaseConfig]:

    loop = asyncio.get_running_loop()
    tvs = await pyatv.scan(loop=loop, hosts=hosts, timeout=timeout, protocol={Protocol.AirPlay, Protocol.Companion, Protocol.MRP})

    def is_atv(c: pyatv.interface.BaseConfig):
        svc = c.get_service(Protocol.Companion)
        return svc is not None and svc.pairing not in (PairingRequirement.Unsupported, PairingRequirement.Disabled)


    return [tv for tv in tvs if is_atv(tv)]


