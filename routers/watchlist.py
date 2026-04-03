"""Watchlist and Topics routes — track symbols and areas of interest."""
import json
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from database import get_db
from services.market import get_prices_batch
from routers.shared import render as _render

router = APIRouter()


@router.get("/watchlist", response_class=HTMLResponse)
async def watchlist(request: Request):
    conn = get_db()
    items = conn.execute(
        "SELECT * FROM watchlist ORDER BY added_at DESC"
    ).fetchall()
    topics = conn.execute(
        "SELECT * FROM topics ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    # Fetch live prices for all watchlist symbols
    symbols = [item["symbol"] for item in items]
    prices = get_prices_batch(symbols) if symbols else {}

    # Enrich watchlist items with price data
    enriched = []
    for item in items:
        sym = item["symbol"]
        p = prices.get(sym, {})
        current_price = p.get("price", 0)
        change_pct = p.get("change_pct", 0)
        target = item["target_price"]

        if target and current_price > 0:
            distance_pct = round((target - current_price) / current_price * 100, 2)
        else:
            distance_pct = None

        enriched.append({
            "id": item["id"],
            "symbol": sym,
            "current_price": current_price,
            "target_price": target,
            "distance_pct": distance_pct,
            "change_pct": change_pct,
            "notes": item["notes"] or "",
            "added_at": item["added_at"],
            "error": p.get("error", False),
        })

    # Parse topic keywords from JSON
    parsed_topics = []
    for t in topics:
        keywords_raw = t["keywords"]
        try:
            keywords = json.loads(keywords_raw) if keywords_raw else []
        except (json.JSONDecodeError, TypeError):
            keywords = []
        parsed_topics.append({
            "id": t["id"],
            "name": t["name"],
            "keywords": keywords,
            "enabled": bool(t["enabled"]),
            "created_at": t["created_at"],
        })

    return _render(request, "watchlist.html",
        tab="watchlist", items=enriched, topics=parsed_topics)


@router.post("/watchlist/add")
async def watchlist_add(
    symbol: str = Form(...),
    target_price: float = Form(None),
    notes: str = Form(""),
):
    symbol = symbol.strip().upper()
    if not symbol:
        return RedirectResponse(url="/watchlist", status_code=303)

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO watchlist (symbol, target_price, notes) VALUES (?, ?, ?)",
            (symbol, target_price if target_price else None, notes.strip() or None),
        )
        conn.commit()
    except Exception:
        # Symbol already exists (UNIQUE constraint) — silently redirect
        pass
    finally:
        conn.close()

    return RedirectResponse(url="/watchlist", status_code=303)


@router.post("/watchlist/remove")
async def watchlist_remove(id: int = Form(...)):
    conn = get_db()
    conn.execute("DELETE FROM watchlist WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/watchlist", status_code=303)


@router.post("/topics/add")
async def topics_add(
    name: str = Form(...),
    keywords: str = Form(""),
):
    name = name.strip()
    if not name:
        return RedirectResponse(url="/watchlist", status_code=303)

    # Parse comma-separated keywords into JSON array
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
    kw_json = json.dumps(kw_list)

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO topics (name, keywords) VALUES (?, ?)",
            (name, kw_json),
        )
        conn.commit()
    except Exception:
        # Name already exists (UNIQUE constraint) — silently redirect
        pass
    finally:
        conn.close()

    return RedirectResponse(url="/watchlist", status_code=303)


@router.post("/topics/toggle")
async def topics_toggle(id: int = Form(...)):
    conn = get_db()
    conn.execute(
        "UPDATE topics SET enabled = CASE WHEN enabled = 1 THEN 0 ELSE 1 END WHERE id = ?",
        (id,),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/watchlist", status_code=303)


@router.post("/topics/remove")
async def topics_remove(id: int = Form(...)):
    conn = get_db()
    conn.execute("DELETE FROM topics WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/watchlist", status_code=303)
