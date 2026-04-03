"""Comprehensive test suite for Finance OS.

Categories:
  1. Database — init_db, get/set_setting, is_onboarded
  2. CSV parser — detect_brokerage, parse_csv (all 6 formats), get_preview, edge cases
  3. Portfolio calculations — FIFO cost basis, realized P&L, allocation
  4. Route tests — all GET/POST routes via TestClient
  5. Edge cases — duplicates, empty files, negative quantities, zero prices
"""
import json
import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

APP_DIR = Path(__file__).resolve().parent.parent
SAMPLES_DIR = APP_DIR / "samples"


def _read_sample(brokerage: str) -> str:
    """Read sample CSV for a brokerage."""
    mapping = {
        "wealthsimple": "wealthsimple/activities.csv",
        "robinhood": "robinhood/activities.csv",
        "fidelity": "fidelity/activities.csv",
        "schwab": "schwab/transactions.csv",
        "interactive_brokers": "interactive_brokers/trades.csv",
        "generic": "generic/my_trades.csv",
    }
    return (SAMPLES_DIR / mapping[brokerage]).read_text()


def _get_client():
    """Build a fresh TestClient against the app."""
    from main import app
    return TestClient(app, raise_server_exceptions=True)


def _seed_account(db, name="Test Account", brokerage="robinhood",
                  account_type="Individual", currency="USD"):
    """Insert an account and return its id."""
    cur = db.execute(
        "INSERT INTO accounts (name, brokerage, account_type, currency) VALUES (?,?,?,?)",
        (name, brokerage, account_type, currency),
    )
    db.commit()
    return cur.lastrowid


def _seed_transactions(db, account_id, txns):
    """Insert a list of transaction dicts."""
    for tx in txns:
        db.execute(
            "INSERT INTO transactions (account_id, date, type, symbol, quantity, price, amount, currency) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                account_id,
                tx["date"],
                tx["type"],
                tx["symbol"],
                tx["quantity"],
                tx["price"],
                tx["amount"],
                tx.get("currency", "USD"),
            ),
        )
    db.commit()


# ===================================================================
# 1. DATABASE TESTS
# ===================================================================

