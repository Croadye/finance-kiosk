from __future__ import annotations
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_session
from ..models import Setting
from ..utils import (
    DEFAULT_ACCOUNT_TYPES,
    calculate_current_networth,
    get_account_types,
    get_networth_offset,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/settings/networth", response_class=HTMLResponse)
async def networth_get(request: Request, session: AsyncSession = Depends(get_session)):
    raw_net = await calculate_current_networth(session)
    offset = await get_networth_offset(session)
    return templates.TemplateResponse("settings_networth.html", {
        "request": request, "raw_net": float(raw_net), "offset": float(offset),
        "display_net": float(raw_net + offset),
    })

@router.post("/settings/networth")
async def networth_post(
    home_value: str = Form(""),
    vehicles_value: str = Form(""),
    bank_total_now: str = Form(""),
    cc_debt_now: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    return RedirectResponse(url="/assets", status_code=303)



@router.get("/settings/account-types", response_class=HTMLResponse)
async def account_types_get(request: Request, session: AsyncSession = Depends(get_session)):
    types = await get_account_types(session)
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
