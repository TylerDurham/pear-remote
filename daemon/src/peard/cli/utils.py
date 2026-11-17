import asyncio
import threading
from rich.console import Console
import typer
from rich.table import Table
import asyncio
from pyatv.interface import BaseConfig
from typing import List


async def async_ask(prompt: str = "") -> str:
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
            value = typer.prompt(prompt)
        except (
            BaseException
        ) as exc:  # noqa: BLE001 - EOFError/KeyboardInterrupt go to the awaiter
            loop.call_soon_threadsafe(deliver, fut.set_exception, exc)
        else:
            loop.call_soon_threadsafe(deliver, fut.set_result, value)

    threading.Thread(target=run, daemon=True).start()

    return await fut


def msg_no_devices():
    """Print a message that no devices were found during a `scan` or `pair` operation."""
    print(
        "No Apple TVs found. Use --hosts <IP Address> to get past multicast firewall issues. You can also open port 5353/udp in your local firewall."
    )
    raise typer.Exit(code=1)


def msg_devices(console: Console, tvs: List[BaseConfig]):
    """
    Display a list of devices.
    """

    if tvs is None or len(tvs) == 0:
        msg_no_devices()
        return

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
