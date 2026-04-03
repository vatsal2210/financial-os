"""BYOK AI client — supports Claude and OpenAI for natural language queries."""
import json
from database import get_db, get_setting


def get_ai_provider() -> dict:
    """Get the configured AI provider and key."""
    provider = get_setting("ai_provider", "none")
    key = get_setting("ai_api_key", "")
    return {"provider": provider, "key": key, "configured": bool(key)}


def query_portfolio(question: str) -> str:
    """Answer a natural language question about the user's portfolio data."""
    config = get_ai_provider()
    if not config["configured"]:
        return "Please configure your AI API key in Settings to use natural language queries."

    # Gather context from local database
    conn = get_db()

    # Get summary stats
    accounts = conn.execute("SELECT * FROM accounts").fetchall()
    tx_summary = conn.execute("""
        SELECT type, COUNT(*) as count, COALESCE(SUM(ABS(amount)), 0) as total
        FROM transactions GROUP BY type
    """).fetchall()
    holdings = conn.execute("""
        SELECT h.symbol, h.quantity, h.avg_cost, a.name as account_name, a.currency
        FROM holdings h JOIN accounts a ON h.account_id = a.id
        WHERE h.quantity > 0
    """).fetchall()
    recent_tx = conn.execute("""
        SELECT date, type, symbol, quantity, price, amount
        FROM transactions ORDER BY date DESC LIMIT 50
    """).fetchall()
    conn.close()

    # Build context
    context = _build_context(accounts, tx_summary, holdings, recent_tx)

    # Call the appropriate AI provider
    if config["provider"] == "claude":
        return _query_claude(question, context, config["key"])
    elif config["provider"] == "openai":
        return _query_openai(question, context, config["key"])
    else:
        return "Unknown AI provider. Please configure Claude or OpenAI in Settings."


def _build_context(accounts, tx_summary, holdings, recent_tx) -> str:
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

    if holdings:
        parts.append("\n### Current Holdings")
        for h in holdings:
            parts.append(
                f"- {h['symbol']}: {h['quantity']} shares @ ${h['avg_cost']:.2f} avg "
                f"in {h['account_name']} ({h['currency']})"
            )

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
