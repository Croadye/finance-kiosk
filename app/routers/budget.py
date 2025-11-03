from __future__ import annotations
import uuid
from decimal import Decimal
from datetime import datetime, date, timedelta

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Category, Budget, TxSplit, Transaction

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def month_bounds(month_str: str | None) -> tuple[date, date]:
    # month_str like "2025-11"; default = now
    if month_str:
        y, m = [int(x) for x in month_str.split("-")]
        start = date(y, m, 1)
    else:
        now = datetime.now()
        start = date(now.year, now.month, 1)
    # next month
    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)
    return start, end


@router.get("/budget", response_class=HTMLResponse)
async def budget_get(request: Request, month: str | None = None, session: AsyncSession = Depends(get_session)):
    month_start, month_end = month_bounds(month)
    month_key = month_start  # Budget.month uses first day of month

    # 1) Categories (visible)
    cats = (await session.execute(
        select(Category.id, Category.name, Category.group)
        .where(Category.is_hidden == False)
        .order_by(Category.group.nulls_last(), Category.name)
    )).all()

    cat_ids = [c.id for c in cats]

    # 2) Budgets for this month
    bud_rows = (await session.execute(
        select(Budget.category_id, Budget.planned)
        .where(Budget.month == month_key)
        .where(Budget.category_id.in_(cat_ids))
    )).all()
    planned_by_cat = {r.category_id: Decimal(r.planned) for r in bud_rows}

    # 3) Spend per category this month (sum of splits on tx in range)
    spend_rows = (await session.execute(
        select(TxSplit.category_id, func.coalesce(func.sum(TxSplit.amount), 0))
        .join(Transaction, Transaction.id == TxSplit.transaction_id)
        .where(Transaction.ts >= month_start)
        .where(Transaction.ts < month_end)
        .where(TxSplit.category_id.in_(cat_ids))
        .group_by(TxSplit.category_id)
    )).all()

    # Tx amounts are negative for expense, positive for income.
    # "spent" should be positive dollars out.
    spent_by_cat = {}
    for cid, raw_sum in spend_rows:
        s = Decimal(raw_sum)
        spent_by_cat[cid] = -s if s < 0 else Decimal("0")

    # Build rows for template
    rows = []
    total_planned = Decimal("0")
    total_spent = Decimal("0")
    for cid, name, group in cats:
        planned = planned_by_cat.get(cid, Decimal("0"))
        spent = spent_by_cat.get(cid, Decimal("0"))
        available = planned - spent

        rows.append({
            "id": cid,
            "name": name,
            "group": group or "",
            "planned": planned,
            "spent": spent,
            "available": available,
        })
        total_planned += planned
        total_spent += spent

    return templates.TemplateResponse("budget.html", {
        "request": request,
        "rows": rows,
        "month_str": month_start.strftime("%Y-%m"),
        "total_planned": total_planned,
        "total_spent": total_spent,
        "total_available": total_planned - total_spent,
    })


@router.post("/budget/update")
async def budget_update(
    month: str = Form(...),
    session: AsyncSession = Depends(get_session),
    request: Request = None,
):
    month_start, _ = month_bounds(month)
    form = await request.form()
    # Expect inputs named planned_<uuid>
    updates: list[tuple[uuid.UUID, Decimal]] = []
    for k, v in form.items():
        if not k.startswith("planned_"):
            continue
        cid = uuid.UUID(k.split("_", 1)[1])
        try:
            planned = Decimal(str(v or "0").strip())
        except:
            planned = Decimal("0")
        updates.append((cid, planned))

    # Upsert budgets for this month
    for cid, planned in updates:
        row = (await session.execute(
            select(Budget).where(Budget.category_id ==
                                 cid, Budget.month == month_start)
        )).scalars().first()
        if row:
            row.planned = planned
        else:
            session.add(
                Budget(category_id=cid, month=month_start, planned=planned))

    await session.commit()
    return RedirectResponse(url=f"/budget?month={month}", status_code=303)
