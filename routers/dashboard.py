"""Dashboard routes — portfolio overview, holdings, transactions."""
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from database import get_db, is_onboarded
from services.portfolio import calculate_holdings, get_portfolio_summary, get_allocation

router = APIRouter()
from database import TEMPLATES_DIR
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _render(request, template, **ctx):
    return templates.TemplateResponse(request=request, name=template, context=ctx)


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not is_onboarded():
        return RedirectResponse(url="/onboarding", status_code=303)

    summary = get_portfolio_summary()
    allocation = get_allocation(summary["holdings"])

    return _render(request, "dashboard.html",
        tab="overview", summary=summary, allocation=allocation)


@router.get("/holdings", response_class=HTMLResponse)
async def holdings(request: Request, account_id: int = Query(None)):
    if not is_onboarded():
        return RedirectResponse(url="/onboarding", status_code=303)

    conn = get_db()
    accounts = conn.execute("SELECT * FROM accounts ORDER BY name").fetchall()
    conn.close()

    holdings_list = calculate_holdings(account_id)

    return _render(request, "dashboard.html",
        tab="holdings", holdings=holdings_list, accounts=accounts,
        selected_account=account_id)


@router.get("/transactions", response_class=HTMLResponse)
async def transactions(
    request: Request,
    account_id: int = Query(None),
    type: str = Query(None),
    symbol: str = Query(None),
    page: int = Query(1),
):
    if not is_onboarded():
        return RedirectResponse(url="/onboarding", status_code=303)

    per_page = 50
    offset = (page - 1) * per_page

    conn = get_db()
    accounts = conn.execute("SELECT * FROM accounts ORDER BY name").fetchall()

    # Build query with filters
    where_parts = []
    params = []
    if account_id:
        where_parts.append("t.account_id = ?")
        params.append(account_id)
    if type:
        where_parts.append("t.type = ?")
        params.append(type)
    if symbol:
        where_parts.append("UPPER(t.symbol) LIKE ?")
        params.append(f"%{symbol.upper()}%")

    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    total = conn.execute(
        f"SELECT COUNT(*) as cnt FROM transactions t {where}", params
    ).fetchone()["cnt"]

    txs = conn.execute(
        f"SELECT t.*, a.name as account_name FROM transactions t "
        f"LEFT JOIN accounts a ON t.account_id = a.id "
        f"{where} ORDER BY t.date DESC, t.id DESC LIMIT ? OFFSET ?",
        params + [per_page, offset]
    ).fetchall()

    # Get unique types for filter
    types = conn.execute(
        "SELECT DISTINCT type FROM transactions ORDER BY type"
    ).fetchall()

    conn.close()

    return _render(request, "dashboard.html",
        tab="transactions", transactions=txs, accounts=accounts,
        types=[t["type"] for t in types], selected_account=account_id,
        selected_type=type, search_symbol=symbol or "",
        page=page, total=total,
        total_pages=(total + per_page - 1) // per_page)
