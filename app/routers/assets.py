from __future__ import annotations
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Setting
from ..utils import calculate_current_networth, get_networth_offset

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _parse_decimal(value: str | None) -> Decimal:
    if not value:
        return Decimal(0)
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError):
        return Decimal(0)


async def _store_networth_offset(session: AsyncSession, baseline: Decimal, raw_net: Decimal) -> None:
    offset = baseline - raw_net
    row = await session.get(Setting, "networth_offset")
    if row:
        row.v_json = {"offset": float(offset)}
    else:
        session.add(Setting(k="networth_offset",
                    v_json={"offset": float(offset)}))
    await session.commit()


@router.get("/assets", response_class=HTMLResponse)
async def assets_overview(request: Request, session: AsyncSession = Depends(get_session)):
    raw_net = await calculate_current_networth(session)
    offset = await get_networth_offset(session)
    display_net = raw_net + offset
    return templates.TemplateResponse(
        "assets_overview.html",
        {
            "request": request,
            "raw_net": float(raw_net),
            "offset": float(offset),
            "display_net": float(display_net),
        },
    )


@router.post("/assets/baseline")
async def assets_baseline(
    home_value: str = Form(""),
    vehicles_value: str = Form(""),
    bank_total_now: str = Form(""),
    cc_debt_now: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    baseline = (
        _parse_decimal(home_value)
        + _parse_decimal(vehicles_value)
        + _parse_decimal(bank_total_now)
        - _parse_decimal(cc_debt_now)
    )
    raw_net = await calculate_current_networth(session)
    await _store_networth_offset(session, baseline, raw_net)
    return RedirectResponse(url="/assets", status_code=303)
