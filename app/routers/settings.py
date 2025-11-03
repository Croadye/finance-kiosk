from __future__ import annotations
from decimal import Decimal
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_session
from ..models import Setting, Account, Transaction

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def current_networth(session: AsyncSession) -> Decimal:
    acc_rows = (await session.execute(
        select(Account.id, Account.opening_balance)
    )).all()
    tx_rows = (await session.execute(
        select(Transaction.account_id, func.coalesce(
            func.sum(Transaction.amount), 0))
        .group_by(Transaction.account_id)
    )).all()
    opening = {r.id: Decimal(r.opening_balance or 0) for r in acc_rows}
    txsum = {r[0]: Decimal(r[1] or 0) for r in tx_rows}
    total = sum(opening.get(a, Decimal(0)) + txsum.get(a, Decimal(0))
                for a in opening.keys())
    return total


@router.get("/settings/networth", response_class=HTMLResponse)
async def networth_get(request: Request, session: AsyncSession = Depends(get_session)):
    raw_net = await current_networth(session)
    s = await session.get(Setting, "networth_offset")
    offset = Decimal(0)
    if s and s.v_json is not None:
        try:
            v = s.v_json
            offset = Decimal(v if isinstance(v, (int, float))
                             else v.get("offset", 0))
        except:
            offset = Decimal(0)
    return templates.TemplateResponse("settings_networth.html", {
        "request": request, "raw_net": float(raw_net), "offset": float(offset),
        "display_net": float(raw_net + offset),
    })


@router.post("/settings/networth")
async def networth_post(
    home_value: float = Form(0.0),
    vehicles_value: float = Form(0.0),
    bank_total_now: float = Form(0.0),
    cc_debt_now: float = Form(0.0),
    session: AsyncSession = Depends(get_session),
):
    baseline = Decimal(home_value) + Decimal(vehicles_value) + \
        Decimal(bank_total_now) - Decimal(cc_debt_now)
    raw_net = await current_networth(session)
    offset = baseline - raw_net  # so displayed = raw_net + offset == baseline
    row = await session.get(Setting, "networth_offset")
    if row:
        row.v_json = {"offset": float(offset)}
    else:
        row = Setting(k="networth_offset", v_json={"offset": float(offset)})
        session.add(row)
    await session.commit()
    return RedirectResponse(url="/", status_code=303)
