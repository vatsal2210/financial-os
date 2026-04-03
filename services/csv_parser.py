"""Multi-brokerage CSV parser. Normalizes any brokerage export into unified transactions."""
import csv
import io
import json
from datetime import datetime
from typing import Optional

# Brokerage preset configurations
BROKERAGE_PRESETS = {
    "wealthsimple": {
        "name": "Wealthsimple",
        "country": "CA",
        "currency": "CAD",
        "columns": {
            "date": "Date",
            "type": "Type",
            "symbol": "Symbol",
            "description": "Description",
            "quantity": "Quantity",
            "price": "Price",
            "amount": "Amount",
        },
        "type_map": {
            "buy": "buy",
            "sell": "sell",
            "dividend": "dividend",
            "deposit": "deposit",
            "withdrawal": "withdrawal",
            "fee": "fee",
            "stock split": "split",
            "transfer in": "transfer",
            "transfer out": "transfer",
            "referral bonus": "deposit",
            "interest": "dividend",
        },
        "date_format": "%Y-%m-%d",
        "account_types": ["TFSA", "RRSP", "FHSA", "Personal", "RESP", "Crypto"],
    },
    "robinhood": {
        "name": "Robinhood",
        "country": "US",
        "currency": "USD",
        "columns": {
            "date": "Activity Date",
            "type": "Trans Code",
            "symbol": "Instrument",
            "description": "Description",
            "quantity": "Quantity",
            "price": "Price",
            "amount": "Amount",
        },
        "type_map": {
            "buy": "buy",
            "sell": "sell",
            "cdiv": "dividend",
            "ach": "deposit",
            "slip": "split",
            "fee": "fee",
        },
        "date_format": "%m/%d/%Y",
        "account_types": ["Individual", "Roth IRA", "Traditional IRA"],
    },
    "fidelity": {
        "name": "Fidelity",
        "country": "US",
        "currency": "USD",
        "columns": {
            "date": "Run Date",
            "type": "Action",
            "symbol": "Symbol",
            "description": "Description",
            "quantity": "Quantity",
            "price": "Price",
            "amount": "Amount",
        },
        "type_map": {
            "you bought": "buy",
            "you sold": "sell",
            "dividend received": "dividend",
            "reinvestment": "buy",
            "electronic funds transfer received": "deposit",
            "transferred": "transfer",
        },
        "date_format": "%m/%d/%Y",
        "account_types": ["Individual", "Roth IRA", "401k", "HSA"],
    },
    "schwab": {
        "name": "Charles Schwab",
        "country": "US",
        "currency": "USD",
        "columns": {
            "date": "Date",
            "type": "Action",
            "symbol": "Symbol",
            "description": "Description",
            "quantity": "Quantity",
            "price": "Price",
            "amount": "Amount",
            "fees": "Fees & Comm",
        },
        "type_map": {
            "buy": "buy",
            "sell": "sell",
            "cash dividend": "dividend",
            "qualified dividend": "dividend",
            "reinvest dividend": "buy",
            "journal": "transfer",
            "wire funds received": "deposit",
            "ach": "deposit",
        },
        "date_format": "%m/%d/%Y",
        "account_types": ["Individual", "Roth IRA", "Traditional IRA", "401k"],
    },
    "interactive_brokers": {
        "name": "Interactive Brokers",
        "country": "US",
        "currency": "USD",
        "columns": {
            "date": "TradeDate",
            "type": "Code",
            "symbol": "Symbol",
            "description": "Description",
            "quantity": "Quantity",
            "price": "Price",
            "amount": "Amount",
            "fees": "Commission",
        },
        "type_map": {
            "buy": "buy",
            "sell": "sell",
            "div": "dividend",
            "dep": "deposit",
            "with": "withdrawal",
        },
        "date_format": "%Y%m%d",
        "account_types": ["Individual", "IRA", "Joint"],
    },
}


