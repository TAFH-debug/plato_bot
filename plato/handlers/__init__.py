"""Handler routers, in matching order."""
from aiogram import Router

from . import auth, browse, prefs


def build_router() -> Router:
    root = Router(name="root")
    root.include_router(auth.router)
    root.include_router(prefs.router)
    root.include_router(browse.router)
    return root
