"""Finances routes — income tracking, expense management, cashflow summary."""
import csv
import io
import uuid
from datetime import datetime, date
from fastapi import APIRouter, Request, Form, UploadFile, File, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from database import get_db, TEMPLATES_DIR

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

EXPENSE_CATEGORIES = [
    "housing", "groceries", "transport", "dining", "subscriptions",
    "insurance", "utilities", "health", "shopping", "other",
]

INCOME_CATEGORIES = [
    "salary", "freelance", "rental", "dividends", "benefits", "other",
]

INCOME_FREQUENCIES = ["monthly", "biweekly", "annual"]


def _render(request, template, **ctx):
    return templates.TemplateResponse(request=request, name=template, context=ctx)


def _to_monthly(amount: float, frequency: str) -> float:
    """Convert any income frequency to a monthly amount."""
    if frequency == "biweekly":
        return amount * 26 / 12
    elif frequency == "annual":
        return amount / 12
    return amount  # monthly


def _get_cashflow_summary(year: int, month: int) -> dict:
    """Build the full cashflow summary for a given month."""
    conn = get_db()

    # --- Income sources ---
    income_rows = conn.execute(
        "SELECT * FROM income ORDER BY active DESC, amount DESC"
    ).fetchall()

    total_monthly_income = 0.0
    income_sources = []
    for row in income_rows:
        monthly = _to_monthly(row["amount"], row["frequency"])
        income_sources.append({
            "id": row["id"],
            "name": row["name"],
            "amount": row["amount"],
            "monthly": monthly,
            "frequency": row["frequency"],
            "category": row["category"],
            "active": bool(row["active"]),
        })
        if row["active"]:
            total_monthly_income += monthly

    # --- Expenses for the month ---
    month_start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        month_end = f"{year + 1:04d}-01-01"
    else:
        month_end = f"{year:04d}-{month + 1:02d}-01"

    expenses = conn.execute(
        "SELECT * FROM expenses WHERE date >= ? AND date < ? ORDER BY date DESC",
        (month_start, month_end),
    ).fetchall()

    total_monthly_expenses = sum(row["amount"] for row in expenses)

    # --- Category breakdown ---
    category_totals = {}
    for row in expenses:
        cat = row["category"] or "other"
        category_totals[cat] = category_totals.get(cat, 0.0) + row["amount"]

    # --- Budget limits ---
    budgets = {}
    budget_rows = conn.execute("SELECT * FROM budgets").fetchall()
    for row in budget_rows:
        budgets[row["category"]] = row["monthly_limit"]

    # Build category breakdown with budget comparison
    category_breakdown = []
    # Include all categories that have either spending or a budget
    all_cats = set(category_totals.keys()) | set(budgets.keys())
    for cat in EXPENSE_CATEGORIES:
        spent = category_totals.get(cat, 0.0)
        limit = budgets.get(cat, 0.0)
        if spent > 0 or limit > 0:
            pct = (spent / limit * 100) if limit > 0 else 0
            category_breakdown.append({
                "category": cat,
                "spent": spent,
                "limit": limit,
                "pct": min(pct, 100),  # cap bar at 100%
                "over": spent > limit if limit > 0 else False,
            })
    # Sort: over-budget first, then by spend descending
    category_breakdown.sort(key=lambda x: (-int(x["over"]), -x["spent"]))

    # --- Savings ---
    net_savings = total_monthly_income - total_monthly_expenses
    savings_rate = (
        (net_savings / total_monthly_income * 100)
        if total_monthly_income > 0 else 0.0
    )

    conn.close()

    return {
        "year": year,
        "month": month,
        "month_name": date(year, month, 1).strftime("%B %Y"),
        "total_income": total_monthly_income,
        "total_expenses": total_monthly_expenses,
        "net_savings": net_savings,
        "savings_rate": savings_rate,
        "income_sources": income_sources,
        "expenses": [dict(row) for row in expenses],
        "category_breakdown": category_breakdown,
        "categories": EXPENSE_CATEGORIES,
        "income_categories": INCOME_CATEGORIES,
        "frequencies": INCOME_FREQUENCIES,
    }