def detect_brokerage(header_row: list[str]) -> Optional[str]:
    """Try to auto-detect brokerage from CSV headers."""
    headers_lower = [h.strip().lower() for h in header_row]

    # Wealthsimple has a distinctive "Account Type" column
    if "account type" in headers_lower and "symbol" in headers_lower:
        return "wealthsimple"

    # Robinhood uses "Trans Code" and "Instrument"
    if "trans code" in headers_lower or "instrument" in headers_lower:
        return "robinhood"

    # Fidelity uses "Run Date" and "Action"
    if "run date" in headers_lower:
        return "fidelity"

    # Schwab uses "Fees & Comm"
    if "fees & comm" in headers_lower:
        return "schwab"

    # IBKR uses "TradeDate"
    if "tradedate" in headers_lower:
        return "interactive_brokers"

    return None


def parse_csv(content: str, brokerage: str, account_id: int, import_batch: str) -> list[dict]:
    """Parse CSV content using brokerage preset and return normalized transactions."""
    preset = BROKERAGE_PRESETS.get(brokerage)

    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)

    if not rows:
        return []

    if not preset:
        # Generic parsing — try common column names
        return _parse_generic(rows, account_id, import_batch)

    return _parse_with_preset(rows, preset, account_id, import_batch)


def _parse_with_preset(rows: list[dict], preset: dict, account_id: int, import_batch: str) -> list[dict]:
    """Parse rows using a brokerage preset configuration."""
    col_map = preset["columns"]
    type_map = preset["type_map"]
    date_fmt = preset["date_format"]
    currency = preset["currency"]
    transactions = []

    for row in rows:
        # Find matching columns (case-insensitive, flexible)
        mapped = _flexible_column_match(row, col_map)

        if not mapped.get("date"):
            continue

        # Parse date
        try:
            date_str = mapped["date"].strip()
            parsed_date = datetime.strptime(date_str, date_fmt)
            date_normalized = parsed_date.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            # Try common fallback formats
            date_normalized = _try_parse_date(mapped.get("date", ""))
            if not date_normalized:
                continue

        # Map transaction type
        raw_type = (mapped.get("type") or "").strip().lower()
        tx_type = type_map.get(raw_type, _guess_type(raw_type, mapped))

        # Parse numeric fields
        quantity = _parse_number(mapped.get("quantity"))
        price = _parse_number(mapped.get("price"))
        amount = _parse_number(mapped.get("amount"))
        fees = _parse_number(mapped.get("fees", "0"))

        transactions.append({
            "account_id": account_id,
            "date": date_normalized,
            "type": tx_type,
            "symbol": (mapped.get("symbol") or "").strip().upper() or None,
            "description": (mapped.get("description") or "").strip() or None,
            "quantity": quantity,
            "price": price,
            "amount": amount or (quantity or 0) * (price or 0),
            "currency": currency,
            "fees": fees,
            "raw_data": json.dumps(dict(row)),
            "import_batch": import_batch,
        })

    return transactions


def _parse_generic(rows: list[dict], account_id: int, import_batch: str) -> list[dict]:
    """Best-effort parsing for unknown CSV formats."""
    if not rows:
        return []

    headers = list(rows[0].keys())

    # Try to identify columns by common names
    col_guesses = {
        "date": _find_column(headers, ["date", "trade date", "settlement date", "time", "timestamp"]),
        "type": _find_column(headers, ["type", "action", "trans code", "transaction", "activity"]),
        "symbol": _find_column(headers, ["symbol", "ticker", "instrument", "stock", "security"]),
        "description": _find_column(headers, ["description", "desc", "details", "memo", "notes"]),
        "quantity": _find_column(headers, ["quantity", "qty", "shares", "units"]),
        "price": _find_column(headers, ["price", "unit price", "cost", "rate"]),
        "amount": _find_column(headers, ["amount", "total", "value", "net amount", "proceeds"]),
        "fees": _find_column(headers, ["fees", "commission", "fee", "comm"]),
    }

    transactions = []
    for row in rows:
        date_val = row.get(col_guesses["date"], "") if col_guesses["date"] else ""
        date_normalized = _try_parse_date(date_val)
        if not date_normalized:
            continue

        raw_type = row.get(col_guesses["type"], "") if col_guesses["type"] else ""
        tx_type = _guess_type(raw_type.lower(), row)

        symbol = row.get(col_guesses["symbol"], "") if col_guesses["symbol"] else ""
        description = row.get(col_guesses["description"], "") if col_guesses["description"] else ""
        quantity = _parse_number(row.get(col_guesses["quantity"], "")) if col_guesses["quantity"] else None
        price = _parse_number(row.get(col_guesses["price"], "")) if col_guesses["price"] else None
        amount = _parse_number(row.get(col_guesses["amount"], "")) if col_guesses["amount"] else None
        fees = _parse_number(row.get(col_guesses["fees"], "0")) if col_guesses["fees"] else 0

        transactions.append({
            "account_id": account_id,
            "date": date_normalized,
            "type": tx_type,
            "symbol": symbol.strip().upper() or None,
            "description": description.strip() or None,
            "quantity": quantity,
            "price": price,
            "amount": amount or (quantity or 0) * (price or 0),
            "currency": "USD",
            "fees": fees,
            "raw_data": json.dumps(dict(row)),
            "import_batch": import_batch,
        })

    return transactions


