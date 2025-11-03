from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_session
from ..models import Account, Transaction, Setting
from fastapi.templating import Jinja2Templates
from ..utils import DEFAULT_ACCOUNT_TYPES, get_account_types
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: AsyncSession = Depends(get_session)):
    acc_rows = (await session.execute(
        select(Account.id, Account.type, Account.opening_balance)
    )).all()
    opening = {r.id: float(r.opening_balance or 0) for r in acc_rows}
    types = {r.id: (r.type or "").lower() for r in acc_rows}

    tx_rows = (await session.execute(
        select(Transaction.account_id, func.coalesce(
            func.sum(Transaction.amount), 0)).group_by(Transaction.account_id)
    )).all()
    txsum = {r[0]: float(r[1] or 0) for r in tx_rows}

    balances = {aid: opening.get(aid, 0.0) + txsum.get(aid, 0.0)
                for aid, _ in opening.items()}
    raw_net = float(sum(balances.values()))

    # offset for net worth
    offset = 0.0
    s = await session.get(Setting, "networth_offset")
    if s and s.v_json is not None:
        try:
            offset = float(s.v_json if isinstance(
                s.v_json, (int, float)) else s.v_json.get("offset", 0.0))
        except:  # keep 0
            pass
    net_worth = raw_net + offset

    cash_available = float(sum(
        bal for aid, bal in balances.items() if types.get(aid) in {"checking", "savings", "cash"}
    ))

    # sum of what you owe (positive figure)
    types_list = await get_account_types(session)
    debt_names = {t["name"].lower() for t in types_list if t.get("is_debt")}

    current_debts = float(sum(
        (-bal) if bal < 0 else 0.0
        for aid, bal in balances.items()
        if (types.get(aid) or "").lower() in debt_names
    ))

    # spent this month (expenses are negative amounts)
    from datetime import datetime
    first_of_month = datetime.now().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    spent_raw = (await session.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .where(Transaction.amount < 0)
        .where(Transaction.ts >= first_of_month)
    )).scalar_one()
    spent_this_month = float(-spent_raw if spent_raw else 0.0)

    metrics = {
        "net_worth": net_worth,
        "cash_available": cash_available,
        "current_debts": current_debts,
        "spent_this_month": spent_this_month,
    }
    if request.query_params.get("raw") == "1":
        return JSONResponse(metrics)

    return templates.TemplateResponse("dashboard.html", {"request": request, **metrics})
