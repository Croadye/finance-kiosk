from __future__ import annotations
from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Bill, Account, Category, Transaction, TxSplit

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def advance_next_due(d: date, cadence: str) -> date:
    if cadence == "weekly":
        return d + timedelta(days=7)
    if cadence == "biweekly":
        return d + timedelta(days=14)
    # default monthly: naive month+1
    y, m = d.year, d.month
    if m == 12:
        return date(y+1, 1, d.day if d.day <= 28 else 28)
    return date(y, m+1, min(d.day, 28))


@router.get("/recurring", response_class=HTMLResponse)
async def recurring_list(request: Request, session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(Bill)
        .order_by(Bill.next_due.nulls_last(), Bill.name)
    )).scalars().all()
    return templates.TemplateResponse("recurring_list.html", {"request": request, "rows": rows})


@router.get("/recurring/new", response_class=HTMLResponse)
async def recurring_new(request: Request, session: AsyncSession = Depends(get_session)):
    accounts = (await session.execute(select(Account.id, Account.name))).all()
    categories = (await session.execute(select(Category.id, Category.name))).all()
    return templates.TemplateResponse("recurring_new.html", {
        "request": request, "accounts": accounts, "categories": categories
    })


@router.post("/recurring")
async def recurring_create(
    name: str = Form(...),
    amount: float = Form(...),
    kind: str = Form("expense"),
    cadence: str = Form("monthly"),
    next_due: str = Form(...),
    autopost: bool = Form(False),
    account_id: str = Form(...),
    category_id: str = Form(...),
    payee: str = Form(""),
    memo: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    signed = -abs(amount) if kind == "expense" else abs(amount)
    row = Bill(
        name=name, amount=signed, cadence=cadence,
        next_due=date.fromisoformat(next_due),
        autopost=bool(autopost),
        account_id=UUID(account_id), category_id=UUID(category_id) if category_id else None,
    )
    session.add(row)
    await session.commit()
    return RedirectResponse(url="/recurring", status_code=303)


@router.post("/recurring/{bill_id}/delete")
async def recurring_delete(bill_id: str, session: AsyncSession = Depends(get_session)):
    row = await session.get(Bill, UUID(bill_id))
    if row:
        await session.delete(row)
        await session.commit()
    return RedirectResponse(url="/recurring", status_code=303)


@router.post("/recurring/run_due")
async def recurring_run_due(session: AsyncSession = Depends(get_session), request: Request = None):
    today = date.today()
    due = (await session.execute(
        select(Bill).where(Bill.next_due != None, Bill.next_due <= today)
    )).scalars().all()

    to_confirm = []
    for b in list(due):
        if b.autopost:
            # auto post
            tx = Transaction(
                account_id=b.account_id, amount=b.amount,
                payee=b.name, memo=f"Recurring ({b.cadence})", cleared=True
            )
            session.add(tx)
            await session.flush()
            if b.category_id:
                session.add(TxSplit(transaction_id=tx.id,
                            category_id=b.category_id, amount=b.amount))
            b.next_due = advance_next_due(b.next_due, b.cadence)
        else:
            to_confirm.append(b)

    await session.commit()

    if not to_confirm:
        return RedirectResponse(url="/recurring", status_code=303)

    # show confirmation page for the rest (lets you tweak amounts)
    return templates.TemplateResponse("recurring_review.html", {
        "request": request,
        "rows": to_confirm
    })


@router.post("/recurring/confirm")
async def recurring_confirm(session: AsyncSession = Depends(get_session), request: Request = None):
    form = await request.form()
    today = date.today()
    for key, val in form.items():
        if not key.startswith("amount_"):
            continue
        bill_id = key.split("_", 1)[1]
        b = await session.get(Bill, UUID(bill_id))
        if not b or (b.next_due and b.next_due > today):
            continue
        try:
            amt = float(str(val).strip() or "0")
        except:
            amt = float(b.amount)
        # keep original sign, but allow user to flip with negative if they want
        final = amt if b.amount > 0 else -abs(amt)

        tx = Transaction(
            account_id=b.account_id, amount=final,
            payee=b.name, memo=f"Recurring ({b.cadence})", cleared=True
        )
        session.add(tx)
        await session.flush()
        if b.category_id:
            session.add(TxSplit(transaction_id=tx.id,
                        category_id=b.category_id, amount=final))
        b.next_due = advance_next_due(b.next_due, b.cadence)

    await session.commit()
    return RedirectResponse(url="/recurring", status_code=303)
