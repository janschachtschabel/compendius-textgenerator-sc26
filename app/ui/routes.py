"""The review page (D66): its static files at /ui/ and the options it is built from, served when UI_ENABLED is set.

The page is plain files - HTML, CSS and JavaScript modules, no build step and no library from elsewhere - so the
server only hands them out. It calls the endpoints from the browser with the key its reader enters, and it sets
every text of an answer as text, never as markup (static/render.mjs), so the policy below can forbid everything but
the page's own files.
"""

from __future__ import annotations

import hashlib
from functools import partial
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from app.api.errors import JsonResponse
from app.api.system_threads import run_system
from app.ui.options import ui_options

STATIC_DIR = Path(__file__).parent / "static"
MEDIA_TYPES = {".css": "text/css; charset=utf-8", ".mjs": "text/javascript; charset=utf-8"}
HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-cache",  # an updated image shows at once
}


class _File:
    """A file of the page with the tag of its content. no-cache has the browser ask again on every visit; with the
    tag it gets the file back only when it changed, else a 304 (audit 2026-09-29, S13)."""

    def __init__(self, content: bytes, media_type: str) -> None:
        self.content = content
        self.media_type = media_type
        self.headers = {**HEADERS, "ETag": f'"{hashlib.sha256(content).hexdigest()[:32]}"'}

    def answer(self, request: Request) -> Response:
        held = request.headers.get("if-none-match", "")
        tags = {tag.strip().removeprefix("W/") for tag in held.split(",")}  # a comparison as weak as RFC 9110 allows
        if "*" in tags or self.headers["ETag"] in tags:
            return Response(status_code=304, headers=self.headers)
        return Response(self.content, media_type=self.media_type, headers=self.headers)


def ui_router(static_dir: Path = STATIC_DIR) -> APIRouter:
    """The routes of the page. Its files are read once here, so a request can only pick one of them by name."""
    page = _File((static_dir / "index.html").read_bytes(), "text/html; charset=utf-8")
    assets = {
        path.name: _File(path.read_bytes(), MEDIA_TYPES[path.suffix])
        for path in static_dir.iterdir()
        if path.suffix in MEDIA_TYPES
    }
    router = APIRouter(include_in_schema=False)

    # The files come from memory, so these routes need no thread: a page that waits behind compendium requests for a
    # free worker thread would look broken
    @router.get("/ui")
    async def to_the_page() -> RedirectResponse:
        # Relative, so the page and its files resolve below /ui/ also behind a proxy that puts a prefix in front
        return RedirectResponse("ui/", headers=HEADERS)

    @router.get("/ui/")
    async def the_page(request: Request) -> Response:
        return page.answer(request)

    @router.get("/ui/options.json")
    async def the_options(request: Request) -> JsonResponse:
        # The custom templates are read from disk, so off the event loop - but in the threads of the monitoring
        # path, which compendium requests cannot fill (app/api/system_threads.py)
        state = request.app.state
        build = partial(ui_options, state.settings, state.templates, state.service.subjects, llm=state.llm is not None)
        return JsonResponse(await run_system(request, build), headers=HEADERS)

    @router.get("/ui/{name}")
    async def an_asset(name: str, request: Request) -> Response:
        found = assets.get(name)  # a file name, never a path: nothing but the page's own files can match
        if found is None:
            raise HTTPException(status_code=404, detail="Keine Datei der Prüfansicht")
        return found.answer(request)

    return router
