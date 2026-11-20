"""The Anril icon, served from the backend's own address. Public, no login: two fixed files.

Why here: the Claude app shows an icon next to a connector. It takes it either from what the MCP
server announces (admin_mcp/server.py points at /brand/anril-icon.png) or from the server
address's favicon. The frontend's copies live on another host, so the backend serves its own.
The files are copies of frontend/public/icons/anril-icon-192.png and frontend/app/favicon.ico.
"""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

public_router = APIRouter()

_ASSETS = Path(__file__).resolve().parents[1] / "assets"
ICON_PATH = "/brand/anril-icon.png"
_CACHE = {"Cache-Control": "public, max-age=86400"}


@public_router.get(ICON_PATH, include_in_schema=False)
def anril_icon():
    return FileResponse(_ASSETS / "anril-icon-192.png", media_type="image/png", headers=_CACHE)


@public_router.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(_ASSETS / "favicon.ico", media_type="image/x-icon", headers=_CACHE)
