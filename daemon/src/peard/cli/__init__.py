import pyatv
import typer

import asyncio
from pyatv.interface import BaseConfig
from pyatv.storage.file_storage import FileStorage
from functools import wraps
from collections.abc import Callable, Coroutine
from typing import Any, List, Optional, ParamSpec, TypeVar

from rich.table import Table
from rich.console import Console

import threading
from peard.core.appletv import scan

P = ParamSpec("P")
R = TypeVar("R")


def run_async(fn: Callable[P, Coroutine[Any, Any, R]]) -> Callable[P, R]:
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
        except (
            BaseException
        ) as exc:  # noqa: BLE001 - EOFError/KeyboardInterrupt go to the awaiter
            loop.call_soon_threadsafe(deliver, fut.set_exception, exc)
        else:
            loop.call_soon_threadsafe(deliver, fut.set_result, value)

    threading.Thread(target=run, daemon=True).start()
    return await fut


def describe(tvs: List[BaseConfig]):

    if tvs is None or len(tvs) == 0:
        print(
            "No Apple TVs found. Use --hosts <IP Address> to get past multicast firewall issues. You can also open port 5353/udp in your local firewall."
        )
        raise typer.Exit(code=1)

    else:

        tbl = Table()
        tbl.add_column("#")
        tbl.add_column("Name")
        tbl.add_column("Device")
        tbl.add_column("ID")
        tbl.add_column("Address")

        count = 0
        for tv in tvs:
            count = count + 1
            tbl.add_row(
                f"{count}",
                tv.name,
                tv.device_info.model_str,
                tv.identifier,
                f"{tv.address}",
            )

        console.print(tbl)


@app.command(name="pair")
@run_async
async def cmd_pair(
    host: Optional[str] = typer.Option(None, "--host", "-H", help="The host ip address")
):

    loop = asyncio.get_running_loop()
    hosts: List[str] | None = [host] if host is not None else None
    tvs = await scan(hosts=hosts, timeout=5)

    if len(tvs) > 1:
        describe(tvs)
        while True:
            choice = (
                await ask(
                    f"Enter the number of a TV to pair (1-{len(tvs)}, q to quit): "
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
        describe(tvs)
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
    print(f"{tv}")


@app.command(name="scan")
@run_async
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
    \n - you can allow `5353/udp` through your local firewall.
    \n - you can also temporarily disable your local firewall.
    """

    tvs = await scan(hosts=hosts, timeout=timeout)

    describe(tvs)


def main():
    app()