def _flexible_column_match(row: dict, col_map: dict) -> dict:
    """Match columns flexibly — handles case differences and extra whitespace."""
    row_lower = {k.strip().lower(): v for k, v in row.items()}
    result = {}
    for key, expected_col in col_map.items():
        expected_lower = expected_col.strip().lower()
        result[key] = row_lower.get(expected_lower, "")
    return result


def _find_column(headers: list[str], candidates: list[str]) -> Optional[str]:
    """Find the first header that matches any candidate (case-insensitive)."""
    headers_lower = {h.strip().lower(): h for h in headers}
    for candidate in candidates:
        if candidate in headers_lower:
            return headers_lower[candidate]
    # Partial match fallback
    for candidate in candidates:
        for h_lower, h_orig in headers_lower.items():
            if candidate in h_lower:
                return h_orig
    return None


def _try_parse_date(date_str: str) -> Optional[str]:
    """Try multiple date formats and return YYYY-MM-DD or None."""
    if not date_str:
        return None
    date_str = date_str.strip()
    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%d/%m/%Y",
        "%Y%m%d",
        "%b %d, %Y",
        "%B %d, %Y",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _parse_number(val) -> Optional[float]:
    """Parse a numeric value, handling currency symbols and parentheses for negatives."""
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    # Remove currency symbols and commas
    s = s.replace("$", "").replace(",", "").replace(" ", "")
    # Handle parentheses for negative numbers: (100.00) → -100.00
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


def _guess_type(raw_type: str, row) -> str:
    """Best-effort guess at transaction type from raw string."""
    raw = raw_type.lower()
    if any(kw in raw for kw in ["buy", "purchased", "bought"]):
        return "buy"
    if any(kw in raw for kw in ["sell", "sold", "sale"]):
        return "sell"
    if any(kw in raw for kw in ["div", "dividend", "distribution", "interest"]):
        return "dividend"
    if any(kw in raw for kw in ["deposit", "ach", "wire", "fund", "contribution"]):
        return "deposit"
    if any(kw in raw for kw in ["withdraw", "disbursement"]):
        return "withdrawal"
    if any(kw in raw for kw in ["fee", "commission", "charge"]):
        return "fee"
    if any(kw in raw for kw in ["split"]):
        return "split"
    if any(kw in raw for kw in ["transfer", "journal"]):
        return "transfer"
    return "other"


def get_preview(content: str, max_rows: int = 10) -> dict:
    """Return a preview of the CSV: headers, first N rows, detected brokerage."""
    reader = csv.DictReader(io.StringIO(content))
    headers = reader.fieldnames or []
    rows = []
    for i, row in enumerate(reader):
        if i >= max_rows:
            break
        rows.append(dict(row))

    brokerage = detect_brokerage(headers)

    return {
        "headers": headers,
        "rows": rows,
        "row_count": len(rows),
        "detected_brokerage": brokerage,
    }
