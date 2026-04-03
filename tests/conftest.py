"""Shared fixtures for Finance OS tests.

Every test gets its own temporary SQLite database so the real
~/.financeos/finance.db is never touched.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure the app package is importable
APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))


@pytest.fixture(autouse=True)
def _test_db(tmp_path, monkeypatch):
    """Redirect ALL database access to a temp file for every test."""
    test_db = tmp_path / "test_finance.db"
    test_uploads = tmp_path / "uploads"
    test_uploads.mkdir()

    import database
    monkeypatch.setattr(database, "DB_PATH", test_db)
    monkeypatch.setattr(database, "UPLOADS_DIR", test_uploads)
    database.init_db()
    yield test_db


@pytest.fixture()
def db():
    """Return a fresh database connection (uses the patched DB_PATH)."""
    from database import get_db
    conn = get_db()
    yield conn
    conn.close()


def _noop_prices_batch(symbols):
    """Return deterministic fake prices so tests never hit Yahoo Finance."""
    return {
        s: {"symbol": s, "price": 100.0, "change_pct": 1.5, "currency": "USD", "cached": True}
        for s in symbols
    }


def _noop_price(symbol):
    return {"symbol": symbol, "price": 100.0, "change_pct": 1.5, "currency": "USD", "cached": True}


@pytest.fixture(autouse=True)
def _mock_market(monkeypatch):
    """Prevent all Yahoo Finance calls during tests."""
    import services.market as mkt
    monkeypatch.setattr(mkt, "get_prices_batch", _noop_prices_batch)
    monkeypatch.setattr(mkt, "get_price", _noop_price)
    monkeypatch.setattr(mkt, "get_fx_rate", lambda *a, **kw: 1.37)
