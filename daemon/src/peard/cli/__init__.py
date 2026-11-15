import time

import pyatv
import typer

import asyncio
from functools import wraps
from collections.abc import Callable, Coroutine
from typing import Any, List, Optional, ParamSpec, TypeVar

from rich.table import Table
from rich.console import Console

import peard
from peard.core.appletv import scan

P = ParamSpec("P")
R = TypeVar("R")

console = Console()


def run_async(fn: Callable[P, Coroutine[Any, Any, R]]) -> Callable[P, R]:
    @wraps(fn)  # keeps the signature so Typer still sees the params/annotations
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return asyncio.run(fn(*args, **kwargs))

    return wrapper


app = typer.Typer(rich_markup_mode="markdown")


def describe(tvs: List[pyatv.interface.BaseConfig]):

    tbl = Table()
    tbl.add_column("Name")
    tbl.add_column("Device")
    tbl.add_column("ID")
    tbl.add_column("Address")

    for tv in tvs:
        tbl.add_row(tv.name, tv.device_info.model_str, tv.identifier, f"{tv.address}")

    console.print(tbl)


@app.command(name="pair")
@run_async
async def cmd_pair(
    host: Optional[str] = typer.Option(None, "--host", "-H", help="The host ip address")
):
    pass


@app.command(name="scan")
@run_async
async def cmd_scan(
    hosts: Optional[List[str]] = typer.Option(
        None, "--hosts", "-H", help="One or more host ip addresses"
    ),
    timeout: Optional[int] = typer.Option(
        5, "--timeout", "-t", help="The timeout for the operation"
    ),
):
    """
    Scans the network for compatible devices. If you don't see devices, try the following:
    \n - you can allow `5353/udp` through your local firewall.
    \n - you can also temporarily disable your local firewall.
    """

    tvs = await scan(hosts=hosts, timeout=timeout)
    if tvs is None or len(tvs) == 0:
        print(
            "No Apple TVs found. Use --hosts <IP Address> to get past multicast firewall issues. You can also open port 5353/udp in your local firewall."
        )
        raise typer.Exit(code=1)

    describe(tvs)


def main():
    app()
