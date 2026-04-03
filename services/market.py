"""Yahoo Finance price fetcher with local caching."""
import yfinance as yf
from datetime import datetime, timedelta
from database import get_db


CACHE_DURATION_MINUTES = 15


def get_price(symbol: str) -> dict:
    """Get current price for a symbol. Uses cache if fresh enough."""
    conn = get_db()
    cached = conn.execute(
        "SELECT price, change_pct, currency, updated_at FROM price_cache WHERE symbol = ?",
        (symbol,)
    ).fetchone()

    if cached:
        updated = datetime.fromisoformat(cached["updated_at"])
        if datetime.utcnow() - updated < timedelta(minutes=CACHE_DURATION_MINUTES):
            conn.close()
            return {
                "symbol": symbol,
                "price": cached["price"],
                "change_pct": cached["change_pct"],
                "currency": cached["currency"],
                "cached": True,
            }

    # Fetch from Yahoo Finance
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        price = info.get("lastPrice") or info.get("last_price", 0)
        prev_close = info.get("previousClose") or info.get("previous_close", 0)
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0
        currency = info.get("currency", "USD")

        # Cache it
        conn.execute(
            "INSERT INTO price_cache (symbol, price, change_pct, currency, updated_at) "
            "VALUES (?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(symbol) DO UPDATE SET price=excluded.price, change_pct=excluded.change_pct, "
            "currency=excluded.currency, updated_at=excluded.updated_at",
            (symbol, price, round(change_pct, 2), currency)
        )
        conn.commit()
        conn.close()

        return {
            "symbol": symbol,
            "price": round(price, 2),
            "change_pct": round(change_pct, 2),
            "currency": currency,
            "cached": False,
        }
    except Exception:
        conn.close()
        return {
            "symbol": symbol,
            "price": 0,
            "change_pct": 0,
            "currency": "USD",
            "cached": False,
            "error": True,
        }


def get_prices_batch(symbols: list[str]) -> dict[str, dict]:
    """Get prices for multiple symbols efficiently."""
    results = {}
    # yfinance supports batch downloads
    if not symbols:
        return results

    # Check cache first
    conn = get_db()
    fresh = set()
    for symbol in symbols:
        cached = conn.execute(
            "SELECT price, change_pct, currency, updated_at FROM price_cache WHERE symbol = ?",
            (symbol,)
        ).fetchone()
        if cached:
            updated = datetime.fromisoformat(cached["updated_at"])
            if datetime.utcnow() - updated < timedelta(minutes=CACHE_DURATION_MINUTES):
                results[symbol] = {
                    "symbol": symbol,
                    "price": cached["price"],
                    "change_pct": cached["change_pct"],
                    "currency": cached["currency"],
                    "cached": True,
                }
                fresh.add(symbol)

    # Fetch remaining from Yahoo
    stale = [s for s in symbols if s not in fresh]
    if stale:
        try:
            tickers = yf.Tickers(" ".join(stale))
            for symbol in stale:
                try:
                    info = tickers.tickers[symbol].fast_info
                    price = info.get("lastPrice") or info.get("last_price", 0)
                    prev_close = info.get("previousClose") or info.get("previous_close", 0)
                    change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0
                    currency = info.get("currency", "USD")

                    conn.execute(
                        "INSERT INTO price_cache (symbol, price, change_pct, currency, updated_at) "
                        "VALUES (?, ?, ?, ?, datetime('now')) "
                        "ON CONFLICT(symbol) DO UPDATE SET price=excluded.price, change_pct=excluded.change_pct, "
                        "currency=excluded.currency, updated_at=excluded.updated_at",
                        (symbol, round(price, 2), round(change_pct, 2), currency)
                    )

                    results[symbol] = {
                        "symbol": symbol,
                        "price": round(price, 2),
                        "change_pct": round(change_pct, 2),
                        "currency": currency,
                        "cached": False,
                    }
                except Exception:
                    results[symbol] = {"symbol": symbol, "price": 0, "change_pct": 0, "currency": "USD", "error": True}
            conn.commit()
        except Exception:
            for symbol in stale:
                results[symbol] = {"symbol": symbol, "price": 0, "change_pct": 0, "currency": "USD", "error": True}

    conn.close()
    return results


def get_fx_rate(from_currency: str = "USD", to_currency: str = "CAD") -> float:
    """Get FX rate between two currencies."""
    if from_currency == to_currency:
        return 1.0
    symbol = f"{from_currency}{to_currency}=X"
    result = get_price(symbol)
    return result["price"] if result["price"] > 0 else 1.0
