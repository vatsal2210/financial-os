# Finance OS

**Local-first personal finance intelligence. Your data never leaves your machine.**

## Quick Start

### macOS (App Bundle)
Double-click `Finance OS.app` — that's it. Opens in your browser at localhost:3001.

### macOS / Linux (Source)
```bash
bash install.sh
```
Then run: `~/.financeos-app/launch.sh` (or just `financeos` if symlink worked)

### Windows (Source)
```
install.bat
```
Then run: `%USERPROFILE%\.financeos-app\FinanceOS.bat`

### Manual (Any OS)
```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## What It Does

- **Import** your brokerage CSV (Robinhood, Fidelity, Schwab, Wealthsimple, Interactive Brokers, or any CSV)
- **Dashboard** with live prices, P&L, allocation breakdown
- **Holdings** calculated from your transaction history (FIFO cost basis)
- **Watchlist** with target prices and topics of interest
- **Feed** with live price tracking for held + watched symbols
- **Ask AI** — natural language questions about your portfolio (bring your own Claude or OpenAI key)
- **Portfolio X-Ray** — instant health check (concentration, risk, returns grading)

## Your Data

All data is stored locally at `~/.financeos/finance.db` (SQLite).

- No cloud. No accounts. No telemetry.
- API keys (if you add one for AI features) are stored locally.
- AI queries send portfolio context to your chosen provider — data is not stored by them.

## Sample Data

Test with pre-made CSVs in `samples/`:
- `samples/robinhood/activities.csv`
- `samples/fidelity/activities.csv`
- `samples/schwab/transactions.csv`
- `samples/wealthsimple/activities.csv`
- `samples/interactive_brokers/trades.csv`
- `samples/generic/my_trades.csv`

## Tech

- Python + FastAPI + SQLite + Jinja2
- Yahoo Finance for live prices (public, no auth)
- 74 tests (`python -m pytest tests/ -v`)
