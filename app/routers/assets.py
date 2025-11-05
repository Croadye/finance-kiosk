from __future__ import annotations
from datetime import datetime, date, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Asset

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
    rows = (
        (
            await session.execute(
                select(Asset).where(Asset.is_archived ==
                                    False).order_by(Asset.name)
            )
        )
        .scalars()
        .all()
    )

    total_assets = sum([a.estimate_value or 0 for a in rows])
    types = await get_asset_types(session)
    return templates.TemplateResponse(
        "assets_list.html",
        {
            "request": request,
            "assets": rows,
            "total_assets": total_assets,
            "types": types,
        },
    )


@router.get("/assets/new", response_class=HTMLResponse)
async def assets_new(request: Request, session: AsyncSession = Depends(get_session)):
    types = await get_asset_types(session)
    return templates.TemplateResponse(
        "assets_new.html",
        {
            "request": request,
            "types": types,
            "today": date.today().isoformat(),
        },
    )


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
        meta.update(
            {
                "year": year,
                "make": make,
                "model": model,
                "trim": trim,
                "mileage": mileage,
                "zip": zip,
                "vin": vin,
            }
        )
    elif kind == "electronics":
        meta.update({"details": f"{make} {model} {trim}".strip()})

    meta = {k: v for k, v in meta.items() if str(v).strip()}
    meta.pop("vin", None)

    raw_value = est_value.strip()
    raw_source = est_source.strip().lower()

    value: Decimal | None = None
    if raw_value:
        try:
            value = Decimal(str(raw_value).replace(",", ""))
        except InvalidOperation as exc:
            raise HTTPException(status_code=422,
                                detail="Invalid estimated value") from exc

    source = raw_source or None
    if value is not None:
        source = source or "manual"

    if source and value is None:
        raise HTTPException(
            status_code=422,
            detail="Tracked assets require an estimated value.",
        )

    estimate_at = datetime.now(timezone.utc) if value is not None else None


    a = Asset(
        name=name.strip(),
        kind=kind.strip().lower(),
        estimate_value=value,
        estimate_source=source,
        estimate_at=estimate_at,
        meta=meta or None,
        vin=vin.strip() or None,
        is_archived=False,
    )
    session.add(a)
    await session.commit()
    return RedirectResponse(url="/assets?notice=created", status_code=303)


@router.get("/assets/{asset_id}/edit", response_class=HTMLResponse)
async def assets_edit(
    asset_id: str, request: Request, session: AsyncSession = Depends(get_session)
):
    a = await session.get(Asset, UUID(asset_id))
    if not a:
        return RedirectResponse(url="/assets?error=not_found", status_code=303)
    types = await get_asset_types(session)
    return templates.TemplateResponse(
        "assets_edit.html", {"request": request, "a": a, "types": types}
    )


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
        meta.update(
            {
                "year": year,
                "make": make,
                "model": model,
                "trim": trim,
                "mileage": mileage,
                "zip": zip,
                "vin": vin,
            }
        )
    elif kind == "electronics":
        meta.update({"details": f"{make} {model} {trim}".strip()})

    meta = {k: v for k, v in meta.items() if str(v).strip()}
    meta.pop("vin", None)

    a.name = name.strip()
    a.kind = kind.strip().lower()
    a.meta = meta or None
    a.vin = vin.strip() or None
    raw_value = est_value.strip()
    raw_source = est_source.strip().lower()

    new_value: Decimal | None = None
    if raw_value:
        try:
            new_value = Decimal(str(raw_value).replace(",", ""))
        except InvalidOperation as exc:
            raise HTTPException(status_code=422,
                                detail="Invalid estimated value") from exc

    if new_value is not None:
        source = raw_source or "manual"
        a.estimate_value = new_value
        a.estimate_source = source
        a.estimate_at = datetime.now(timezone.utc)
    elif raw_source:
        a.estimate_source = raw_source

    final_source = a.estimate_source
    if final_source and a.estimate_value is None:
        raise HTTPException(
            status_code=422,
            detail="Tracked assets require an estimated value.",
        )
    await session.commit()
    return RedirectResponse(url="/assets?notice=updated", status_code=303)


@router.post("/assets/{asset_id}/archive")
async def assets_archive(asset_id: str, session: AsyncSession = Depends(get_session)):
    a = await session.get(Asset, UUID(asset_id))
    if a:
        a.is_archived = True
        await session.commit()
    return RedirectResponse(url="/assets?notice=archived", status_code=303)
