"""Settings routes — API keys, preferences, scan schedule, danger zone."""
import shutil
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from database import get_db, get_setting, set_setting, DB_PATH, TEMPLATES_DIR
from routers.shared import render as _render

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    conn = get_db()
    accounts = conn.execute("SELECT * FROM accounts ORDER BY name").fetchall()
    imports = conn.execute(
        "SELECT i.*, a.name as account_name FROM imports i "
        "LEFT JOIN accounts a ON i.account_id = a.id ORDER BY imported_at DESC LIMIT 10"
    ).fetchall()
    conn.close()

    # Check effective AI config (Settings + env fallback)
    from services.ai_client import get_ai_provider
    effective_ai = get_ai_provider()

    from version import VERSION, BUILD

    return _render(request, "settings.html",
        tab="settings",
        ai_provider=get_setting("ai_provider", "") or effective_ai["provider"],
        ai_api_key=_mask_key(get_setting("ai_api_key", "") or effective_ai["key"]),
        has_ai_key=effective_ai["configured"],
        ai_from_env=effective_ai["configured"] and not get_setting("ai_api_key", ""),
        currency=get_setting("home_currency", "USD"),
        scan_market=get_setting("scan_market_interval", "0"),
        scan_off=get_setting("scan_off_interval", "0"),
        scan_holdings_news=get_setting("scan_holdings_news", "") == "1",
        accounts=accounts,
        imports=imports,
        version=VERSION,
        build=BUILD,
    )


@router.post("/settings/ai")
async def save_ai_settings(
    request: Request,
    ai_provider: str = Form(...),
    ai_api_key: str = Form(""),
):
    set_setting("ai_provider", ai_provider)
    if ai_api_key and not ai_api_key.startswith("sk-..."):
        set_setting("ai_api_key", ai_api_key)
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/scan-schedule")
async def save_scan_schedule(
    request: Request,
    market_hours_interval: str = Form("0"),
    off_hours_interval: str = Form("0"),
    scan_holdings_news: str = Form("0"),
):
    set_setting("scan_market_interval", market_hours_interval)
    set_setting("scan_off_interval", off_hours_interval)
    set_setting("scan_holdings_news", scan_holdings_news)
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/currency")
async def save_currency(request: Request, currency: str = Form(...)):
    set_setting("home_currency", currency)
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/account/add")
async def add_account(
    request: Request,
    name: str = Form(...),
    brokerage: str = Form(...),
    account_type: str = Form(...),
    currency: str = Form("USD"),
):
    conn = get_db()
    conn.execute(
        "INSERT INTO accounts (name, brokerage, account_type, currency) VALUES (?, ?, ?, ?)",
        (name, brokerage, account_type, currency)
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/settings", status_code=303)


@router.get("/settings/export-backup")
async def export_backup(request: Request):
    """Download a copy of the SQLite database."""
    if DB_PATH.exists():
        return FileResponse(
            path=str(DB_PATH),
            filename="financeos-backup.db",
            media_type="application/octet-stream",
        )
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/delete-transactions")
async def delete_transactions(request: Request):
    """Delete all transactions but keep accounts and settings."""
    conn = get_db()
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.executescript("""
        DELETE FROM transactions;
        DELETE FROM imports;
        DELETE FROM holdings;
        DELETE FROM price_cache;
    """)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()
    conn.close()
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/reset")
async def reset_data(request: Request):
    """Nuclear option — delete all data and start fresh."""
    conn = get_db()
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.executescript("""
        DELETE FROM transactions;
        DELETE FROM holdings;
        DELETE FROM accounts;
        DELETE FROM imports;
        DELETE FROM chat_history;
        DELETE FROM price_cache;
        DELETE FROM watchlist;
        DELETE FROM topics;
        DELETE FROM settings WHERE key = 'onboarded';
    """)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()
    conn.close()
    return RedirectResponse(url="/onboarding", status_code=303)


def _mask_key(key: str) -> str:
    if not key:
        return ""
    return f"sk-...{key[-4:]}" if len(key) > 8 else "***"
