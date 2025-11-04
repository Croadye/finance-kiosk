from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Category

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def _fetch_categories(session: AsyncSession):
    result = await session.execute(
        select(Category).order_by(
            Category.group.is_(None),
            Category.group,
            Category.name,
        )
    )
    return result.scalars().all()


@router.get("/categories", response_class=HTMLResponse)
async def categories_list(
    request: Request,
    session: AsyncSession = Depends(get_session),
    created: str | None = None,
    error: str | None = None,
):
    categories = await _fetch_categories(session)
    return templates.TemplateResponse(
        "categories_list.html",
        {
            "request": request,
            "categories": categories,
            "created": created,
            "error": error,
            "form_name": "",
            "form_group": "",
        },
    )


@router.post("/categories", response_class=HTMLResponse)
async def categories_create(
    request: Request,
    name: str = Form(...),
    group: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    cleaned_name = name.strip()
    cleaned_group = group.strip()

    if not cleaned_name:
        categories = await _fetch_categories(session)
        return templates.TemplateResponse(
            "categories_list.html",
            {
                "request": request,
                "categories": categories,
                "error": "Category name is required.",
                "created": None,
                "form_name": name,
                "form_group": group,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    category = Category(name=cleaned_name, group=cleaned_group or None)
    session.add(category)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        categories = await _fetch_categories(session)
        return templates.TemplateResponse(
            "categories_list.html",
            {
                "request": request,
                "categories": categories,
                "error": "A category with that name already exists.",
                "created": None,
                "form_name": name,
                "form_group": group,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse("/categories?created=1", status_code=status.HTTP_303_SEE_OTHER)
