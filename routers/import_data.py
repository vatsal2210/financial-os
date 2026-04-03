"""CSV import and onboarding routes."""
import uuid
from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from database import get_db, set_setting, is_onboarded, UPLOADS_DIR
from services.csv_parser import (
    BROKERAGE_PRESETS, parse_csv, get_preview, detect_brokerage
)
from routers.shared import render as _render

router = APIRouter()


@router.get("/onboarding", response_class=HTMLResponse)
async def onboarding(request: Request):
    if is_onboarded():
        return RedirectResponse(url="/", status_code=303)
    return _render(request, "onboarding.html", step="welcome", brokerages=BROKERAGE_PRESETS)


@router.post("/onboarding/account", response_class=HTMLResponse)
async def onboarding_account(
    request: Request,
    brokerage: str = Form(...),
    account_name: str = Form(...),
    account_type: str = Form(...),
    country: str = Form(""),
):
    preset = BROKERAGE_PRESETS.get(brokerage, {})
    currency = preset.get("currency", "USD")

    # Override currency based on country selection
    if country == "CA":
        currency = "CAD"
    elif country == "US":
        currency = "USD"

    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO accounts (name, brokerage, account_type, currency) VALUES (?, ?, ?, ?)",
        (account_name, brokerage, account_type, currency)
    )
    account_id = cursor.lastrowid

    # Save country-based settings
    if country:
        # Set home currency
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('home_currency', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (currency,)
        )
        # Set tax profile country
        conn.execute(
            "INSERT INTO tax_profile (key, value) VALUES ('country', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (country.upper(),)
        )
        # Default province/state
        if country == "CA":
            conn.execute(
                "INSERT INTO tax_profile (key, value) VALUES ('province', 'ON') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )

    conn.commit()
    conn.close()

    return _render(request, "onboarding.html",
        step="upload",
        account_id=account_id,
        brokerage=brokerage,
        brokerage_name=preset.get("name", brokerage),
        sample_hint=True,
    )


@router.post("/import/preview", response_class=HTMLResponse)
async def import_preview(
    request: Request,
    account_id: int = Form(...),
    brokerage: str = Form(...),
    file: UploadFile = File(...),
):
    content = (await file.read()).decode("utf-8-sig")

    # Save the upload
    upload_path = UPLOADS_DIR / file.filename
    upload_path.write_text(content)

    preview = get_preview(content)
    detected = preview["detected_brokerage"]

    # If we detect a different brokerage, suggest it
    if detected and detected != brokerage:
        brokerage = detected

    # Parse transactions
    import_batch = str(uuid.uuid4())[:8]
    transactions = parse_csv(content, brokerage, account_id, import_batch)

    return _render(request, "onboarding.html",
        step="preview",
        account_id=account_id,
        brokerage=brokerage,
        preview=preview,
        transactions=transactions[:20],
        total_count=len(transactions),
        import_batch=import_batch,
        filename=file.filename,
    )


@router.post("/import/confirm", response_class=HTMLResponse)
async def import_confirm(
    request: Request,
    account_id: int = Form(...),
    brokerage: str = Form(...),
    filename: str = Form(...),
    import_batch: str = Form(...),
):
    # Re-read the saved file and parse
    upload_path = UPLOADS_DIR / filename
    content = upload_path.read_text()

    transactions = parse_csv(content, brokerage, account_id, import_batch)

    # Insert all transactions
    conn = get_db()
    for tx in transactions:
        conn.execute(
            "INSERT INTO transactions "
            "(account_id, date, type, symbol, description, quantity, price, amount, currency, fees, raw_data, import_batch) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tx["account_id"], tx["date"], tx["type"], tx["symbol"],
                tx["description"], tx["quantity"], tx["price"], tx["amount"],
                tx["currency"], tx["fees"], tx["raw_data"], tx["import_batch"],
            )
        )

    # Log the import
    conn.execute(
        "INSERT INTO imports (filename, brokerage, account_id, rows_imported) VALUES (?, ?, ?, ?)",
        (filename, brokerage, account_id, len(transactions))
    )

    conn.commit()
    conn.close()

    # Mark as onboarded
    set_setting("onboarded", "true")

    return _render(request, "onboarding.html",
        step="done",
        rows_imported=len(transactions),
        filename=filename,
    )


# --- Additional import route (post-onboarding) ---

@router.get("/import", response_class=HTMLResponse)
async def import_page(request: Request):
    conn = get_db()
    accounts = conn.execute("SELECT * FROM accounts ORDER BY name").fetchall()
    imports = conn.execute(
        "SELECT i.*, a.name as account_name FROM imports i "
        "LEFT JOIN accounts a ON i.account_id = a.id ORDER BY imported_at DESC LIMIT 20"
    ).fetchall()
    conn.close()
    return _render(request, "import.html",
        accounts=accounts,
        imports=imports,
        brokerages=BROKERAGE_PRESETS,
    )


@router.post("/import/upload")
async def import_upload(
    request: Request,
    account_id: int = Form(...),
    brokerage: str = Form(...),
    file: UploadFile = File(...),
):
    content = (await file.read()).decode("utf-8-sig")
    upload_path = UPLOADS_DIR / file.filename
    upload_path.write_text(content)

    import_batch = str(uuid.uuid4())[:8]
    transactions = parse_csv(content, brokerage, account_id, import_batch)

    conn = get_db()
    for tx in transactions:
        conn.execute(
            "INSERT INTO transactions "
            "(account_id, date, type, symbol, description, quantity, price, amount, currency, fees, raw_data, import_batch) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tx["account_id"], tx["date"], tx["type"], tx["symbol"],
                tx["description"], tx["quantity"], tx["price"], tx["amount"],
                tx["currency"], tx["fees"], tx["raw_data"], tx["import_batch"],
            )
        )
    conn.execute(
        "INSERT INTO imports (filename, brokerage, account_id, rows_imported) VALUES (?, ?, ?, ?)",
        (file.filename, brokerage, account_id, len(transactions))
    )
    conn.commit()
    conn.close()

    return RedirectResponse(url="/import", status_code=303)
