from __future__ import annotations
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Account, Transaction
from ..utils import DEFAULT_ACCOUNT_TYPES, get_account_types

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _normalize_is_debt(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "on", "yes"}


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_list(request: Request, session: AsyncSession = Depends(get_session)):
    accs = (
        await session.execute(
            select(
                Account.id,
                Account.name,
                Account.type,
                Account.opening_balance,
                Account.is_archived,
                Account.is_debt,
            )
        )
    ).all()
    tx_rows = (await session.execute(
        select(Transaction.account_id, func.coalesce(
            func.sum(Transaction.amount), 0)).group_by(Transaction.account_id)
    )).all()
    txsum = {r[0]: Decimal(r[1] or 0) for r in tx_rows}

    rows = []
    for id, name, typ, opening_balance, is_archived, is_debt in accs:

        bal = Decimal(opening_balance or 0) + txsum.get(id, Decimal(0))
        rows.append({
            "id": id,
            "name": name,
            "type": typ,
            "balance": float(bal),
            "arch": is_archived,
            "is_debt": is_debt,
        })
        
    return templates.TemplateResponse("accounts_list.html", {"request": request, "rows": rows})


@router.get("/accounts/new", response_class=HTMLResponse)
async def accounts_new(request: Request, session: AsyncSession = Depends(get_session)):
    types = await get_account_types(session)
    return templates.TemplateResponse("accounts_new.html", {"request": request, "types": types})


@router.post("/accounts")
async def accounts_create(
    name: str = Form(...),
    type: str = Form(...),
    opening_balance: float = Form(0.0),
    is_debt: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    default_is_debt = next(
        (
            t["is_debt"]
            for t in DEFAULT_ACCOUNT_TYPES
            if t["name"].lower() == type.lower()
        ),
        False,
    )
    session.add(
        Account(
            name=name,
            type=type,
            opening_balance=Decimal(opening_balance),
            is_debt=_normalize_is_debt(is_debt, default_is_debt),
        )
    )
    await session.commit()
    return RedirectResponse(url="/accounts", status_code=303)


@router.get("/accounts/{acc_id}/edit", response_class=HTMLResponse)
async def accounts_edit(acc_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    a = await session.get(Account, UUID(acc_id))
    if not a:
        return RedirectResponse(url="/accounts", status_code=303)
    types = await get_account_types(session)
    return templates.TemplateResponse("accounts_edit.html", {"request": request, "acc": a, "types": types})


@router.post("/accounts/{acc_id}/edit")
async def accounts_update(
    acc_id: str,
    name: str = Form(...),
    type: str = Form(...),
    opening_balance: float = Form(...),
    is_archived: str | None = Form(None),
    is_debt: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    a = await session.get(Account, UUID(acc_id))
    if not a:
        return RedirectResponse(url="/accounts", status_code=303)
    a.name = name
    a.type = type
    a.opening_balance = Decimal(opening_balance)
    a.is_archived = bool(is_archived)
    default_is_debt = next(
        (
            t["is_debt"]
            for t in DEFAULT_ACCOUNT_TYPES
            if t["name"].lower() == type.lower()
        ),
        False,
    )
    a.is_debt = _normalize_is_debt(is_debt, default_is_debt)
    await session.commit()
    return RedirectResponse(url="/accounts", status_code=303)
