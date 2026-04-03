"""Trading rules — user-configurable enforcement and compliance tracking."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from database import get_db, TEMPLATES_DIR
from routers.shared import render as _render

router = APIRouter()
# Default rules (user can customize)
DEFAULT_RULES = [
    {"name": "Max Positions", "rule_type": "max_positions", "value": 20,
     "desc": "Maximum number of open positions across all accounts"},
    {"name": "Max Trades / Month", "rule_type": "max_monthly_trades", "value": 15,
     "desc": "Maximum buy orders per calendar month"},
    {"name": "Stop-Loss %", "rule_type": "stop_loss_pct", "value": 15,
     "desc": "Alert when a position drops below this % from average cost"},
    {"name": "Min Position Size ($)", "rule_type": "min_position", "value": 300,
     "desc": "Minimum value for any single position — too small isn't worth tracking"},
    {"name": "Cooling Period (hours)", "rule_type": "cooling_period", "value": 24,
     "desc": "Wait this long after adding to watchlist before buying"},
]



def _ensure_default_rules():
    """Seed default rules if none exist."""
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM trading_rules").fetchone()[0]
    if count == 0:
        for r in DEFAULT_RULES:
            conn.execute(
                "INSERT INTO trading_rules (name, rule_type, value, enabled) VALUES (?, ?, ?, 1)",
                (r["name"], r["rule_type"], r["value"])
            )
        conn.commit()
    conn.close()


def _check_compliance(conn) -> list[dict]:
    """Run all enabled rules against current data and return violations."""
    rules = conn.execute("SELECT * FROM trading_rules WHERE enabled = 1").fetchall()
    violations = []
    warnings = []

    for rule in rules:
        rt = rule["rule_type"]
        val = rule["value"]

        if rt == "max_positions":
            positions = conn.execute("""
                SELECT COUNT(DISTINCT symbol) as cnt FROM (
                    SELECT symbol,
                        SUM(CASE WHEN type='buy' THEN quantity ELSE 0 END) -
                        SUM(CASE WHEN type='sell' THEN quantity ELSE 0 END) as net
                    FROM transactions WHERE symbol IS NOT NULL AND type IN ('buy','sell')
                    GROUP BY symbol HAVING net > 0.001
                )
            """).fetchone()["cnt"]
            if positions > val:
                violations.append({
                    "rule": rule["name"], "severity": "high",
                    "detail": f"{positions} positions open (limit: {int(val)})",
                    "current": positions, "limit": int(val),
                })
            else:
                warnings.append({
                    "rule": rule["name"], "status": "ok",
                    "detail": f"{positions} / {int(val)} positions",
                    "pct": round(positions / val * 100) if val else 0,
                })

        elif rt == "max_monthly_trades":
            now = datetime.now()
            month_start = now.replace(day=1).strftime("%Y-%m-%d")
            trades = conn.execute(
                "SELECT COUNT(*) as cnt FROM transactions WHERE type='buy' AND date >= ?",
                (month_start,)
            ).fetchone()["cnt"]
            if trades > val:
                violations.append({
                    "rule": rule["name"], "severity": "high",
                    "detail": f"{trades} buys this month (limit: {int(val)})",
                    "current": trades, "limit": int(val),
                })
            else:
                warnings.append({
                    "rule": rule["name"], "status": "ok",
                    "detail": f"{trades} / {int(val)} trades this month",
                    "pct": round(trades / val * 100) if val else 0,
                })

        elif rt == "stop_loss_pct":
            # Check positions that have dropped significantly
            positions = conn.execute("""
                SELECT symbol,
                    SUM(CASE WHEN type='buy' THEN quantity ELSE 0 END) as bought,
                    SUM(CASE WHEN type='sell' THEN quantity ELSE 0 END) as sold,
                    SUM(CASE WHEN type='buy' THEN quantity * price ELSE 0 END) as total_cost
                FROM transactions WHERE symbol IS NOT NULL AND type IN ('buy','sell')
                GROUP BY symbol
                HAVING bought - sold > 0.001
            """).fetchall()

            from services.market import get_prices_batch
            symbols = [p["symbol"] for p in positions]
            prices = get_prices_batch(symbols) if symbols else {}

            breached = []
            for p in positions:
                net_qty = (p["bought"] or 0) - (p["sold"] or 0)
                if net_qty <= 0:
                    continue
                avg_cost = p["total_cost"] / (p["bought"] or 1)
                current = prices.get(p["symbol"], {}).get("price", 0)
                if current > 0 and avg_cost > 0:
                    drop_pct = (avg_cost - current) / avg_cost * 100
                    if drop_pct > val:
                        breached.append(f"{p['symbol']} (-{drop_pct:.1f}%)")

            if breached:
                violations.append({
                    "rule": rule["name"], "severity": "high",
                    "detail": f"Below {int(val)}% stop: {', '.join(breached[:5])}",
                })
            else:
                warnings.append({
                    "rule": rule["name"], "status": "ok",
                    "detail": f"No positions below -{int(val)}% stop",
                    "pct": 0,
                })

        elif rt == "min_position":
            from services.market import get_prices_batch
            positions = conn.execute("""
                SELECT symbol,
                    SUM(CASE WHEN type='buy' THEN quantity ELSE 0 END) -
                    SUM(CASE WHEN type='sell' THEN quantity ELSE 0 END) as net_qty
                FROM transactions WHERE symbol IS NOT NULL AND type IN ('buy','sell')
                GROUP BY symbol HAVING net_qty > 0.001
            """).fetchall()

            symbols = [p["symbol"] for p in positions]
            prices = get_prices_batch(symbols) if symbols else {}

            small = []
            for p in positions:
                current = prices.get(p["symbol"], {}).get("price", 0)
                mkt_val = p["net_qty"] * current
                if 0 < mkt_val < val:
                    small.append(f"{p['symbol']} (${mkt_val:.0f})")

            if small:
                violations.append({
                    "rule": rule["name"], "severity": "low",
                    "detail": f"Under ${int(val)}: {', '.join(small[:5])}",
                })
            else:
                warnings.append({
                    "rule": rule["name"], "status": "ok",
                    "detail": f"All positions above ${int(val)}",
                    "pct": 0,
                })

        elif rt == "cooling_period":
            hours = int(val)
            cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
            recent_buys = conn.execute("""
                SELECT t.symbol, t.date, w.added_at FROM transactions t
                JOIN watchlist w ON t.symbol = w.symbol
                WHERE t.type = 'buy' AND t.created_at >= ?
            """, (cutoff,)).fetchall()

            if recent_buys:
                symbols = [r["symbol"] for r in recent_buys]
                violations.append({
                    "rule": rule["name"], "severity": "medium",
                    "detail": f"Bought within {hours}h of watchlisting: {', '.join(symbols[:3])}",
                })
            else:
                warnings.append({
                    "rule": rule["name"], "status": "ok",
                    "detail": f"{hours}h cooling period respected",
                    "pct": 0,
                })

    return violations, warnings


@router.get("/rules", response_class=HTMLResponse)
async def rules_page(request: Request):
    _ensure_default_rules()
    conn = get_db()

    rules = conn.execute("SELECT * FROM trading_rules ORDER BY id").fetchall()
    violations, compliance = _check_compliance(conn)
    conn.close()

    violation_count = len(violations)
    compliance_count = len(compliance)
    total = violation_count + compliance_count
    score = round(compliance_count / total * 100) if total else 100

    return _render(request, "rules.html",
        tab="rules",
        rules=rules,
        violations=violations,
        compliance=compliance,
        score=score,
        violation_count=violation_count,
        default_rules=DEFAULT_RULES,
    )


@router.post("/rules/update")
async def update_rule(
    request: Request,
    id: int = Form(...),
    value: float = Form(...),
):
    conn = get_db()
    conn.execute("UPDATE trading_rules SET value = ? WHERE id = ?", (value, id))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/rules", status_code=303)


@router.post("/rules/toggle")
async def toggle_rule(id: int = Form(...)):
    conn = get_db()
    conn.execute(
        "UPDATE trading_rules SET enabled = CASE WHEN enabled=1 THEN 0 ELSE 1 END WHERE id = ?",
        (id,)
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/rules", status_code=303)


@router.post("/rules/add")
async def add_rule(
    name: str = Form(...),
    rule_type: str = Form(...),
    value: float = Form(...),
):
    conn = get_db()
    conn.execute(
        "INSERT INTO trading_rules (name, rule_type, value) VALUES (?, ?, ?)",
        (name.strip(), rule_type, value)
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/rules", status_code=303)


@router.post("/rules/remove")
async def remove_rule(id: int = Form(...)):
    conn = get_db()
    conn.execute("DELETE FROM trading_rules WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/rules", status_code=303)


@router.post("/rules/reset")
async def reset_rules():
    """Reset to default rules."""
    conn = get_db()
    conn.execute("DELETE FROM trading_rules")
    conn.commit()
    conn.close()
    _ensure_default_rules()
    return RedirectResponse(url="/rules", status_code=303)
