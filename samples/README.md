# Sample Data for Testing

Each folder contains a sample CSV matching that brokerage's export format.
Use these to test the import flow without needing real brokerage data.

| Folder | Brokerage | File | Positions |
|--------|-----------|------|-----------|
| `robinhood/` | Robinhood | activities.csv | AAPL, NVDA, MSFT, TSLA, AMZN, GOOGL, META, AMD, PLTR |
| `fidelity/` | Fidelity | activities.csv | VTI, VXUS, BND, QQQ, SCHD |
| `schwab/` | Charles Schwab | transactions.csv | SPY, AAPL, COST, V, JPM, AVGO, LLY |
| `wealthsimple/` | Wealthsimple (Canada) | activities.csv | SHOP, CNR, VFV, VDY, TD, NVDA, ENB |
| `interactive_brokers/` | Interactive Brokers | trades.csv | INTC, BABA, TSM, ASML, MRVL, MU, QCOM |
| `generic/` | Any / Unknown | my_trades.csv | SOFI, COIN, SQ, ARKK, HOOD, MSTR, NU |

## To test

1. Start the app: `python main.py`
2. On the onboarding screen, select a brokerage
3. Upload the matching sample CSV
4. Review and confirm the import

## Your own files

Drop your own brokerage CSVs into `../uploads/` for safekeeping, then import them through the app UI.
