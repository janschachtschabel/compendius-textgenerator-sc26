"""/docs and /redoc with a policy that lets their scripts talk to this service only (audit 2026-09-29, S12).

FastAPI's own pages load Swagger UI and ReDoc from cdn.jsdelivr.net (swagger-ui-dist@5, redoc@2) without Subresource
Integrity and without a Content-Security-Policy, on the origin of /ui/, whose reader's API key sits in the
sessionStorage - and a key entered in Swagger UI's dialog sits in its page. A compromised package could read either and
send it anywhere. The pages here are FastAPI's, with a policy: scripts only from the one file of the CDN and the inline
code the page holds, by its hash (computed from the page as served, since the code names the address of
/openapi.json, which a proxy's prefix changes); requests and images only to the service itself (images as data: too),
no form anywhere, no frame around the page. Styles may be inline: ReDoc writes its own style elements. The icon is the
review page's, not FastAPI's.

What a policy cannot stop is a script that sends the whole page elsewhere. So the files come in fixed versions, each
with its SHA-384, and the browser runs no other content (Subresource Integrity). A version on jsDelivr never changes:
the checksums hold on every server whose readers reach the CDN, and no update of the service touches them. A newer
Swagger UI or ReDoc is a new version and checksum below, taken of the file as served:
``curl -s <address> | openssl dgst -sha384 -binary | openssl base64 -A``. A server whose readers cannot reach
cdn.jsdelivr.net, or that does not need the pages, sets API_DOCS_ENABLED=false.
"""

from __future__ import annotations

import base64
import hashlib
import re

from fastapi import APIRouter, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse

CDN = "https://cdn.jsdelivr.net/npm"
# FastAPI's defaults @5 and @2 as they resolved on 2026-09-29; each checksum was taken of the file jsDelivr served,
# which matched the hash jsDelivr lists for it
SWAGGER_JS = f"{CDN}/swagger-ui-dist@5.33.0/swagger-ui-bundle.js"
SWAGGER_CSS = f"{CDN}/swagger-ui-dist@5.33.0/swagger-ui.css"
REDOC_JS = f"{CDN}/redoc@2.5.4/bundles/redoc.standalone.js"
CHECKSUMS = {
    SWAGGER_JS: "sha384-YDALVcy8kj8yltLBVi1vBiBAUqdxvus673gM8XKwiy6aDUJFXivF/KCufekjYbVf",
    SWAGGER_CSS: "sha384-Ov4/wv3j2bmct8cDc5X4ngJZohVPzEmc6uDPH8WeljUxO5vtoykvMEfbu9Vh6RaW",
    REDOC_JS: "sha384-w447zOpYfw/1Tv/5AK9NfHTlQIqE3RVR6KY62jCyy9zNDgO64cMwGGP1Fj0zJVf5",
}
# The icon of the review page (app/ui/static/index.html): FastAPI's came from fastapi.tiangolo.com
ICON = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' "
    "height='32' rx='7' fill='%230f6b6f'/%3E%3Cpath d='M9 8h11a3 3 0 0 1 3 3v13H12a3 3 0 0 1-3-3z' fill='none' "
    "stroke='%23fff' stroke-width='2.4'/%3E%3Cpath d='M13 14h6M13 18h4' stroke='%23fff' stroke-width='2.4' "
    "stroke-linecap='round'/%3E%3C/svg%3E"
)
INLINE_SCRIPT = re.compile("<script>(.*?)</script>", re.DOTALL)  # a script element without src: code in the page


def _checked(html: str, urls: list[str]) -> str:
    """``html`` with each of ``urls`` tagged with its checksum. FastAPI writes each address once, in quotes, as src or
    href; a newer FastAPI that writes it otherwise fails here and in the tests, rather than serving it unchecked."""
    for url in urls:
        quoted = f'"{url}"'
        if html.count(quoted) != 1:
            raise RuntimeError(f"FastAPI's page names {url} {html.count(quoted)} times, not once")
        html = html.replace(quoted, f'{quoted} integrity="{CHECKSUMS[url]}" crossorigin="anonymous"')
    return html


def _with_policy(page: HTMLResponse, script: str, style: str = "", *, workers: bool = False) -> HTMLResponse:
    """``page`` with its files checked by their checksums and a policy that allows ``script``, the page's inline code
    by its hash and ``style``."""
    html = _checked(bytes(page.body).decode("utf-8"), [url for url in (script, style) if url])
    hashes = [
        f"'sha256-{base64.b64encode(hashlib.sha256(code.encode('utf-8')).digest()).decode('ascii')}'"
        for code in INLINE_SCRIPT.findall(html)
    ]
    directives = [
        "default-src 'none'",
        " ".join(["script-src", script, *hashes]),
        " ".join(["style-src", *([style] if style else []), "'unsafe-inline'"]),
        # ReDoc's logo from cdn.redoc.ly stays out, and the console says so: redoc.ly need not learn of every reader
        "img-src 'self' data:",
        "connect-src 'self'",
        *(["worker-src blob:"] if workers else []),  # ReDoc's search runs in a worker it makes from a blob
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    ]
    headers = {
        "Content-Security-Policy": "; ".join(directives),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",  # the CDN need not learn where the pages are
    }
    return HTMLResponse(html, status_code=page.status_code, headers=headers)


def docs_router(openapi_url: str, title: str) -> APIRouter:
    """The routes of /docs and /redoc for the description at ``openapi_url``."""
    router = APIRouter(include_in_schema=False)

    def described_at(request: Request) -> str:
        return str(request.scope.get("root_path", "")).rstrip("/") + openapi_url  # as FastAPI's own pages do

    @router.get("/docs")
    async def swagger_ui(request: Request) -> HTMLResponse:
        page = get_swagger_ui_html(
            openapi_url=described_at(request),
            title=f"{title} - Swagger UI",
            swagger_js_url=SWAGGER_JS,
            swagger_css_url=SWAGGER_CSS,
            swagger_favicon_url=ICON,
            # Swagger UI shows a badge from validator.swagger.io, which would learn the address of the description
            swagger_ui_parameters={"validatorUrl": None},
        )
        return _with_policy(page, SWAGGER_JS, SWAGGER_CSS)

    @router.get("/redoc")
    async def redoc(request: Request) -> HTMLResponse:
        page = get_redoc_html(
            openapi_url=described_at(request),
            title=f"{title} - ReDoc",
            redoc_js_url=REDOC_JS,
            redoc_favicon_url=ICON,
            with_google_fonts=False,  # fonts.googleapis.com would learn of every reader
        )
        return _with_policy(page, REDOC_JS, workers=True)

    return router
