"""BYOK AI client — supports Claude and OpenAI for natural language queries."""
import os
from database import get_db, get_setting

# Load .env if present (for local dev — keys can also be set via Settings UI)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def get_ai_provider() -> dict:
    """Get the configured AI provider and key.
    Priority: Settings UI (SQLite) > environment variables.
    """
    provider = get_setting("ai_provider", "")
    key = get_setting("ai_api_key", "")

    # Fallback to env vars if nothing in Settings
    if not key:
        env_claude = os.environ.get("ANTHROPIC_API_KEY", "")
        env_openai = os.environ.get("OPENAI_API_KEY", "")
        if env_claude:
            provider = "claude"
            key = env_claude
        elif env_openai:
            provider = "openai"
            key = env_openai

    if not provider and key:
        provider = "claude" if "ant" in key else "openai"

    return {"provider": provider or "none", "key": key, "configured": bool(key)}


def query_portfolio(question: str) -> str:
    """Answer a natural language question about the user's portfolio data."""
    config = get_ai_provider()
    if not config["configured"]:
        return "No API key found. Add one in Settings, or set ANTHROPIC_API_KEY / OPENAI_API_KEY in your environment."

    # Gather context from local database
    conn = get_db()

    accounts = conn.execute("SELECT * FROM accounts").fetchall()
    tx_summary = conn.execute("""
        SELECT type, COUNT(*) as count, COALESCE(SUM(ABS(amount)), 0) as total
        FROM transactions GROUP BY type
    """).fetchall()

    # Calculate holdings from transactions (not the empty holdings table)
    held_symbols = conn.execute("""
        SELECT symbol,
               SUM(CASE WHEN type='buy' THEN quantity ELSE 0 END) as bought,
               SUM(CASE WHEN type='sell' THEN quantity ELSE 0 END) as sold
        FROM transactions
        WHERE symbol IS NOT NULL AND type IN ('buy', 'sell')
        GROUP BY symbol
        HAVING bought - sold > 0.001
    """).fetchall()

    recent_tx = conn.execute("""
        SELECT date, type, symbol, quantity, price, amount
        FROM transactions ORDER BY date DESC LIMIT 50
    """).fetchall()

    # Watchlist
    watchlist = conn.execute("SELECT symbol, target_price, notes FROM watchlist").fetchall()

    conn.close()

    context = _build_context(accounts, tx_summary, held_symbols, recent_tx, watchlist)

    if config["provider"] == "claude":
        return _query_claude(question, context, config["key"])
    elif config["provider"] == "openai":
        return _query_openai(question, context, config["key"])
    else:
        return "Unknown AI provider. Configure Claude or OpenAI in Settings."


def _build_context(accounts, tx_summary, held_symbols, recent_tx, watchlist) -> str:
    """Build a structured context string from portfolio data."""
    parts = ["## Your Portfolio Data\n"]

    if accounts:
        parts.append("### Accounts")
        for a in accounts:
            parts.append(f"- {a['name']} ({a['brokerage']}, {a['account_type']}, {a['currency']})")

    if tx_summary:
        parts.append("\n### Transaction Summary")
        for t in tx_summary:
            parts.append(f"- {t['type']}: {t['count']} transactions, total ${t['total']:,.2f}")

    if held_symbols:
        parts.append("\n### Current Holdings (calculated)")
        for h in held_symbols:
            net_qty = (h['bought'] or 0) - (h['sold'] or 0)
            parts.append(f"- {h['symbol']}: {net_qty:.2f} shares held")

    if watchlist:
        parts.append("\n### Watchlist")
        for w in watchlist:
            target = f" (target: ${w['target_price']:.2f})" if w['target_price'] else ""
            notes = f" — {w['notes']}" if w['notes'] else ""
            parts.append(f"- {w['symbol']}{target}{notes}")

    if recent_tx:
        parts.append("\n### Recent Transactions (last 50)")
        for t in recent_tx:
            symbol = t['symbol'] or ''
            parts.append(
                f"- {t['date']} {t['type']} {symbol} "
                f"qty={t['quantity'] or ''} price=${t['price'] or ''} "
                f"amount=${t['amount'] or ''}"
            )

    return "\n".join(parts)


def _query_claude(question: str, context: str, api_key: str) -> str:
    """Query Claude API."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=(
                "You are a personal finance assistant. Answer questions about the user's "
                "portfolio using ONLY the data provided. Be concise and specific with numbers. "
                "If the data doesn't contain enough information to answer, say so."
            ),
            messages=[
                {"role": "user", "content": f"{context}\n\n---\n\nQuestion: {question}"}
            ],
        )
        return response.content[0].text
    except Exception as e:
        return f"Error querying Claude: {str(e)}"


def _query_openai(question: str, context: str, api_key: str) -> str:
    """Query OpenAI API."""
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=1024,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a personal finance assistant. Answer questions about the user's "
                        "portfolio using ONLY the data provided. Be concise and specific with numbers. "
                        "If the data doesn't contain enough information to answer, say so."
                    ),
                },
                {"role": "user", "content": f"{context}\n\n---\n\nQuestion: {question}"},
            ],
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error querying OpenAI: {str(e)}"
