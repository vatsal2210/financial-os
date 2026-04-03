"""SQLite database setup and models for Finance OS."""
import sqlite3
import os
import sys
import json
from pathlib import Path
from datetime import datetime

# Resolve base path for templates/static (works in PyInstaller bundles)
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).parent

TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
SAMPLES_DIR = BASE_DIR / "samples"

# Data directory: ~/.financeos/
DATA_DIR = Path.home() / ".financeos"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "finance.db"
UPLOADS_DIR = DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

def get_db() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    """Create all tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
        -- User settings (API keys, preferences)
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- Brokerage accounts
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            brokerage TEXT NOT NULL,
            account_type TEXT,  -- TFSA, RRSP, Individual, etc.
            currency TEXT DEFAULT 'USD',
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- Normalized transactions from any brokerage
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER REFERENCES accounts(id),
            date TEXT NOT NULL,
            type TEXT NOT NULL,  -- buy, sell, dividend, deposit, withdrawal, fee, transfer, split
            symbol TEXT,
            description TEXT,
            quantity REAL,
            price REAL,
            amount REAL NOT NULL,  -- total value (negative for buys, positive for sells/dividends)
            currency TEXT DEFAULT 'USD',
            fees REAL DEFAULT 0,
            raw_data TEXT,  -- original CSV row as JSON for audit trail
            import_batch TEXT,  -- links transactions from same import
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- Current holdings (calculated from transactions or imported)
        CREATE TABLE IF NOT EXISTS holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER REFERENCES accounts(id),
            symbol TEXT NOT NULL,
            quantity REAL NOT NULL,
            avg_cost REAL,
            currency TEXT DEFAULT 'USD',
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(account_id, symbol)
        );

        -- Watchlist items
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL UNIQUE,
            target_price REAL,
            notes TEXT,
            topics TEXT,  -- JSON array of topic tags
            added_at TEXT DEFAULT (datetime('now'))
        );

        -- Topics of interest for news/scanning
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            keywords TEXT,  -- JSON array of search keywords
            enabled INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- AI chat history (for natural language queries)
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,  -- user or assistant
            content TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- Import history
        CREATE TABLE IF NOT EXISTS imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            brokerage TEXT NOT NULL,
            account_id INTEGER REFERENCES accounts(id),
            rows_imported INTEGER DEFAULT 0,
            status TEXT DEFAULT 'completed',
            imported_at TEXT DEFAULT (datetime('now'))
        );

        -- Price cache (avoid hammering Yahoo Finance)
        CREATE TABLE IF NOT EXISTS price_cache (
            symbol TEXT PRIMARY KEY,
            price REAL NOT NULL,
            change_pct REAL,
            currency TEXT DEFAULT 'USD',
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- Feed entries (scan results, alerts, news)
        CREATE TABLE IF NOT EXISTS feed (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,  -- mover, alert, news, scan
            symbol TEXT,
            title TEXT NOT NULL,
            detail TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_transactions_symbol ON transactions(symbol);
        CREATE INDEX IF NOT EXISTS idx_feed_created ON feed(created_at);
        CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date);
        CREATE INDEX IF NOT EXISTS idx_transactions_account ON transactions(account_id);
        CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions(type);
    """)
    conn.commit()
    conn.close()

# --- Helper functions ---

def get_setting(key: str, default: str = "") -> str:
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value)
    )
    conn.commit()
    conn.close()

def is_onboarded() -> bool:
    return get_setting("onboarded") == "true"
