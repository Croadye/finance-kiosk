from __future__ import annotations
from datetime import datetime, date
from decimal import Decimal
from uuid import UUID, uuid4
from typing import Optional

from fastapi import APIRouter, Depends, Request, Form, Body, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Asset
from ..services.valuations import estimate_home_value, estimate_vehicle_value

templates = Jinja2Templates(directory="app/templates")

router = APIRouter()

DEFAULT_ASSET_TYPES = [
    {"name": "home"},
    {"name": "vehicle"},
    {"name": "trailer"},
    {"name": "electronics"},
    {"name": "other"},
]


async def get_asset_types(session: AsyncSession):
    return [t["name"] for t in DEFAULT_ASSET_TYPES]


@router.get("/assets", response_class=HTMLResponse)
async def assets_index(request: Request, session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(Asset).where(Asset.is_archived == False).order_by(Asset.name)
    )).scalars().all()

    total_assets = sum([a.estimate_value or 0 for a in rows])
    types = await get_asset_types(session)
    return templates.TemplateResponse("assets_list.html", {
        "request": request,
        "assets": rows,
        "total_assets": total_assets,
        "types": types,
    })


@router.get("/assets/new", response_class=HTMLResponse)
async def assets_new(request: Request, session: AsyncSession = Depends(get_session)):
    types = await get_asset_types(session)
    return templates.TemplateResponse("assets_new.html", {
        "request": request,
        "types": types,
        "today": date.today().isoformat(),
    })


@router.post("/assets")
async def assets_create(
    name: str = Form(...),
    # home | vehicle | trailer | electronics | other
    kind: str = Form(...),
    est_value: str = Form(""),
    est_source: str = Form(""),
    # generic details (we’ll stash in meta)
    address: str = Form(""),
    city: str = Form(""),
    state: str = Form(""),
    zip: str = Form(""),
    year: str = Form(""),
    make: str = Form(""),
    model: str = Form(""),
    trim: str = Form(""),
    vin: str = Form(""),
    mileage: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    meta = {}
    if kind == "home":
        meta.update({"address": address, "city": city,
                    "state": state, "zip": zip})
    elif kind in ("vehicle", "trailer"):
        meta.update({"year": year, "make": make, "model": model,
                    "trim": trim, "mileage": mileage, "zip": zip, "vin": vin})
    elif kind == "electronics":
        meta.update({"details": f"{make} {model} {trim}".strip()})

    meta = {k: v for k, v in meta.items() if str(v).strip()}
    meta.pop("vin", None)

    value: Decimal | None = None
    if est_value.strip():
        value = Decimal(str(est_value).replace(",", "").strip())
        
    source = est_source.strip().lower()
    if value is None:
        source = None
    elif not source:
        source = "manual"

    a = Asset(
        name=name.strip(),
        kind=kind.strip().lower(),
        estimate_value=value,
        estimate_source=source,
        estimate_at=datetime.utcnow() if value is not None else None,
        meta=meta or None,
        vin=vin.strip() or None,
        is_archived=False,
    )
    session.add(a)
    await session.commit()
    return RedirectResponse(url="/assets?notice=created", status_code=303)


@router.get("/assets/{asset_id}/edit", response_class=HTMLResponse)
async def assets_edit(asset_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    a = await session.get(Asset, UUID(asset_id))
    if not a:
        return RedirectResponse(url="/assets?error=not_found", status_code=303)
    types = await get_asset_types(session)
    return templates.TemplateResponse("assets_edit.html", {"request": request, "a": a, "types": types})


@router.post("/assets/{asset_id}/edit")
async def assets_update(
    asset_id: str,
    name: str = Form(...),
    kind: str = Form(...),
    est_value: str = Form(""),
    est_source: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    state: str = Form(""),
    zip: str = Form(""),
    year: str = Form(""),
    make: str = Form(""),
    model: str = Form(""),
    trim: str = Form(""),
    mileage: str = Form(""),
    vin: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    a = await session.get(Asset, UUID(asset_id))
    if not a:
        return RedirectResponse(url="/assets?error=not_found", status_code=303)

    meta = {}
    if kind == "home":
        meta.update({"address": address, "city": city,
                    "state": state, "zip": zip})
    elif kind in ("vehicle", "trailer"):
        meta.update({"year": year, "make": make, "model": model,
                    "trim": trim, "mileage": mileage, "zip": zip, "vin": vin})
    elif kind == "electronics":
        meta.update({"details": f"{make} {model} {trim}".strip()})
        
    meta = {k: v for k, v in meta.items() if str(v).strip()}
    meta.pop("vin", None)
    
    a.name = name.strip()
    a.kind = kind.strip().lower()
    a.meta = meta or None
    a.vin = vin.strip() or None
    if est_value.strip():
        a.estimate_value = Decimal(str(est_value).replace(",", "").strip())
        source = est_source.strip().lower() or "manual"
        a.estimate_source = source
        a.estimate_at = datetime.utcnow()
    await session.commit()
    return RedirectResponse(url="/assets?notice=updated", status_code=303)


@router.post("/assets/estimates/zillow")
async def estimate_from_zillow(payload: dict = Body(...)):
    try:
        value = estimate_home_value(
            payload.get("address", ""),
            payload.get("city", ""),
            payload.get("state", ""),
            payload.get("zip", ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse({
        "value": f"{value:.2f}",
        "source": "zillow",
    })


@router.post("/assets/estimates/kbb")
async def estimate_from_kbb(payload: dict = Body(...)):
    try:
        value = estimate_vehicle_value(
            payload.get("year", ""),
            payload.get("make", ""),
            payload.get("model", ""),
            payload.get("trim", ""),
            payload.get("mileage", ""),
            payload.get("zip", ""),
            payload.get("vin"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse({
        "value": f"{value:.2f}",
        "source": "kbb",
    })

@router.post("/assets/{asset_id}/archive")
async def assets_archive(asset_id: str, session: AsyncSession = Depends(get_session)):
    a = await session.get(Asset, UUID(asset_id))
    if a:
        a.is_archived = True
        await session.commit()
    return RedirectResponse(url="/assets?notice=archived", status_code=303)
