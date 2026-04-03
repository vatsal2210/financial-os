"""Portfolio X-Ray — instant one-click analysis of portfolio health."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from database import get_db, is_onboarded
from services.portfolio import calculate_holdings, get_portfolio_summary, get_allocation
from routers.shared import render as _render

router = APIRouter()


@router.get("/xray", response_class=HTMLResponse)
async def xray(request: Request):
    if not is_onboarded():
        return RedirectResponse(url="/onboarding", status_code=303)

    summary = get_portfolio_summary()
    holdings = summary["holdings"]
    allocation = get_allocation(holdings)

    # --- Run all analysis checks ---
    alerts = []
    insights = []
    grades = {}

    # 1. Concentration risk
    if allocation:
        top_pct = allocation[0]["pct"]
        top_symbol = allocation[0]["symbol"]
        if top_pct > 30:
            alerts.append({
                "severity": "high",
                "title": "High concentration risk",
                "detail": f"{top_symbol} is {top_pct}% of your portfolio. Consider trimming to under 20%.",
            })
            grades["concentration"] = "D"
        elif top_pct > 20:
            alerts.append({
                "severity": "medium",
                "title": "Moderate concentration",
                "detail": f"{top_symbol} is {top_pct}% of your portfolio. Manageable but watch it.",
            })
            grades["concentration"] = "C"
        else:
            insights.append(f"Good diversification — largest position ({top_symbol}) is {top_pct}%.")
            grades["concentration"] = "A"
    else:
        grades["concentration"] = "N/A"

    # 2. Position count
    num_positions = len(holdings)
    if num_positions > 25:
        alerts.append({
            "severity": "medium",
            "title": f"Too many positions ({num_positions})",
            "detail": "More than 25 positions makes it hard to track. Consider consolidating.",
        })
        grades["simplicity"] = "D"
    elif num_positions > 15:
        grades["simplicity"] = "C"
        insights.append(f"{num_positions} positions — getting crowded. Consider which ones earn their spot.")
    elif num_positions >= 5:
        grades["simplicity"] = "A"
        insights.append(f"{num_positions} positions — well-managed portfolio size.")
    else:
        grades["simplicity"] = "B"
        insights.append(f"Only {num_positions} positions — consider more diversification.")

    # 3. Winners vs losers
    winners = [h for h in holdings if h["unrealized_pnl"] > 0]
    losers = [h for h in holdings if h["unrealized_pnl"] < 0]
    if losers:
        deep_losers = [h for h in losers if h["unrealized_pct"] < -20]
        if deep_losers:
            symbols = ", ".join(h["symbol"] for h in deep_losers[:3])
            alerts.append({
                "severity": "high",
                "title": f"{len(deep_losers)} position(s) down more than 20%",
                "detail": f"{symbols} — consider cutting losses. Averaging down past -20% rarely works.",
            })
            grades["discipline"] = "D"
        else:
            grades["discipline"] = "B"
    else:
        grades["discipline"] = "A"
        insights.append("All positions in the green. Nice work.")

    win_rate = round(len(winners) / len(holdings) * 100) if holdings else 0
    insights.append(f"Win rate: {win_rate}% ({len(winners)} green, {len(losers)} red)")

    # 4. Small positions (under $300)
    small = [h for h in holdings if 0 < h["market_value"] < 300]
    if small:
        symbols = ", ".join(h["symbol"] for h in small[:5])
        alerts.append({
            "severity": "low",
            "title": f"{len(small)} position(s) under $300",
            "detail": f"{symbols} — too small to move the needle. Either size up or close out.",
        })

    # 5. Dividend income
    if summary["dividends"] > 0:
        monthly_div = round(summary["dividends"] / 12, 2) if summary["dividends"] else 0
        insights.append(f"Dividend income: ${summary['dividends']:,.2f} total (${monthly_div:,.2f}/mo est.)")

    # 6. Realized P&L
    if summary["realized_pnl"] > 0:
        insights.append(f"Realized gains: +${summary['realized_pnl']:,.2f} — watch for tax implications.")
    elif summary["realized_pnl"] < 0:
        insights.append(f"Realized losses: ${summary['realized_pnl']:,.2f} — can offset capital gains on taxes.")

    # 7. Cost basis efficiency
    if summary["total_cost_basis"] > 0:
        return_pct = round((summary["total_value"] - summary["total_cost_basis"]) / summary["total_cost_basis"] * 100, 1)
        if return_pct > 10:
            grades["returns"] = "A"
        elif return_pct > 0:
            grades["returns"] = "B"
        elif return_pct > -10:
            grades["returns"] = "C"
        else:
            grades["returns"] = "D"
    else:
        grades["returns"] = "N/A"

    # Overall grade
    grade_values = {"A": 4, "B": 3, "C": 2, "D": 1}
    scoreable = [grade_values[g] for g in grades.values() if g in grade_values]
    avg_score = sum(scoreable) / len(scoreable) if scoreable else 0
    if avg_score >= 3.5:
        overall = "A"
    elif avg_score >= 2.5:
        overall = "B"
    elif avg_score >= 1.5:
        overall = "C"
    else:
        overall = "D"

    return _render(request, "xray.html",
        tab="overview",
        summary=summary,
        allocation=allocation,
        alerts=alerts,
        insights=insights,
        grades=grades,
        overall=overall,
    )
