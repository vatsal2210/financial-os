"""Portfolio calculations — P&L, allocation, holdings from transactions."""
from database import get_db
from services.market import get_prices_batch


def calculate_holdings(account_id: int = None) -> list[dict]:
    """Calculate current holdings from transaction history using FIFO cost basis."""
    conn = get_db()

    where = "WHERE type IN ('buy', 'sell')"
    params = []
    if account_id:
        where += " AND account_id = ?"
        params.append(account_id)

    rows = conn.execute(
        f"SELECT symbol, type, quantity, price, amount, account_id, currency "
        f"FROM transactions {where} AND symbol IS NOT NULL "
        f"ORDER BY date ASC",
        params
    ).fetchall()
    conn.close()

    # Build position map: {(account_id, symbol): {quantity, total_cost}}
    positions = {}
    for row in rows:
        key = (row["account_id"], row["symbol"])
        if key not in positions:
            positions[key] = {"quantity": 0, "total_cost": 0, "currency": row["currency"]}

        pos = positions[key]
        qty = abs(row["quantity"] or 0)
        price = abs(row["price"] or 0)

        if row["type"] == "buy":
            pos["quantity"] += qty
            pos["total_cost"] += qty * price
        elif row["type"] == "sell":
            if pos["quantity"] > 0:
                avg_cost = pos["total_cost"] / pos["quantity"]
                sell_qty = min(qty, pos["quantity"])
                pos["quantity"] -= sell_qty
                pos["total_cost"] -= sell_qty * avg_cost

    # Filter out zero/negative positions and build result
    holdings = []
    symbols = set()
    for (acct_id, symbol), pos in positions.items():
        if pos["quantity"] > 0.001:
            avg_cost = pos["total_cost"] / pos["quantity"] if pos["quantity"] > 0 else 0
            holdings.append({
                "account_id": acct_id,
                "symbol": symbol,
                "quantity": round(pos["quantity"], 4),
                "avg_cost": round(avg_cost, 2),
                "currency": pos["currency"],
            })
            symbols.add(symbol)

    # Fetch live prices
    prices = get_prices_batch(list(symbols))

    for h in holdings:
        price_data = prices.get(h["symbol"], {})
        current_price = price_data.get("price", 0)
        h["current_price"] = current_price
        h["market_value"] = round(h["quantity"] * current_price, 2)
        h["cost_basis"] = round(h["quantity"] * h["avg_cost"], 2)
        h["unrealized_pnl"] = round(h["market_value"] - h["cost_basis"], 2)
        h["unrealized_pct"] = round(
            (h["unrealized_pnl"] / h["cost_basis"] * 100) if h["cost_basis"] > 0 else 0, 2
        )
        h["change_pct"] = price_data.get("change_pct", 0)

    return sorted(holdings, key=lambda x: x["market_value"], reverse=True)


def get_portfolio_summary(account_id: int = None) -> dict:
    """Get high-level portfolio stats."""
    conn = get_db()

    where_clause = ""
    params = []
    if account_id:
        where_clause = "WHERE account_id = ?"
        params.append(account_id)

    # Total deposits and withdrawals
    deposits = conn.execute(
        f"SELECT COALESCE(SUM(ABS(amount)), 0) as total FROM transactions "
        f"{'WHERE' if not where_clause else where_clause + ' AND'} type = 'deposit'"
        if not where_clause else
        f"SELECT COALESCE(SUM(ABS(amount)), 0) as total FROM transactions "
        f"{where_clause} AND type = 'deposit'",
        params
    ).fetchone()["total"]

    withdrawals = conn.execute(
        f"SELECT COALESCE(SUM(ABS(amount)), 0) as total FROM transactions "
        f"{'WHERE' if not where_clause else where_clause + ' AND'} type = 'withdrawal'"
        if not where_clause else
        f"SELECT COALESCE(SUM(ABS(amount)), 0) as total FROM transactions "
        f"{where_clause} AND type = 'withdrawal'",
        params
    ).fetchone()["total"]

    # Dividends
    dividends = conn.execute(
        f"SELECT COALESCE(SUM(ABS(amount)), 0) as total FROM transactions "
        f"{'WHERE' if not where_clause else where_clause + ' AND'} type = 'dividend'"
        if not where_clause else
        f"SELECT COALESCE(SUM(ABS(amount)), 0) as total FROM transactions "
        f"{where_clause} AND type = 'dividend'",
        params
    ).fetchone()["total"]

    # Realized P&L from sells
    realized = _calculate_realized_pnl(conn, account_id)

    # Transaction count
    tx_count = conn.execute(
        f"SELECT COUNT(*) as cnt FROM transactions {where_clause}",
        params
    ).fetchone()["cnt"]

    # Account count
    acct_count = conn.execute("SELECT COUNT(*) as cnt FROM accounts").fetchone()["cnt"]

    conn.close()

    # Current holdings value
    holdings = calculate_holdings(account_id)
    total_market_value = sum(h["market_value"] for h in holdings)
    total_cost_basis = sum(h["cost_basis"] for h in holdings)
    total_unrealized = sum(h["unrealized_pnl"] for h in holdings)

    net_deposits = deposits - withdrawals

    return {
        "total_value": round(total_market_value, 2),
        "total_cost_basis": round(total_cost_basis, 2),
        "net_deposits": round(net_deposits, 2),
        "total_return": round(total_market_value - net_deposits + realized + dividends, 2),
        "unrealized_pnl": round(total_unrealized, 2),
        "realized_pnl": round(realized, 2),
        "dividends": round(dividends, 2),
        "num_positions": len(holdings),
        "num_transactions": tx_count,
        "num_accounts": acct_count,
        "holdings": holdings,
    }


def _calculate_realized_pnl(conn, account_id: int = None) -> float:
    """Calculate realized P&L using FIFO method."""
    where = "WHERE type IN ('buy', 'sell') AND symbol IS NOT NULL"
    params = []
    if account_id:
        where += " AND account_id = ?"
        params.append(account_id)

    rows = conn.execute(
        f"SELECT symbol, type, quantity, price FROM transactions {where} ORDER BY date ASC",
        params
    ).fetchall()

    # FIFO lots per symbol
    lots = {}  # symbol → deque of (qty, price)
    realized = 0.0

    for row in rows:
        symbol = row["symbol"]
        qty = abs(row["quantity"] or 0)
        price = abs(row["price"] or 0)

        if symbol not in lots:
            lots[symbol] = []

        if row["type"] == "buy":
            lots[symbol].append([qty, price])
        elif row["type"] == "sell":
            remaining = qty
            while remaining > 0 and lots.get(symbol):
                lot = lots[symbol][0]
                take = min(remaining, lot[0])
                realized += take * (price - lot[1])
                lot[0] -= take
                remaining -= take
                if lot[0] <= 0.001:
                    lots[symbol].pop(0)

    return realized


def get_allocation(holdings: list[dict]) -> list[dict]:
    """Calculate portfolio allocation by symbol."""
    total = sum(h["market_value"] for h in holdings)
    if total == 0:
        return []

    return [
        {
            "symbol": h["symbol"],
            "value": h["market_value"],
            "pct": round(h["market_value"] / total * 100, 1),
        }
        for h in holdings
    ]
