"""Shared render helper — injects global context (update check, etc.)."""
from fastapi.templating import Jinja2Templates
from database import TEMPLATES_DIR
from services.updater import check_for_update

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Cache update check result per process (avoid re-checking on every render)
_update_cache = {}


def render(request, template, **ctx):
    """Render template with global context injected."""
    if "update" not in _update_cache or not _update_cache.get("_checked"):
        _update_cache["data"] = check_for_update()
        _update_cache["_checked"] = True
    ctx.setdefault("update", _update_cache["data"])
    return templates.TemplateResponse(request=request, name=template, context=ctx)