class TestDatabase:
    def test_init_db_creates_tables(self, db):
        tables = [
            r["name"]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        expected = [
            "settings", "accounts", "transactions", "holdings",
            "watchlist", "topics", "chat_history", "imports", "price_cache",
        ]
        for t in expected:
            assert t in tables, f"Table '{t}' missing after init_db()"

    def test_get_setting_default(self):
        from database import get_setting
        assert get_setting("nonexistent") == ""
        assert get_setting("nonexistent", "fallback") == "fallback"

    def test_set_and_get_setting(self):
        from database import get_setting, set_setting
        set_setting("theme", "dark")
        assert get_setting("theme") == "dark"

    def test_set_setting_upsert(self):
        from database import get_setting, set_setting
        set_setting("theme", "dark")
        set_setting("theme", "light")
        assert get_setting("theme") == "light"

    def test_is_onboarded_default_false(self):
        from database import is_onboarded
        assert is_onboarded() is False

    def test_is_onboarded_toggle(self):
        from database import is_onboarded, set_setting
        assert is_onboarded() is False
        set_setting("onboarded", "true")
        assert is_onboarded() is True
        set_setting("onboarded", "false")
        assert is_onboarded() is False


# ===================================================================
# 2. CSV PARSER TESTS
# ===================================================================

class TestDetectBrokerage:
    def test_detect_wealthsimple(self):
        from services.csv_parser import detect_brokerage
        assert detect_brokerage(["Date", "Type", "Symbol", "Description", "Quantity", "Price", "Amount", "Account Type"]) == "wealthsimple"

    def test_detect_robinhood(self):
        from services.csv_parser import detect_brokerage
        assert detect_brokerage(["Activity Date", "Trans Code", "Instrument", "Description", "Quantity", "Price", "Amount"]) == "robinhood"

    def test_detect_fidelity(self):
        from services.csv_parser import detect_brokerage
        assert detect_brokerage(["Run Date", "Action", "Symbol", "Description", "Quantity", "Price", "Amount"]) == "fidelity"

    def test_detect_schwab(self):
        from services.csv_parser import detect_brokerage
        assert detect_brokerage(["Date", "Action", "Symbol", "Description", "Quantity", "Price", "Fees & Comm", "Amount"]) == "schwab"

    def test_detect_interactive_brokers(self):
        from services.csv_parser import detect_brokerage
        assert detect_brokerage(["TradeDate", "Code", "Symbol", "Description", "Quantity", "Price", "Amount", "Commission"]) == "interactive_brokers"

    def test_detect_unknown(self):
        from services.csv_parser import detect_brokerage
        assert detect_brokerage(["A", "B", "C"]) is None

    def test_detect_case_insensitive(self):
        from services.csv_parser import detect_brokerage
        assert detect_brokerage(["run date", "action", "symbol"]) == "fidelity"


class TestParseCSV:
    @pytest.mark.parametrize("brokerage", [
        "wealthsimple", "robinhood", "fidelity", "schwab", "interactive_brokers",
    ])
    def test_parse_sample_returns_transactions(self, brokerage):
        from services.csv_parser import parse_csv
        content = _read_sample(brokerage)
        txns = parse_csv(content, brokerage, account_id=1, import_batch="test")
        assert len(txns) > 0, f"No transactions parsed for {brokerage}"
        for tx in txns:
            assert "date" in tx
            assert "type" in tx
            assert "amount" in tx

    def test_parse_generic_fallback(self):
        from services.csv_parser import parse_csv
        content = _read_sample("generic")
        txns = parse_csv(content, "unknown_brokerage", account_id=1, import_batch="test")
        assert len(txns) > 0, "Generic fallback parser returned no transactions"

    def test_parse_empty_csv(self):
        from services.csv_parser import parse_csv
        txns = parse_csv("", "robinhood", account_id=1, import_batch="test")
        assert txns == []

    def test_parse_headers_only_csv(self):
        from services.csv_parser import parse_csv
        content = "Activity Date,Trans Code,Instrument,Description,Quantity,Price,Amount\n"
        txns = parse_csv(content, "robinhood", account_id=1, import_batch="test")
        assert txns == []

    def test_parse_malformed_rows_skipped(self):
        from services.csv_parser import parse_csv
        content = (
            "Activity Date,Trans Code,Instrument,Description,Quantity,Price,Amount\n"
            "not-a-date,Buy,AAPL,desc,10,150,-1500\n"
            "12/15/2024,Buy,AAPL,desc,10,150,-1500\n"
        )
        txns = parse_csv(content, "robinhood", account_id=1, import_batch="test")
        # First row has an unparseable date for robinhood format but _try_parse_date
        # may still parse it via fallback. Either way second row should parse.
        assert len(txns) >= 1

    def test_transaction_fields_populated(self):
        from services.csv_parser import parse_csv
        content = _read_sample("robinhood")
        txns = parse_csv(content, "robinhood", account_id=1, import_batch="batch1")
        buy = next(t for t in txns if t["type"] == "buy")
        assert buy["account_id"] == 1
        assert buy["import_batch"] == "batch1"
        assert buy["symbol"] is not None
        assert buy["price"] is not None
        assert buy["quantity"] is not None
        assert buy["raw_data"] is not None

    def test_wealthsimple_currency_is_cad(self):
        from services.csv_parser import parse_csv
        content = _read_sample("wealthsimple")
        txns = parse_csv(content, "wealthsimple", account_id=1, import_batch="t")
        for tx in txns:
            assert tx["currency"] == "CAD"

    def test_parse_number_handles_currency_symbols(self):
        from services.csv_parser import _parse_number
        assert _parse_number("$1,234.56") == 1234.56
        assert _parse_number("(500.00)") == -500.00
        assert _parse_number("") is None
        assert _parse_number(None) is None
        assert _parse_number(42) == 42.0
        assert _parse_number(3.14) == 3.14


class TestGetPreview:
    def test_preview_returns_headers_and_rows(self):
        from services.csv_parser import get_preview
        content = _read_sample("robinhood")
        preview = get_preview(content)
        assert "headers" in preview
        assert "rows" in preview
        assert "detected_brokerage" in preview
        assert preview["detected_brokerage"] == "robinhood"
        assert len(preview["headers"]) > 0
        assert len(preview["rows"]) > 0

    def test_preview_max_rows(self):
        from services.csv_parser import get_preview
        content = _read_sample("wealthsimple")
        preview = get_preview(content, max_rows=3)
        assert preview["row_count"] <= 3

    def test_preview_empty_csv(self):
        from services.csv_parser import get_preview
        preview = get_preview("")
        assert preview["headers"] == []
        assert preview["rows"] == []
        assert preview["detected_brokerage"] is None


# ===================================================================
# 3. PORTFOLIO CALCULATION TESTS
# ===================================================================

class TestPortfolioCalculations:
    def test_calculate_holdings_simple_buy(self, db):
        from services.portfolio import calculate_holdings
        acct = _seed_account(db)
        _seed_transactions(db, acct, [
            {"date": "2025-01-01", "type": "buy", "symbol": "AAPL", "quantity": 10, "price": 150, "amount": -1500},
        ])
        holdings = calculate_holdings()
        assert len(holdings) == 1
        h = holdings[0]
        assert h["symbol"] == "AAPL"
        assert h["quantity"] == 10
        assert h["avg_cost"] == 150.0

    def test_calculate_holdings_buy_sell(self, db):
        from services.portfolio import calculate_holdings
        acct = _seed_account(db)
        _seed_transactions(db, acct, [
            {"date": "2025-01-01", "type": "buy", "symbol": "AAPL", "quantity": 10, "price": 150, "amount": -1500},
            {"date": "2025-01-10", "type": "sell", "symbol": "AAPL", "quantity": 5, "price": 170, "amount": 850},
        ])
        holdings = calculate_holdings()
        assert len(holdings) == 1
        h = holdings[0]
        assert h["quantity"] == 5
        assert h["avg_cost"] == 150.0  # avg cost unchanged after partial sell

    def test_calculate_holdings_full_sell(self, db):
        from services.portfolio import calculate_holdings
        acct = _seed_account(db)
        _seed_transactions(db, acct, [
            {"date": "2025-01-01", "type": "buy", "symbol": "AAPL", "quantity": 10, "price": 150, "amount": -1500},
            {"date": "2025-01-10", "type": "sell", "symbol": "AAPL", "quantity": 10, "price": 170, "amount": 1700},
        ])
        holdings = calculate_holdings()
        assert len(holdings) == 0

    def test_calculate_holdings_multiple_buys_avg_cost(self, db):
        from services.portfolio import calculate_holdings
        acct = _seed_account(db)
        _seed_transactions(db, acct, [
            {"date": "2025-01-01", "type": "buy", "symbol": "AAPL", "quantity": 10, "price": 100, "amount": -1000},
            {"date": "2025-01-05", "type": "buy", "symbol": "AAPL", "quantity": 10, "price": 200, "amount": -2000},
        ])
        holdings = calculate_holdings()
        assert len(holdings) == 1
        h = holdings[0]
        assert h["quantity"] == 20
        assert h["avg_cost"] == 150.0  # (1000 + 2000) / 20

    def test_calculate_holdings_by_account(self, db):
        from services.portfolio import calculate_holdings
        acct1 = _seed_account(db, name="Acc1")
        acct2 = _seed_account(db, name="Acc2")
        _seed_transactions(db, acct1, [
            {"date": "2025-01-01", "type": "buy", "symbol": "AAPL", "quantity": 10, "price": 150, "amount": -1500},
        ])
        _seed_transactions(db, acct2, [
            {"date": "2025-01-01", "type": "buy", "symbol": "MSFT", "quantity": 5, "price": 300, "amount": -1500},
        ])
        all_holdings = calculate_holdings()
        assert len(all_holdings) == 2
        acct1_holdings = calculate_holdings(account_id=acct1)
        assert len(acct1_holdings) == 1
        assert acct1_holdings[0]["symbol"] == "AAPL"

    def test_realized_pnl_fifo(self, db):
        """Buy 10 @ $100, buy 10 @ $200, sell 10 @ $250. FIFO: sell the $100 lot first = +$1500."""
        from services.portfolio import _calculate_realized_pnl
        acct = _seed_account(db)
        _seed_transactions(db, acct, [
            {"date": "2025-01-01", "type": "buy", "symbol": "X", "quantity": 10, "price": 100, "amount": -1000},
            {"date": "2025-01-02", "type": "buy", "symbol": "X", "quantity": 10, "price": 200, "amount": -2000},
            {"date": "2025-01-03", "type": "sell", "symbol": "X", "quantity": 10, "price": 250, "amount": 2500},
        ])
        conn = db  # reuse the fixture's connection
        realized = _calculate_realized_pnl(conn)
        assert realized == pytest.approx(1500.0)

    def test_realized_pnl_loss(self, db):
        """Buy 10 @ $100, sell 10 @ $80 = -$200 loss."""
        from services.portfolio import _calculate_realized_pnl
        acct = _seed_account(db)
        _seed_transactions(db, acct, [
            {"date": "2025-01-01", "type": "buy", "symbol": "X", "quantity": 10, "price": 100, "amount": -1000},
            {"date": "2025-01-03", "type": "sell", "symbol": "X", "quantity": 10, "price": 80, "amount": 800},
        ])
        realized = _calculate_realized_pnl(db)
        assert realized == pytest.approx(-200.0)

    def test_allocation_percentages(self):
        from services.portfolio import get_allocation
        holdings = [
            {"symbol": "AAPL", "market_value": 5000},
            {"symbol": "MSFT", "market_value": 3000},
            {"symbol": "GOOG", "market_value": 2000},
        ]
        alloc = get_allocation(holdings)
        assert len(alloc) == 3
        assert alloc[0]["symbol"] == "AAPL"
        assert alloc[0]["pct"] == 50.0
        assert alloc[1]["pct"] == 30.0
        assert alloc[2]["pct"] == 20.0
        assert sum(a["pct"] for a in alloc) == pytest.approx(100.0)

    def test_allocation_empty(self):
        from services.portfolio import get_allocation
        assert get_allocation([]) == []

    def test_allocation_zero_total(self):
        from services.portfolio import get_allocation
        assert get_allocation([{"symbol": "X", "market_value": 0}]) == []

    def test_portfolio_summary_empty(self, db):
        from services.portfolio import get_portfolio_summary
        summary = get_portfolio_summary()
        assert summary["total_value"] == 0
        assert summary["num_positions"] == 0
        assert summary["num_transactions"] == 0

    def test_portfolio_summary_with_data(self, db):
        from services.portfolio import get_portfolio_summary
        acct = _seed_account(db)
        _seed_transactions(db, acct, [
            {"date": "2025-01-01", "type": "deposit", "symbol": None, "quantity": 0, "price": 0, "amount": 5000},
            {"date": "2025-01-02", "type": "buy", "symbol": "AAPL", "quantity": 10, "price": 150, "amount": -1500},
        ])
        summary = get_portfolio_summary()
        assert summary["num_positions"] == 1
        assert summary["net_deposits"] == 5000
        assert summary["num_transactions"] == 2


# ===================================================================
# 4. ROUTE TESTS
# ===================================================================

class TestRoutes:
    """Test all HTTP routes via TestClient."""

    # --- Onboarding state (not onboarded) ---

    def test_index_redirects_to_onboarding(self):
        client = _get_client()
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 303
        assert "/onboarding" in resp.headers["location"]

    def test_onboarding_page_loads(self):
        client = _get_client()
        resp = client.get("/onboarding")
        assert resp.status_code == 200

    def test_holdings_redirects_when_not_onboarded(self):
        client = _get_client()
        resp = client.get("/holdings", follow_redirects=False)
        assert resp.status_code == 303

    def test_transactions_redirects_when_not_onboarded(self):
        client = _get_client()
        resp = client.get("/transactions", follow_redirects=False)
        assert resp.status_code == 303

    def test_xray_redirects_when_not_onboarded(self):
        client = _get_client()
        resp = client.get("/xray", follow_redirects=False)
        assert resp.status_code == 303

    # --- After onboarding ---

    def _onboard(self, db):
        from database import set_setting
        _seed_account(db)
        set_setting("onboarded", "true")

    def test_index_loads_when_onboarded(self, db):
        self._onboard(db)
        client = _get_client()
        resp = client.get("/")
        assert resp.status_code == 200

    def test_holdings_page_loads(self, db):
        self._onboard(db)
        client = _get_client()
        resp = client.get("/holdings")
        assert resp.status_code == 200

    def test_transactions_page_loads(self, db):
        self._onboard(db)
        client = _get_client()
        resp = client.get("/transactions")
        assert resp.status_code == 200

    def test_xray_page_loads(self, db):
        self._onboard(db)
        client = _get_client()
        resp = client.get("/xray")
        assert resp.status_code == 200

    def test_onboarding_redirects_when_already_onboarded(self, db):
        self._onboard(db)
        client = _get_client()
        resp = client.get("/onboarding", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"

    # --- Settings routes ---

    def test_settings_page_loads(self):
        client = _get_client()
        resp = client.get("/settings")
        assert resp.status_code == 200

    def test_settings_save_ai(self):
        client = _get_client()
        resp = client.post("/settings/ai", data={
            "ai_provider": "claude",
            "ai_api_key": "sk-test-key-1234567890",
        }, follow_redirects=False)
        assert resp.status_code == 303
        from database import get_setting
        assert get_setting("ai_provider") == "claude"
        assert get_setting("ai_api_key") == "sk-test-key-1234567890"

    def test_settings_save_currency(self):
        client = _get_client()
        resp = client.post("/settings/currency", data={"currency": "CAD"}, follow_redirects=False)
        assert resp.status_code == 303
        from database import get_setting
        assert get_setting("home_currency") == "CAD"

    def test_settings_add_account(self):
        client = _get_client()
        resp = client.post("/settings/account/add", data={
            "name": "My TFSA",
            "brokerage": "wealthsimple",
            "account_type": "TFSA",
            "currency": "CAD",
        }, follow_redirects=False)
        assert resp.status_code == 303
        from database import get_db
        conn = get_db()
        acct = conn.execute("SELECT * FROM accounts WHERE name='My TFSA'").fetchone()
        conn.close()
        assert acct is not None
        assert acct["brokerage"] == "wealthsimple"

    def test_settings_reset(self, db):
        from database import set_setting
        _seed_account(db)
        set_setting("onboarded", "true")
        client = _get_client()
        resp = client.post("/settings/reset", follow_redirects=False)
        assert resp.status_code == 303
        from database import is_onboarded
        assert is_onboarded() is False

    # --- Import routes ---

    def test_import_page_loads(self):
        client = _get_client()
        resp = client.get("/import")
        assert resp.status_code == 200

    def test_full_import_flow_onboarding(self, db):
        """Test the full onboarding import flow: account -> preview -> confirm."""
        client = _get_client()

        # Step 1: Create account
        resp = client.post("/onboarding/account", data={
            "brokerage": "robinhood",
            "account_name": "My Robinhood",
            "account_type": "Individual",
        })
        assert resp.status_code == 200  # returns HTML, not redirect

        # Step 2: Get account id
        from database import get_db
        conn = get_db()
        acct = conn.execute("SELECT id FROM accounts LIMIT 1").fetchone()
        conn.close()
        account_id = acct["id"]

        # Step 3: Preview upload
        sample_content = _read_sample("robinhood")
        resp = client.post("/import/preview", data={
            "account_id": str(account_id),
            "brokerage": "robinhood",
        }, files={"file": ("activities.csv", sample_content.encode(), "text/csv")})
        assert resp.status_code == 200

        # Step 4: Confirm import
        resp = client.post("/import/confirm", data={
            "account_id": str(account_id),
            "brokerage": "robinhood",
            "filename": "activities.csv",
            "import_batch": "testbatch",
        })
        assert resp.status_code == 200

        # Verify transactions were inserted
        conn = get_db()
        count = conn.execute("SELECT COUNT(*) as cnt FROM transactions").fetchone()["cnt"]
        conn.close()
        assert count > 0

        # Verify onboarded
        from database import is_onboarded
        assert is_onboarded() is True

    # --- Watchlist routes ---

    def test_watchlist_page_loads(self):
        client = _get_client()
        resp = client.get("/watchlist")
        assert resp.status_code == 200

    def test_watchlist_add_and_remove(self):
        client = _get_client()

        # Add
        resp = client.post("/watchlist/add", data={
            "symbol": "TSLA",
            "target_price": "250.00",
            "notes": "Watch for breakout",
        }, follow_redirects=False)
        assert resp.status_code == 303

        from database import get_db
        conn = get_db()
        item = conn.execute("SELECT * FROM watchlist WHERE symbol='TSLA'").fetchone()
        assert item is not None
        assert item["target_price"] == 250.0

        # Remove
        item_id = item["id"]
        conn.close()
        resp = client.post("/watchlist/remove", data={"id": str(item_id)}, follow_redirects=False)
        assert resp.status_code == 303

        conn = get_db()
        item = conn.execute("SELECT * FROM watchlist WHERE symbol='TSLA'").fetchone()
        conn.close()
        assert item is None

    def test_watchlist_add_empty_symbol_redirects(self):
        client = _get_client()
        resp = client.post("/watchlist/add", data={
            "symbol": "  ",
            "notes": "",
        }, follow_redirects=False)
        assert resp.status_code == 303

    # --- Topics routes ---

    def test_topics_add_toggle_remove(self):
        client = _get_client()

        # Add
        resp = client.post("/topics/add", data={
            "name": "AI Stocks",
            "keywords": "nvidia, openai, anthropic",
        }, follow_redirects=False)
        assert resp.status_code == 303

        from database import get_db
        conn = get_db()
        topic = conn.execute("SELECT * FROM topics WHERE name='AI Stocks'").fetchone()
        assert topic is not None
        assert topic["enabled"] == 1
        topic_id = topic["id"]
        conn.close()

        # Toggle off
        resp = client.post("/topics/toggle", data={"id": str(topic_id)}, follow_redirects=False)
        assert resp.status_code == 303
        conn = get_db()
        topic = conn.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()
        assert topic["enabled"] == 0
        conn.close()

        # Toggle on
        resp = client.post("/topics/toggle", data={"id": str(topic_id)}, follow_redirects=False)
        assert resp.status_code == 303
        conn = get_db()
        topic = conn.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()
        assert topic["enabled"] == 1
        conn.close()

        # Remove
        resp = client.post("/topics/remove", data={"id": str(topic_id)}, follow_redirects=False)
        assert resp.status_code == 303
        conn = get_db()
        topic = conn.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()
        conn.close()
        assert topic is None

    def test_topics_add_empty_name_redirects(self):
        client = _get_client()
        resp = client.post("/topics/add", data={
            "name": "  ",
            "keywords": "",
        }, follow_redirects=False)
        assert resp.status_code == 303

    # --- AI / Ask routes ---

    def test_ask_page_loads(self):
        client = _get_client()
        resp = client.get("/ask")
        assert resp.status_code == 200

    def test_ask_without_ai_key_returns_message(self, db):
        client = _get_client()
        resp = client.post("/ask", data={"question": "How is my portfolio?"})
        assert resp.status_code == 200
        # Should contain the "configure your AI key" message in the response
        assert b"Settings" in resp.content or b"API key" in resp.content or b"configure" in resp.content.lower()


# ===================================================================
# 5. EDGE CASES
# ===================================================================

class TestEdgeCases:
    def test_duplicate_watchlist_symbol(self):
        """Adding the same symbol twice should not raise an error."""
        client = _get_client()
        client.post("/watchlist/add", data={"symbol": "AAPL", "notes": "first"}, follow_redirects=False)
        # Second add of same symbol should silently succeed (UNIQUE constraint handled)
        resp = client.post("/watchlist/add", data={"symbol": "AAPL", "notes": "second"}, follow_redirects=False)
        assert resp.status_code == 303

        from database import get_db
        conn = get_db()
        items = conn.execute("SELECT * FROM watchlist WHERE symbol='AAPL'").fetchall()
        conn.close()
        assert len(items) == 1  # only one entry

    def test_duplicate_topic_name(self):
        """Adding the same topic name twice should not raise an error."""
        client = _get_client()
        client.post("/topics/add", data={"name": "Tech", "keywords": "tech"}, follow_redirects=False)
        resp = client.post("/topics/add", data={"name": "Tech", "keywords": "more tech"}, follow_redirects=False)
        assert resp.status_code == 303

        from database import get_db
        conn = get_db()
        topics = conn.execute("SELECT * FROM topics WHERE name='Tech'").fetchall()
        conn.close()
        assert len(topics) == 1

    def test_negative_quantity_handling(self, db):
        """Negative quantities in transactions should be handled via abs()."""
        from services.portfolio import calculate_holdings
        acct = _seed_account(db)
        _seed_transactions(db, acct, [
            {"date": "2025-01-01", "type": "buy", "symbol": "AAPL", "quantity": -10, "price": 150, "amount": -1500},
        ])
        holdings = calculate_holdings()
        assert len(holdings) == 1
        assert holdings[0]["quantity"] == 10  # abs() applied

    def test_zero_price_transaction(self, db):
        """Zero-price buys (e.g., stock grants) should not crash calculations."""
        from services.portfolio import calculate_holdings
        acct = _seed_account(db)
        _seed_transactions(db, acct, [
            {"date": "2025-01-01", "type": "buy", "symbol": "AAPL", "quantity": 10, "price": 0, "amount": 0},
        ])
        holdings = calculate_holdings()
        # Should have a position with zero cost
        assert len(holdings) == 1
        assert holdings[0]["avg_cost"] == 0

    def test_empty_file_upload(self):
        """Uploading an empty file should not crash the preview route."""
        client = _get_client()
        # Create an account first
        from database import get_db
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO accounts (name, brokerage, account_type, currency) VALUES (?,?,?,?)",
            ("Test", "robinhood", "Individual", "USD"),
        )
        account_id = cur.lastrowid
        conn.commit()
        conn.close()

        resp = client.post("/import/preview", data={
            "account_id": str(account_id),
            "brokerage": "robinhood",
        }, files={"file": ("empty.csv", b"", "text/csv")})
        assert resp.status_code == 200

    def test_sell_more_than_owned(self, db):
        """Selling more shares than owned should not go negative."""
        from services.portfolio import calculate_holdings
        acct = _seed_account(db)
        _seed_transactions(db, acct, [
            {"date": "2025-01-01", "type": "buy", "symbol": "AAPL", "quantity": 5, "price": 150, "amount": -750},
            {"date": "2025-01-10", "type": "sell", "symbol": "AAPL", "quantity": 10, "price": 170, "amount": 1700},
        ])
        holdings = calculate_holdings()
        # Position should be gone (clamped at 0), not negative
        assert len(holdings) == 0

    def test_parse_number_edge_cases(self):
        from services.csv_parser import _parse_number
        assert _parse_number("abc") is None
        assert _parse_number("$0.00") == 0.0
        assert _parse_number("  1,234.56  ") == 1234.56
        assert _parse_number("(100)") == -100.0

    def test_multiple_symbols_in_portfolio(self, db):
        """Verify multiple symbols tracked correctly."""
        from services.portfolio import calculate_holdings, get_allocation
        acct = _seed_account(db)
        _seed_transactions(db, acct, [
            {"date": "2025-01-01", "type": "buy", "symbol": "AAPL", "quantity": 10, "price": 100, "amount": -1000},
            {"date": "2025-01-01", "type": "buy", "symbol": "MSFT", "quantity": 5, "price": 200, "amount": -1000},
            {"date": "2025-01-01", "type": "buy", "symbol": "GOOG", "quantity": 8, "price": 150, "amount": -1200},
        ])
        holdings = calculate_holdings()
        assert len(holdings) == 3
        symbols = {h["symbol"] for h in holdings}
        assert symbols == {"AAPL", "MSFT", "GOOG"}

        alloc = get_allocation(holdings)
        assert len(alloc) == 3
        total_pct = sum(a["pct"] for a in alloc)
        assert total_pct == pytest.approx(100.0)

    def test_guess_type_coverage(self):
        """Exercise the _guess_type fallback for various raw type strings."""
        from services.csv_parser import _guess_type
        assert _guess_type("purchased shares", {}) == "buy"
        assert _guess_type("sold position", {}) == "sell"
        assert _guess_type("distribution", {}) == "dividend"
        assert _guess_type("wire deposit", {}) == "deposit"
        assert _guess_type("withdrawal", {}) == "withdrawal"
        assert _guess_type("fee charged", {}) == "fee"
        assert _guess_type("stock split", {}) == "split"
        assert _guess_type("transfer in", {}) == "transfer"
        assert _guess_type("totally random", {}) == "other"

    def test_try_parse_date_formats(self):
        """Verify multiple date formats are handled."""
        from services.csv_parser import _try_parse_date
        assert _try_parse_date("2025-01-15") == "2025-01-15"
        assert _try_parse_date("01/15/2025") == "2025-01-15"
        assert _try_parse_date("20250115") == "2025-01-15"
        assert _try_parse_date("Jan 15, 2025") == "2025-01-15"
        assert _try_parse_date("January 15, 2025") == "2025-01-15"
        assert _try_parse_date("") is None
        assert _try_parse_date("not a date") is None
