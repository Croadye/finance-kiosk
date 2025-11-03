from __future__ import annotations
from decimal import Decimal
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_session
from ..models import Setting, Account, Transaction
from ..utils import DEFAULT_ACCOUNT_TYPES

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


@router.get("/settings/account-types", response_class=HTMLResponse)
async def account_types_get(request: Request, session: AsyncSession = Depends(get_session)):
    row = await session.get(Setting, "account_types")
    types = row.v_json if (row and row.v_json) else DEFAULT_ACCOUNT_TYPES
    return templates.TemplateResponse("settings_account_types.html", {"request": request, "types": types})


@router.post("/settings/account-types/add")
async def account_types_add(
    name: str = Form(...),
    is_debt: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(Setting, "account_types")
    types = (row.v_json if (row and row.v_json)
             else DEFAULT_ACCOUNT_TYPES).copy()
    if not any(t["name"].lower() == name.strip().lower() for t in types):
        types.append({"name": name.strip(), "is_debt": bool(is_debt)})
    if row:
        row.v_json = types
    else:
        session.add(Setting(k="account_types", v_json=types))
    await session.commit()
    return RedirectResponse(url="/settings/account-types", status_code=303)


@router.post("/settings/account-types/update")
async def account_types_update(request: Request, session: AsyncSession = Depends(get_session)):
    form = await request.form()
    # Expect rows as name_i, is_debt_i, with hidden count field 'n'
    n = int(form.get("n", "0"))
    new_list = []
    for i in range(n):
        name = (form.get(f"name_{i}") or "").strip()
        if not name:
            continue
        is_debt = form.get(f"is_debt_{i}") is not None
        new_list.append({"name": name, "is_debt": is_debt})
    row = await session.get(Setting, "account_types")
    if row:
        row.v_json = new_list
    else:
        session.add(Setting(k="account_types", v_json=new_list))
    await session.commit()
    return RedirectResponse(url="/settings/account-types", status_code=303)
