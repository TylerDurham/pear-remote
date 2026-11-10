"""Local HTTP + SSE API consumed by the Noctalia plugin.

GET  /health                     liveness
GET  /state                      current snapshot
GET  /events                     SSE stream of snapshots (one `data:` line each)
POST /key/<name>[?action=hold]   remote button (up, select, menu, home, play_pause, volume_up, ...)
POST /volume        {"level": 0-100}
POST /position      {"seconds": n}
POST /power/<on|off|toggle>
POST /keyboard/<set|append|clear>  {"text": "..."}
GET  /apps[?refresh=1]
POST /launch        {"id": "com.apple.TVWatchList"}

Bound to 127.0.0.1. POSTs must carry `X-Napple: 1` (a custom header forces a CORS
preflight that is never answered, so web pages can't drive the TV) and the Host
header must be loopback (blocks DNS rebinding).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from aiohttp import web
from pyatv import exceptions as atv_exc
from yarl import URL

from .controller import Controller, NotConnected, UnknownCommand

log = logging.getLogger(__name__)

CONTROLLER = web.AppKey("controller", Controller)
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
HEARTBEAT_S = 15


def _err(status: int, message: str) -> web.Response:
    return web.json_response({"error": message}, status=status)


@web.middleware
async def guard(request: web.Request, handler: Any) -> web.StreamResponse:
    try:
        host = URL(f"http://{request.host}").host
    except ValueError:
        host = None
    if host not in ALLOWED_HOSTS:
        return _err(403, "bad host")
    if request.method != "GET" and request.headers.get("X-Napple") != "1":
        return _err(403, "missing X-Napple header")
    try:
        return await handler(request)
    except NotConnected as exc:
        return _err(503, str(exc))
    except UnknownCommand as exc:
        return _err(404, str(exc))
    except (atv_exc.NotSupportedError, atv_exc.CommandError) as exc:
        return _err(409, str(exc) or type(exc).__name__)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        return _err(400, f"bad request: {exc}")
    except web.HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("command failed")
        return _err(502, str(exc) or type(exc).__name__)


async def _body(request: web.Request) -> dict[str, Any]:
    if not request.can_read_body:
        return {}
    text = await request.text()
    return json.loads(text) if text.strip() else {}


def _ctl(request: web.Request) -> Controller:
    return request.app[CONTROLLER]


async def health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "connected": _ctl(request).state["connected"]})


async def state(request: web.Request) -> web.Response:
    return web.json_response(_ctl(request).snapshot())


async def events(request: web.Request) -> web.StreamResponse:
    ctl = _ctl(request)
    resp = web.StreamResponse(
        headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"}
    )
    await resp.prepare(request)
    queue = ctl.hub.subscribe()

    async def send(snap: dict[str, Any]) -> None:
        await resp.write(f"data: {json.dumps(snap, separators=(',', ':'))}\n\n".encode())

    try:
        await send(ctl.snapshot())
        while True:
            try:
                snap = await asyncio.wait_for(queue.get(), HEARTBEAT_S)
            except TimeoutError:
                await resp.write(b": ping\n\n")
                continue
            if snap is None:  # shutting down
                break
            await send(snap)
    except (ConnectionResetError, ConnectionError):
        pass
    finally:
        ctl.hub.unsubscribe(queue)
    return resp


async def key(request: web.Request) -> web.Response:
    await _ctl(request).key(request.match_info["name"], request.query.get("action"))
    return web.Response(status=204)


async def volume(request: web.Request) -> web.Response:
    await _ctl(request).set_volume(float((await _body(request))["level"]))
    return web.Response(status=204)


async def position(request: web.Request) -> web.Response:
    await _ctl(request).set_position(int((await _body(request))["seconds"]))
    return web.Response(status=204)


async def power(request: web.Request) -> web.Response:
    await _ctl(request).power(request.match_info["op"])
    return web.Response(status=204)


async def keyboard(request: web.Request) -> web.Response:
    body = await _body(request)
    await _ctl(request).keyboard(request.match_info["op"], str(body.get("text", "")))
    return web.Response(status=204)


async def apps(request: web.Request) -> web.Response:
    refresh = request.query.get("refresh") in ("1", "true")
    return web.json_response(await _ctl(request).apps(refresh=refresh))


async def launch(request: web.Request) -> web.Response:
    await _ctl(request).launch(str((await _body(request))["id"]))
    return web.Response(status=204)


def make_app(controller: Controller) -> web.Application:
    app = web.Application(middlewares=[guard])
    app[CONTROLLER] = controller
    app.router.add_get("/health", health)
    app.router.add_get("/state", state)
    app.router.add_get("/events", events)
    app.router.add_post("/key/{name}", key)
    app.router.add_post("/volume", volume)
    app.router.add_post("/position", position)
    app.router.add_post("/power/{op}", power)
    app.router.add_post("/keyboard/{op}", keyboard)
    app.router.add_get("/apps", apps)
    app.router.add_post("/launch", launch)
    return app


async def serve(controller: Controller, port: int) -> None:
    runner = web.AppRunner(make_app(controller), shutdown_timeout=2.0)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    log.info("listening on http://127.0.0.1:%d", port)
    ctl_task = asyncio.create_task(controller.run())
    try:
        await asyncio.Event().wait()  # until cancelled
    finally:
        controller.hub.close()
        ctl_task.cancel()
        await asyncio.gather(ctl_task, return_exceptions=True)
        await runner.cleanup()
