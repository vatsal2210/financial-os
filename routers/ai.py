"""AI query routes — natural language questions about portfolio."""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from database import get_db, TEMPLATES_DIR
from services.ai_client import query_portfolio, get_ai_provider

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _render(request, template, **ctx):
    return templates.TemplateResponse(request=request, name=template, context=ctx)


@router.get("/ask", response_class=HTMLResponse)
async def ask_page(request: Request):
    ai_config = get_ai_provider()
    conn = get_db()
    history = conn.execute(
        "SELECT * FROM chat_history ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    conn.close()

    return _render(request, "ask.html",
        tab="ask", ai_configured=ai_config["configured"],
        ai_provider=ai_config["provider"], history=list(reversed(history)))


@router.post("/ask", response_class=HTMLResponse)
async def ask_question(request: Request, question: str = Form(...)):
    conn = get_db()
    conn.execute(
        "INSERT INTO chat_history (role, content) VALUES ('user', ?)",
        (question,)
    )
    conn.commit()

    answer = query_portfolio(question)

    conn.execute(
        "INSERT INTO chat_history (role, content) VALUES ('assistant', ?)",
        (answer,)
    )
    conn.commit()

    ai_config = get_ai_provider()
    history = conn.execute(
        "SELECT * FROM chat_history ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    conn.close()

    return _render(request, "ask.html",
        tab="ask", ai_configured=ai_config["configured"],
        ai_provider=ai_config["provider"], history=list(reversed(history)),
        latest_answer=answer)


@router.post("/api/ask")
async def api_ask(request: Request):
    """JSON endpoint for the sidebar AI panel."""
    body = await request.json()
    question = body.get("question", "").strip()
    if not question:
        return JSONResponse({"error": "No question provided"}, status_code=400)

    ai_config = get_ai_provider()
    if not ai_config["configured"]:
        return JSONResponse({
            "answer": "Set up your API key in Settings to use AI queries.",
            "configured": False,
        })

    conn = get_db()
    conn.execute("INSERT INTO chat_history (role, content) VALUES ('user', ?)", (question,))
    conn.commit()

    answer = query_portfolio(question)

    conn.execute("INSERT INTO chat_history (role, content) VALUES ('assistant', ?)", (answer,))
    conn.commit()
    conn.close()

    return JSONResponse({"answer": answer, "configured": True})


@router.get("/api/ask/history")
async def api_ask_history():
    """Get recent chat history for the sidebar panel."""
    conn = get_db()
    rows = conn.execute(
        "SELECT role, content FROM chat_history ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    conn.close()
    history = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    ai_config = get_ai_provider()
    return JSONResponse({"history": history, "configured": ai_config["configured"]})
