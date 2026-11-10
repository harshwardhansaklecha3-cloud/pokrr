"""Web server: serves the browser page and the game WebSocket.

Run:  .venv\\Scripts\\python.exe -m uvicorn server.app:app --port 8000
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import site
from .room import Connection, RoomManager, handle_message

WEB = Path(__file__).resolve().parents[1] / "web"

app = FastAPI(title="POKRR", docs_url=None, redoc_url=None,
              openapi_url=None)   # no debug/API explorer endpoints
app.add_middleware(GZipMiddleware, minimum_size=800)
app.mount("/static", StaticFiles(directory=WEB), name="static")

_delay = float(os.environ.get("POKER_BOT_DELAY", "0.9"))
manager = RoomManager(bot_delay=_delay, deal_pause=1.6 if _delay else 0)


PAGE_CACHE = {"Cache-Control": "public, max-age=600"}


@app.get("/play")
async def play():
    # no-cache: the page always asks for the latest version (it names the
    # current script/style versions, so updates show up without a hard refresh)
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/")
async def home(request: Request):
    room = request.query_params.get("room")
    if room:                                   # old invite links: /?room=CODE
        return RedirectResponse(f"/play?room={room[:8]}", status_code=307)
    return HTMLResponse(site.render("/", _base(request)), headers=PAGE_CACHE)


def _base(request: Request) -> str:
    """This site's address as the visitor sees it (https behind the host's proxy)."""
    return str(request.base_url).rstrip("/")


@app.get("/sitemap.xml")
async def sitemap(request: Request):
    return Response(site.with_base(_base(request), site.sitemap), media_type="application/xml",
                    headers=PAGE_CACHE)


@app.get("/robots.txt")
async def robots(request: Request):
    return PlainTextResponse(site.with_base(_base(request), site.robots), headers=PAGE_CACHE)


@app.get("/llms.txt")
async def llms(request: Request):
    return PlainTextResponse(site.with_base(_base(request), site.llms_txt), headers=PAGE_CACHE)


@app.get("/llms-full.txt")
async def llms_full(request: Request):
    return PlainTextResponse(site.with_base(_base(request), site.llms_txt, True), headers=PAGE_CACHE)


@app.get("/sw.js")
async def service_worker():
    # served from the root so it can cache the guide pages for offline reading
    return FileResponse(WEB / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.get("/healthz")
async def health():
    return PlainTextResponse("ok")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    conn = Connection(ws)
    try:
        while True:
            msg = await ws.receive_json()
            if isinstance(msg, dict):
                await handle_message(manager, conn, msg)
    except WebSocketDisconnect:
        pass
    except Exception:          # bad JSON etc.: drop this connection only
        logging.getLogger("poker").exception("connection closed after an error")
    finally:
        await manager.detach(conn.token, ws)


@app.get("/{path:path}")
async def pages(path: str, request: Request):
    html = site.render("/" + path.rstrip("/"), _base(request))
    if html is None:
        return HTMLResponse(site.with_base(_base(request), site.page, "/404", "Page not found", "This page doesn't exist.",
                                      '<h1>Page not found</h1><p><a href="/">Home</a> · '
                                      '<a href="/play">Play</a></p>'), status_code=404)
    return HTMLResponse(html, headers=PAGE_CACHE)
