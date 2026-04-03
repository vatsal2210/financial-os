"""Tax tab — Canada & USA tax calculations, receipts, and optimization."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from database import get_db, TEMPLATES_DIR

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _render(request, template, **ctx):
    return templates.TemplateResponse(request=request, name=template, context=ctx)


# ---------------------------------------------------------------------------
# Tax bracket definitions
# ---------------------------------------------------------------------------

CA_FEDERAL_BRACKETS_2025 = [
    (57_375, 0.15),
    (114_750, 0.205),
    (158_468, 0.26),
    (221_708, 0.29),
    (float("inf"), 0.33),
]

CA_PROVINCIAL_BRACKETS = {
    "ON": [
        (52_886, 0.0505),
        (105_775, 0.0915),
        (150_000, 0.1116),
        (220_000, 0.1216),
        (float("inf"), 0.1316),
    ],
    "BC": [
        (47_937, 0.0506),
        (95_875, 0.077),
        (110_076, 0.105),
        (133_664, 0.1229),
        (181_232, 0.147),
        (252_752, 0.168),
        (float("inf"), 0.205),
    ],
    "AB": [
        (148_269, 0.10),
        (177_922, 0.12),
        (237_230, 0.13),
        (355_845, 0.14),
        (float("inf"), 0.15),
    ],
    "QC": [
        (51_780, 0.14),
        (103_545, 0.19),
        (126_000, 0.24),
        (float("inf"), 0.2575),
    ],
}

US_FEDERAL_BRACKETS_2025_SINGLE = [
    (11_925, 0.10),
    (48_475, 0.12),
    (103_350, 0.22),
    (197_300, 0.24),
    (250_525, 0.32),
    (626_350, 0.35),
    (float("inf"), 0.37),
]

US_FEDERAL_BRACKETS_2025_MFJ = [
    (23_850, 0.10),
    (96_950, 0.12),
    (206_700, 0.22),
    (394_600, 0.24),
    (501_050, 0.32),
    (751_600, 0.35),
    (float("inf"), 0.37),
]

US_LTCG_BRACKETS_SINGLE = [
    (48_350, 0.0),
    (533_400, 0.15),
    (float("inf"), 0.20),
]

US_LTCG_BRACKETS_MFJ = [
    (96_700, 0.0),
    (583_750, 0.15),
    (float("inf"), 0.20),
]

CA_RECEIPT_CATEGORIES = [
    "medical", "charitable", "moving", "home_office",
    "professional_dues", "child_care", "tuition",
]

US_RECEIPT_CATEGORIES = [
    "medical", "charitable", "mortgage_interest", "state_local_tax",
    "home_office", "education", "business_expense",
]

CA_PROVINCES = {
    "ON": "Ontario", "BC": "British Columbia", "AB": "Alberta",
    "QC": "Quebec", "MB": "Manitoba", "SK": "Saskatchewan",
    "NS": "Nova Scotia", "NB": "New Brunswick", "NL": "Newfoundland & Labrador",
    "PE": "Prince Edward Island", "NT": "Northwest Territories",
    "YT": "Yukon", "NU": "Nunavut",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_tax_profile() -> dict:
    """Return tax profile as a dict from the tax_profile table."""
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM tax_profile").fetchall()
    conn.close()
    return {row["key"]: row["value"] for row in rows}


def _calc_bracket_tax(income: float, brackets: list[tuple[float, float]]) -> float:
    """Calculate progressive tax through brackets."""
    tax = 0.0
    prev = 0.0
    for ceiling, rate in brackets:
        if income <= prev:
            break
        taxable = min(income, ceiling) - prev
        tax += taxable * rate
        prev = ceiling
    return tax


def _marginal_rate(income: float, brackets: list[tuple[float, float]]) -> float:
    """Return the marginal rate for a given income."""
    for ceiling, rate in brackets:
        if income <= ceiling:
            return rate
    return brackets[-1][1]


def _calc_ca_tax(income: float, province: str) -> dict:
    """Calculate Canadian federal + provincial tax."""
    federal = _calc_bracket_tax(income, CA_FEDERAL_BRACKETS_2025)
    fed_marginal = _marginal_rate(income, CA_FEDERAL_BRACKETS_2025)

    prov_brackets = CA_PROVINCIAL_BRACKETS.get(province, CA_PROVINCIAL_BRACKETS["ON"])
    provincial = _calc_bracket_tax(income, prov_brackets)
    prov_marginal = _marginal_rate(income, prov_brackets)

    # Basic personal amount credits (simplified)
    bpa_federal = 16_129 * 0.15  # ~$2,419
    bpa_provincial_rates = {"ON": 11_865 * 0.0505, "BC": 12_580 * 0.0506,
                            "AB": 22_323 * 0.10, "QC": 18_056 * 0.14}
    bpa_prov = bpa_provincial_rates.get(province, 11_865 * 0.0505)

    federal_net = max(0, federal - bpa_federal)
    provincial_net = max(0, provincial - bpa_prov)

    return {
        "federal": round(federal_net, 2),
        "provincial": round(provincial_net, 2),
        "total": round(federal_net + provincial_net, 2),
        "marginal_federal": round(fed_marginal * 100, 1),
        "marginal_provincial": round(prov_marginal * 100, 1),
        "marginal_combined": round((fed_marginal + prov_marginal) * 100, 1),
    }


def _calc_us_tax(income: float, filing_status: str, state_rate: float) -> dict:
    """Calculate US federal + state tax."""
    if filing_status == "married_filing_jointly":
        brackets = US_FEDERAL_BRACKETS_2025_MFJ
    else:
        brackets = US_FEDERAL_BRACKETS_2025_SINGLE

    # Standard deduction
    std_deduction = 30_000 if filing_status == "married_filing_jointly" else 15_000
    taxable = max(0, income - std_deduction)

    federal = _calc_bracket_tax(taxable, brackets)
    fed_marginal = _marginal_rate(taxable, brackets)

    state_tax = income * (state_rate / 100)

    return {
        "federal": round(federal, 2),
        "state": round(state_tax, 2),
        "total": round(federal + state_tax, 2),
        "standard_deduction": std_deduction,
        "taxable_income": round(taxable, 2),
        "marginal_federal": round(fed_marginal * 100, 1),
        "marginal_state": round(state_rate, 1),
        "marginal_combined": round(fed_marginal * 100 + state_rate, 1),
    }


def _calc_capital_gains(country: str, filing_status: str, year: int) -> dict:
    """Calculate realized capital gains from transactions using FIFO."""
    conn = get_db()
    # Get all buy and sell transactions for the year and prior (for cost basis)
    buys = conn.execute(
        "SELECT * FROM transactions WHERE type = 'buy' AND symbol IS NOT NULL ORDER BY date ASC"
    ).fetchall()
    sells = conn.execute(
        "SELECT * FROM transactions WHERE type = 'sell' AND symbol IS NOT NULL "
        "AND strftime('%Y', date) = ? ORDER BY date ASC",
        (str(year),)
    ).fetchall()
    conn.close()

    # Build lot pool per symbol: list of (date, qty_remaining, cost_per_share)
    lots: dict[str, list] = {}
    for b in buys:
        sym = b["symbol"]
        qty = abs(b["quantity"]) if b["quantity"] else 0
        price = abs(b["price"]) if b["price"] else 0
        if qty <= 0:
            continue
        lots.setdefault(sym, []).append({
            "date": b["date"],
            "qty": qty,
            "cost": price,
        })

    gains = []
    total_short = 0.0
    total_long = 0.0

    for s in sells:
        sym = s["symbol"]
        sell_qty = abs(s["quantity"]) if s["quantity"] else 0
        sell_price = abs(s["price"]) if s["price"] else 0
        sell_date = s["date"]
        if sell_qty <= 0 or sym not in lots:
            continue

        remaining = sell_qty
        for lot in lots[sym]:
            if remaining <= 0:
                break
            if lot["qty"] <= 0:
                continue

            used = min(remaining, lot["qty"])
            proceeds = used * sell_price
            cost_basis = used * lot["cost"]
            gain = proceeds - cost_basis
            lot["qty"] -= used
            remaining -= used

            # Determine holding period
            try:
                buy_dt = datetime.strptime(lot["date"][:10], "%Y-%m-%d")
                sell_dt = datetime.strptime(sell_date[:10], "%Y-%m-%d")
                held_days = (sell_dt - buy_dt).days
            except (ValueError, TypeError):
                held_days = 0

            is_long = held_days > 365

            if is_long:
                total_long += gain
            else:
                total_short += gain

            gains.append({
                "symbol": sym,
                "sell_date": sell_date,
                "quantity": round(used, 4),
                "proceeds": round(proceeds, 2),
                "cost_basis": round(cost_basis, 2),
                "gain": round(gain, 2),
                "held_days": held_days,
                "term": "long" if is_long else "short",
            })

    # Tax on gains
    if country == "CA":
        # First $250K at 50% inclusion, above at 66.7%
        total_gain = total_short + total_long  # Canada doesn't distinguish short/long
        if total_gain <= 0:
            taxable_gain = total_gain * 0.5  # losses still at 50%
        elif total_gain <= 250_000:
            taxable_gain = total_gain * 0.5
        else:
            taxable_gain = 250_000 * 0.5 + (total_gain - 250_000) * 0.667
        cap_gains_tax = 0  # Will be calculated as part of income
    else:
        taxable_gain = total_short + total_long  # placeholder
        cap_gains_tax = 0

    # Wash sale detection for US
    wash_sales = []
    if country == "US":
        conn = get_db()
        all_txns = conn.execute(
            "SELECT * FROM transactions WHERE symbol IS NOT NULL "
            "AND strftime('%Y', date) = ? ORDER BY date ASC",
            (str(year),)
        ).fetchall()
        conn.close()

        sell_events = [(t["symbol"], t["date"]) for t in all_txns if t["type"] == "sell"]
        buy_events = [(t["symbol"], t["date"]) for t in all_txns if t["type"] == "buy"]

        for sym, sell_date in sell_events:
            try:
                sd = datetime.strptime(sell_date[:10], "%Y-%m-%d")
            except (ValueError, TypeError):
                continue
            for bsym, buy_date in buy_events:
                if bsym != sym:
                    continue
                try:
                    bd = datetime.strptime(buy_date[:10], "%Y-%m-%d")
                except (ValueError, TypeError):
                    continue
                diff = (bd - sd).days
                if 0 < diff <= 30:
                    wash_sales.append({
                        "symbol": sym,
                        "sell_date": sell_date[:10],
                        "buy_date": buy_date[:10],
                        "days_apart": diff,
                    })

    return {
        "gains": gains,
        "total_short": round(total_short, 2),
        "total_long": round(total_long, 2),
        "total_gain": round(total_short + total_long, 2),
        "taxable_gain": round(taxable_gain, 2),
        "wash_sales": wash_sales,
    }


def _get_optimization_checklist(country: str, income: float, profile: dict) -> list[dict]:
    """Return country-specific optimization items."""
    items = []

    if country == "CA":
        marginal = (_marginal_rate(income, CA_FEDERAL_BRACKETS_2025)
                    + _marginal_rate(income, CA_PROVINCIAL_BRACKETS.get(
                        profile.get("province", "ON"), CA_PROVINCIAL_BRACKETS["ON"])))

        items = [
            {
                "name": "RRSP Contribution",
                "description": "Reduce taxable income dollar-for-dollar",
                "max_amount": "18% of earned income (max $32,490 for 2025)",
                "tax_savings": f"~${round(32_490 * marginal):,} if maxed",
                "status": "Check CRA My Account for room",
                "checked": False,
            },
            {
                "name": "TFSA Contribution",
                "description": "Tax-free growth on investments",
                "max_amount": "$7,000 for 2025",
                "tax_savings": "No deduction, but all growth is tax-free",
                "status": "Check cumulative room",
                "checked": False,
            },
            {
                "name": "FHSA Contribution",
                "description": "First Home Savings Account (deductible + tax-free)",
                "max_amount": "$8,000/year ($40,000 lifetime)",
                "tax_savings": f"~${round(8_000 * marginal):,} per year",
                "status": "Best of both RRSP + TFSA",
                "checked": False,
            },
            {
                "name": "RESP Contribution",
                "description": "Canada Education Savings Grant (CESG)",
                "max_amount": "$2,500/year for 20% CESG match",
                "tax_savings": "$500/year free from government",
                "status": "Contribute at least $2,500 for full CESG",
                "checked": False,
            },
            {
                "name": "Canada Training Credit",
                "description": "Claim for eligible tuition and training fees",
                "max_amount": "$250/year accumulation (max $5,000 lifetime)",
                "tax_savings": "Up to $1,500 available for 2025",
                "status": "Check CRA My Account for balance",
                "checked": False,
            },
            {
                "name": "Home Office Expenses (T2200)",
                "description": "Deduct portion of rent/utilities/internet if working from home",
                "max_amount": "Varies — detailed or flat rate ($2/day, max $500)",
                "tax_savings": f"~${round(500 * marginal):,} at flat rate",
                "status": "Need T2200 from employer",
                "checked": False,
            },
            {
                "name": "Medical Expenses",
                "description": "Claim medical costs exceeding 3% of net income",
                "max_amount": "No cap — threshold is 3% of net income",
                "tax_savings": "15% federal credit on eligible amount",
                "status": "Collect all receipts",
                "checked": False,
            },
            {
                "name": "Charitable Donations",
                "description": "15% on first $200, 29-33% on amounts above",
                "max_amount": "Up to 75% of net income",
                "tax_savings": "Higher rate above $200 threshold",
                "status": "Combine with spouse for best rate",
                "checked": False,
            },
        ]
    else:  # US
        items = [
            {
                "name": "401(k) Contribution",
                "description": "Pre-tax retirement savings",
                "max_amount": "$23,500 for 2025 (under 50)",
                "tax_savings": f"~${round(23_500 * 0.24):,} at 24% bracket",
                "status": "Check with employer",
                "checked": False,
            },
            {
                "name": "Traditional IRA",
                "description": "Tax-deductible retirement contribution",
                "max_amount": "$7,000 for 2025 (under 50)",
                "tax_savings": f"~${round(7_000 * 0.22):,} at 22% bracket",
                "status": "Income limits may apply",
                "checked": False,
            },
            {
                "name": "HSA Contribution",
                "description": "Triple tax advantage — deductible, grows tax-free, tax-free withdrawals",
                "max_amount": "$4,300 single / $8,550 family (2025)",
                "tax_savings": f"~${round(4_300 * 0.22):,} single at 22%",
                "status": "Requires HDHP enrollment",
                "checked": False,
            },
            {
                "name": "Standard Deduction",
                "description": "Automatic deduction from taxable income",
                "max_amount": "$15,000 single / $30,000 MFJ (2025)",
                "tax_savings": "Applied automatically",
                "status": "Compare with itemized deductions",
                "checked": True,
            },
            {
                "name": "Roth IRA Conversion",
                "description": "Convert traditional to Roth in low-income years",
                "max_amount": "No limit, but taxed as income",
                "tax_savings": "Long-term tax-free growth",
                "status": "Evaluate if income is lower this year",
                "checked": False,
            },
            {
                "name": "Tax-Loss Harvesting",
                "description": "Sell losers to offset gains (watch wash sale rule)",
                "max_amount": "$3,000 net loss deduction against income",
                "tax_savings": f"~${round(3_000 * 0.22):,} at 22% bracket",
                "status": "Review unrealized losses",
                "checked": False,
            },
            {
                "name": "Mortgage Interest Deduction",
                "description": "Itemized deduction on mortgage interest",
                "max_amount": "Interest on up to $750K mortgage",
                "tax_savings": "Only if itemizing exceeds standard deduction",
                "status": "Get Form 1098 from lender",
                "checked": False,
            },
            {
                "name": "Charitable Donations",
                "description": "Itemized deduction for qualified charitable gifts",
                "max_amount": "Up to 60% of AGI for cash gifts",
                "tax_savings": "Only if itemizing",
                "status": "Keep all receipts over $250",
                "checked": False,
            },
        ]

    return items


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/tax", response_class=HTMLResponse)
async def tax_page(request: Request):
    profile = _get_tax_profile()
    country = profile.get("country", "")
    configured = bool(country)

    tax_info = {}
    optimization = []
    cap_gains = {}
    receipts = []
    deductions_total = 0.0
    current_year = datetime.now().year

    if configured:
        income = float(profile.get("annual_income", "0") or "0")

        # Calculate tax
        if country == "CA":
            province = profile.get("province", "ON")
            tax_info = _calc_ca_tax(income, province)
        else:
            filing = profile.get("filing_status", "single")
            state_rate = float(profile.get("state_tax_rate", "0") or "0")
            tax_info = _calc_us_tax(income, filing, state_rate)

        # Capital gains
        cap_gains = _calc_capital_gains(country, profile.get("filing_status", "single"), current_year)

        # Optimization checklist
        optimization = _get_optimization_checklist(country, income, profile)

        # Receipts — show current tax year, or most recent year with data
        conn = get_db()
        years_rows = conn.execute(
            "SELECT DISTINCT tax_year FROM receipts ORDER BY tax_year DESC"
        ).fetchall()
        available_years = [r["tax_year"] for r in years_rows]

        # Default to current year, but if no receipts there, show most recent
        display_year = current_year
        if available_years and current_year not in available_years:
            display_year = available_years[0]
        if current_year not in available_years:
            available_years.insert(0, current_year)

        receipts = conn.execute(
            "SELECT * FROM receipts WHERE tax_year = ? ORDER BY date DESC",
            (display_year,)
        ).fetchall()
        conn.close()
        deductions_total = sum(r["amount"] for r in receipts)
    else:
        available_years = [current_year]
        display_year = current_year

    categories = CA_RECEIPT_CATEGORIES if country == "CA" else US_RECEIPT_CATEGORIES

    return _render(request, "tax.html",
        tab="tax",
        profile=profile,
        configured=configured,
        country=country,
        tax_info=tax_info,
        optimization=optimization,
        cap_gains=cap_gains,
        receipts=receipts,
        deductions_total=deductions_total,
        current_year=display_year,
        available_years=available_years,
        categories=categories,
        ca_provinces=CA_PROVINCES,
    )


@router.post("/tax/profile")
async def save_tax_profile(
    country: str = Form(...),
    filing_status: str = Form("single"),
    annual_income: str = Form("0"),
    province: str = Form(""),
    state_tax_rate: str = Form("0"),
):
    conn = get_db()
    fields = {
        "country": country.strip().upper()[:2],
        "filing_status": filing_status.strip(),
        "annual_income": annual_income.strip(),
        "province": province.strip().upper()[:2],
        "state_tax_rate": state_tax_rate.strip(),
    }
    for key, value in fields.items():
        conn.execute(
            "INSERT INTO tax_profile (key, value, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value),
        )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/tax", status_code=303)


@router.post("/tax/receipt/add")
async def add_receipt(
    date: str = Form(...),
    description: str = Form(...),
    amount: float = Form(...),
    category: str = Form(...),
    tax_year: int = Form(...),
):
    conn = get_db()
    conn.execute(
        "INSERT INTO receipts (date, description, amount, category, tax_year) "
        "VALUES (?, ?, ?, ?, ?)",
        (date.strip(), description.strip(), amount, category.strip(), tax_year),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/tax", status_code=303)


@router.post("/tax/receipt/remove")
async def remove_receipt(id: int = Form(...)):
    conn = get_db()
    conn.execute("DELETE FROM receipts WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/tax", status_code=303)


@router.get("/tax/report/{year}", response_class=HTMLResponse)
async def tax_report(request: Request, year: int):
    profile = _get_tax_profile()
    country = profile.get("country", "")

    if not country:
        return RedirectResponse(url="/tax", status_code=303)

    income = float(profile.get("annual_income", "0") or "0")

    if country == "CA":
        province = profile.get("province", "ON")
        tax_info = _calc_ca_tax(income, province)
    else:
        filing = profile.get("filing_status", "single")
        state_rate = float(profile.get("state_tax_rate", "0") or "0")
        tax_info = _calc_us_tax(income, filing, state_rate)

    cap_gains = _calc_capital_gains(country, profile.get("filing_status", "single"), year)

    conn = get_db()
    receipts = conn.execute(
        "SELECT * FROM receipts WHERE tax_year = ? ORDER BY date DESC",
        (year,)
    ).fetchall()

    # Dividends for the year
    dividends = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) as total FROM transactions "
        "WHERE type = 'dividend' AND strftime('%Y', date) = ?",
        (str(year),)
    ).fetchone()
    conn.close()

    deductions_total = sum(r["amount"] for r in receipts)
    optimization = _get_optimization_checklist(country, income, profile)
    categories = CA_RECEIPT_CATEGORIES if country == "CA" else US_RECEIPT_CATEGORIES

    return _render(request, "tax.html",
        tab="tax",
        profile=profile,
        configured=True,
        country=country,
        tax_info=tax_info,
        optimization=optimization,
        cap_gains=cap_gains,
        receipts=receipts,
        deductions_total=deductions_total,
        current_year=year,
        available_years=[year],
        categories=categories,
        ca_provinces=CA_PROVINCES,
        report_year=year,
        dividends_total=round(dividends["total"], 2) if dividends else 0,
    )
