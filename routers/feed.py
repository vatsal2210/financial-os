"""Feed routes — market scans, news, and auto-refresh for holdings."""
import json
from datetime import datetime
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from database import get_db, get_setting, TEMPLATES_DIR
from services.market import get_prices_batch

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _render(request, template, **ctx):
    return templates.TemplateResponse(request=request, name=template, context=ctx)


@router.get("/feed", response_class=HTMLResponse)
async def feed(request: Request):
    conn = get_db()

    # Get all held symbols
    held_symbols = [
        row["symbol"] for row in conn.execute(
            "SELECT DISTINCT symbol FROM transactions "
            "WHERE symbol IS NOT NULL AND type IN ('buy', 'sell') "
            "GROUP BY symbol HAVING SUM(CASE WHEN type='buy' THEN quantity ELSE -quantity END) > 0"
        ).fetchall()
    ]

    # Get watchlist symbols
    watchlist_symbols = [
        row["symbol"] for row in conn.execute(
            "SELECT symbol FROM watchlist"
        ).fetchall()
    ]

    # Get feed entries
    feed_entries = conn.execute(
        "SELECT * FROM feed ORDER BY created_at DESC LIMIT 50"
    ).fetchall()

    # Topics
    topics = conn.execute(
        "SELECT * FROM topics WHERE enabled = 1"
    ).fetchall()

    conn.close()

    # Combine all tracked symbols
    all_symbols = list(set(held_symbols + watchlist_symbols))

    # Fetch latest prices
    prices = get_prices_batch(all_symbols) if all_symbols else {}

    # Build movers list (sort by absolute change)
    movers = []
    for sym in all_symbols:
        p = prices.get(sym, {})
        if p.get("price", 0) > 0:
            movers.append({
                "symbol": sym,
                "price": p["price"],
                "change_pct": p.get("change_pct", 0),
                "held": sym in held_symbols,
                "watched": sym in watchlist_symbols,
            })
    movers.sort(key=lambda x: abs(x["change_pct"]), reverse=True)

    # Scan schedule info
    scan_market = get_setting("scan_market_interval", "0")
    scan_off = get_setting("scan_off_interval", "0")

    return _render(request, "feed.html",
        tab="feed",
        movers=movers,
        held_symbols=held_symbols,
        watchlist_symbols=watchlist_symbols,
        feed_entries=feed_entries,
        topics=[dict(t) for t in topics],
        scan_market=scan_market,
        scan_off=scan_off,
        last_scan=get_setting("last_scan_time", "Never"),
    )


@router.post("/feed/refresh", response_class=HTMLResponse)
async def feed_refresh(request: Request):
    """Manually trigger a price refresh and log it."""
    conn = get_db()

    # Get all tracked symbols
    held = [row["symbol"] for row in conn.execute(
        "SELECT DISTINCT symbol FROM transactions "
        "WHERE symbol IS NOT NULL AND type IN ('buy', 'sell') "
        "GROUP BY symbol HAVING SUM(CASE WHEN type='buy' THEN quantity ELSE -quantity END) > 0"
    ).fetchall()]

    watched = [row["symbol"] for row in conn.execute(
        "SELECT symbol FROM watchlist"
    ).fetchall()]

    all_symbols = list(set(held + watched))
    conn.close()

    # Force refresh by clearing cache
    if all_symbols:
        conn = get_db()
        placeholders = ",".join("?" * len(all_symbols))
        conn.execute(f"DELETE FROM price_cache WHERE symbol IN ({placeholders})", all_symbols)
        conn.commit()
        conn.close()

        # Fetch fresh prices
        prices = get_prices_batch(all_symbols)

        # Log the scan
        from database import set_setting
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        set_setting("last_scan_time", now)

        # Log to feed
        big_movers = [s for s in all_symbols if abs(prices.get(s, {}).get("change_pct", 0)) > 3]
        if big_movers:
            conn = get_db()
            for sym in big_movers:
                p = prices[sym]
                direction = "up" if p["change_pct"] > 0 else "down"
                conn.execute(
                    "INSERT INTO feed (type, symbol, title, detail, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
                    ("mover", sym,
                     f"{sym} {direction} {abs(p['change_pct']):.1f}%",
                     f"${p['price']:.2f} — {'held' if sym in held else 'watchlist'}")
                )
            conn.commit()
            conn.close()

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/feed", status_code=303)
