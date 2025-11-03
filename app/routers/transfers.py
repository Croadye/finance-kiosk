from __future__ import annotations
from uuid import uuid4, UUID
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Account, Transaction
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/transfers/new", response_class=HTMLResponse)
async def transfers_new(request: Request, session: AsyncSession = Depends(get_session)):
    accounts = (await session.execute(
        select(Account.id, Account.name).order_by(Account.name)
    )).all()
    today = datetime.now().date().isoformat()
    return templates.TemplateResponse("transfers_new.html", {
        "request": request,
        "accounts": [(r[0], r[1]) for r in accounts],
        "today": today,
    })

@router.post("/transfers")
async def transfers_create(
    tx_date: str = Form(...),                 # YYYY-MM-DD
    from_account_id: str = Form(...),
    to_account_id: str = Form(...),
    amount: str = Form(...),                  # accept as string -> Decimal
    memo: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    # basic validation
    if from_account_id == to_account_id:
        return RedirectResponse(url="/transfers/new?err=same_accounts", status_code=303)
    try:
        amt = Decimal(str(amount).replace(",", "").strip())
    except:
        return RedirectResponse(url="/transfers/new?err=bad_amount", status_code=303)
    if amt <= 0:
        return RedirectResponse(url="/transfers/new?err=nonpositive", status_code=303)

    # parse date -> ts
    try:
        ts = datetime.fromisoformat(tx_date)
    except:
        ts = datetime.now()

    g = uuid4()
    # Outflow from source (negative)
    t1 = Transaction(
        account_id=UUID(from_account_id),
        amount=-abs(amt),
        ts=ts,
        payee="Transfer to account",
        memo=(memo or "").strip()[:200] or None,
        transfer_group_id=g,
    )
    # Inflow to destination (positive) — even if it's a debt account,
    # adding a positive amount moves the balance toward zero (reduces what you owe)
    t2 = Transaction(
        account_id=UUID(to_account_id),
        amount=abs(amt),
        ts=ts,
        payee="Transfer from account",
        memo=(memo or "").strip()[:200] or None,
        transfer_group_id=g,
    )

    session.add_all([t1, t2])
    await session.commit()
    return RedirectResponse(url="/transactions?notice=transfer_saved", status_code=303)