# --- Routes ---

@router.get("/finances", response_class=HTMLResponse)
async def finances_page(request: Request):
    today = date.today()
    summary = _get_cashflow_summary(today.year, today.month)
    return _render(request, "finances.html", tab="finances", **summary)


@router.get("/finances/monthly/{year}/{month}", response_class=HTMLResponse)
async def finances_monthly(request: Request, year: int, month: int):
    # Clamp to valid range
    if month < 1:
        month = 12
        year -= 1
    elif month > 12:
        month = 1
        year += 1
    summary = _get_cashflow_summary(year, month)
    return _render(request, "finances.html", tab="finances", **summary)


@router.post("/income/add")
async def income_add(
    name: str = Form(...),
    amount: float = Form(...),
    frequency: str = Form("monthly"),
    category: str = Form("salary"),
):
    name = name.strip()
    if not name or amount <= 0:
        return RedirectResponse(url="/finances", status_code=303)
    if frequency not in INCOME_FREQUENCIES:
        frequency = "monthly"
    if category not in INCOME_CATEGORIES:
        category = "other"

    conn = get_db()
    conn.execute(
        "INSERT INTO income (name, amount, frequency, category) VALUES (?, ?, ?, ?)",
        (name, amount, frequency, category),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/finances", status_code=303)


@router.post("/income/toggle/{income_id}")
async def income_toggle(income_id: int):
    conn = get_db()
    conn.execute(
        "UPDATE income SET active = CASE WHEN active = 1 THEN 0 ELSE 1 END WHERE id = ?",
        (income_id,),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/finances", status_code=303)


@router.post("/income/remove")
async def income_remove(id: int = Form(...)):
    conn = get_db()
    conn.execute("DELETE FROM income WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/finances", status_code=303)


@router.post("/expenses/add")
async def expense_add(
    date_str: str = Form(..., alias="date"),
    description: str = Form(""),
    amount: float = Form(...),
    category: str = Form("other"),
):
    description = description.strip()
    if amount <= 0:
        return RedirectResponse(url="/finances", status_code=303)
    if category not in EXPENSE_CATEGORIES:
        category = "other"

    # Validate date format
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return RedirectResponse(url="/finances", status_code=303)

    conn = get_db()
    conn.execute(
        "INSERT INTO expenses (date, description, amount, category, source) VALUES (?, ?, ?, ?, ?)",
        (date_str, description or None, amount, category, "manual"),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/finances", status_code=303)


# --- CSV Import ---

def _detect_csv_columns(headers: list[str]) -> dict:
    """Detect date, description, and amount columns from CSV headers.

    Supports Chase, Amex, generic bank exports. Returns a mapping:
    {"date": idx, "description": idx, "amount": idx, "negate": bool}
    """
    headers_lower = [h.strip().lower().replace('"', '') for h in headers]
    mapping = {"date": None, "description": None, "amount": None, "negate": False}

    # Date column detection
    date_names = ["date", "transaction date", "trans date", "posting date", "trans. date"]
    for i, h in enumerate(headers_lower):
        if h in date_names:
            mapping["date"] = i
            break

    # Description column detection
    desc_names = ["description", "memo", "details", "transaction", "merchant", "payee", "name"]
    for i, h in enumerate(headers_lower):
        if h in desc_names:
            mapping["description"] = i
            break

    # Amount column detection (with sign convention)
    # Amex: "Amount" where positive = charge (we want positive for expenses)
    # Chase: "Amount" where negative = charge (we need to negate)
    # Generic: look for "debit" column first, then "amount"
    debit_names = ["debit", "debit amount", "withdrawal"]
    for i, h in enumerate(headers_lower):
        if h in debit_names:
            mapping["amount"] = i
            break

    if mapping["amount"] is None:
        amount_names = ["amount", "transaction amount", "total"]
        for i, h in enumerate(headers_lower):
            if h in amount_names:
                mapping["amount"] = i
                break

    # Detect if this looks like Chase (negative amounts = expenses)
    # Chase CSVs have "Amount" column with negative values for charges
    if any("chase" in h for h in headers_lower) or (
        "type" in headers_lower and "amount" in headers_lower
    ):
        mapping["negate"] = True

    return mapping


def _parse_date(value: str) -> str | None:
    """Try common date formats and return YYYY-MM-DD or None."""
    value = value.strip().replace('"', '')
    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%m-%d-%Y",
        "%d-%m-%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _guess_category(description: str) -> str:
    """Guess expense category from description keywords."""
    desc = description.lower()
    rules = {
        "housing": ["rent", "mortgage", "property tax", "condo", "strata", "hoa"],
        "groceries": ["grocery", "superstore", "walmart", "costco", "no frills",
                       "loblaws", "metro", "freshco", "food basics", "t&t", "farm boy"],
        "transport": ["gas", "fuel", "uber", "lyft", "transit", "parking", "presto",
                       "shell", "esso", "petro", "canadian tire gas"],
        "dining": ["restaurant", "mcdonald", "tim horton", "starbucks", "subway",
                    "pizza", "doordash", "skip the dishes", "ubereats", "grubhub"],
        "subscriptions": ["netflix", "spotify", "apple", "amazon prime", "youtube",
                          "disney", "hulu", "subscription", "membership"],
        "insurance": ["insurance", "manulife", "sun life", "great-west", "desjardins"],
        "utilities": ["hydro", "enbridge", "gas bill", "water", "electric", "internet",
                       "rogers", "bell", "telus", "fido", "koodo", "phone"],
        "health": ["pharmacy", "shoppers drug", "doctor", "dental", "medical",
                    "hospital", "physio", "therapy", "prescription"],
        "shopping": ["amazon", "best buy", "ikea", "canadian tire", "winners",
                      "homesense", "the bay", "indigo", "walmart"],
    }
    for cat, keywords in rules.items():
        for kw in keywords:
            if kw in desc:
                return cat
    return "other"


@router.post("/expenses/import")
async def expense_import(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        return RedirectResponse(url="/finances", status_code=303)

    content = await file.read()
    # Try UTF-8, fall back to latin-1
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2:
        return RedirectResponse(url="/finances", status_code=303)

    headers = rows[0]
    mapping = _detect_csv_columns(headers)

    # Bail if we can't find date and amount columns
    if mapping["date"] is None or mapping["amount"] is None:
        return RedirectResponse(url="/finances", status_code=303)

    batch_id = str(uuid.uuid4())[:8]
    imported = 0
    conn = get_db()

    for row in rows[1:]:
        if not row or len(row) <= max(
            mapping["date"],
            mapping["amount"],
            mapping["description"] or 0,
        ):
            continue

        # Parse date
        parsed_date = _parse_date(row[mapping["date"]])
        if not parsed_date:
            continue

        # Parse amount
        raw_amount = row[mapping["amount"]].strip().replace('"', '').replace('$', '').replace(',', '')
        if not raw_amount or raw_amount == "":
            continue
        try:
            amount = float(raw_amount)
        except ValueError:
            continue

        # Normalize: we want positive values for expenses
        if mapping["negate"]:
            amount = -amount
        # Skip credits/positive values (refunds, payments) — keep only debits
        if amount <= 0:
            continue

        # Description
        description = ""
        if mapping["description"] is not None:
            description = row[mapping["description"]].strip().replace('"', '')

        category = _guess_category(description)

        conn.execute(
            "INSERT INTO expenses (date, description, amount, category, source, import_batch) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (parsed_date, description or None, round(amount, 2), category, file.filename, batch_id),
        )
        imported += 1

    conn.commit()
    conn.close()

    return RedirectResponse(url="/finances", status_code=303)
