import pyatv
from pyatv.const import  Protocol
import typer

import asyncio
from pyatv.interface import BaseConfig
from pyatv.storage.file_storage import FileStorage
from functools import wraps
from collections.abc import Callable, Coroutine
from typing import Any, List, Optional, ParamSpec, TypeVar

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from peard.core.config import Config, Device
from peard.cli.pairing import pair_device, is_pairable
from peard.cli.utils import async_ask, msg_devices, msg_no_devices

P = ParamSpec("P")
R = TypeVar("R")


def async_command(fn: Callable[P, Coroutine[Any, Any, R]]) -> Callable[P, R]:
    """
    We are using Typer, which does not support async commands. This
    is a workaround.
    """

    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        """Keeps the signature so Typer still sees the params/annotations"""
        return asyncio.run(fn(*args, **kwargs))

    return wrapper


console = Console()
app = typer.Typer(rich_markup_mode="markdown")


async def scan_apple_tvs(hosts: List[str] | None, timeout: int = 5) -> List[BaseConfig]:
    """Scan for devices (with a spinner) and keep only pairable Apple TVs."""
    loop = asyncio.get_running_loop()
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(description="Scanning for devices...", total=None)
        found = await pyatv.scan(
            loop,
            hosts=hosts,
            timeout=timeout,
            protocol={Protocol.AirPlay, Protocol.Companion, Protocol.MRP},
        )
    return [tv for tv in found if is_pairable(tv)]



@app.command(name="pair")
@async_command
async def cmd_pair(
    host: Optional[str] = typer.Option(
        None, "--host", "-H", help="The host ip address"
    ),
    force: Optional[bool] = typer.Option(False, "--force", "-f"),
    verbose: Optional[bool] = typer.Option(False, "--verbose", "-v"),
):

    loop = asyncio.get_running_loop()
    hosts: List[str] | None = [host] if host is not None else None
    tvs = await scan_apple_tvs(hosts=hosts, timeout=5)

    if len(tvs) > 1:
        msg_devices(console, tvs)
        while True:
            choice = (
                await async_ask(
                    f"Enter the number of a TV to pair (1-{len(tvs)}, q to quit)"
                )
            ).strip()
            if choice.lower() in ("q", "quit"):
                raise typer.Exit(code=1)
            if choice.isdigit() and 1 <= int(choice) <= len(tvs):
                tv = tvs[int(choice) - 1]
                break
            print(f"Invalid choice {choice!r}: enter a number from 1 to {len(tvs)}.")

    elif len(tvs) == 1:
        tv = tvs[0]
    else:
        msg_no_devices()
        return

    print(f"Pairing with {tv.name} ({tv.address})")

    storage = FileStorage.default_storage(loop)
    await storage.load()

    found = await pyatv.scan(
        loop,
        identifier=tv.identifier,
        hosts=[str(tv.address)],
        storage=storage,
        timeout=5,
    )
    if not found:
        print(
            f"{tv.name} ({tv.address}) stopped responding. Make sure it is awake and try again."
        )
        raise typer.Exit(code=1)

    tv = found[0]

    config = Config.load()
    paired_any = await pair_device(tv, loop, storage, force, verbose)

    if not paired_any:
        return 1

    print(f"Saving config for:")
    print(f"{tv}")

    dev = config.find(str(tv.identifier))
    if dev is None:
        config.devices.append(
            Device(name=tv.name, identifier=str(tv.identifier), host=str(tv.address))
        )
        config.save()


@app.command(name="scan")
@async_command
async def cmd_scan(
    hosts: Optional[List[str]] = typer.Option(
        None, "--hosts", "-H", help="One or more host ip addresses"
    ),
    timeout: int = typer.Option(
        5, "--timeout", "-t", help="The timeout for the operation"
    ),
):
    """
    Scans the network for compatible devices. If you don't see devices, try the following:
     - you can allow `5353/udp` through your local firewall.
     - you can also temporarily disable your local firewall.
    """

    tvs = await scan_apple_tvs(hosts=hosts, timeout=timeout)
    if not tvs:
        msg_no_devices()
    else:
        msg_devices(console, tvs)


@app.command(name="serve")
@async_command
async def cmd_serve():
    pass


def main():
    app()
