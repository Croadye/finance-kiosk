from __future__ import annotations
from datetime import date
from typing import List
from sqlalchemy import select
from fastapi import Request
from uuid import UUID
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.templating import Jinja2Templates

from ..db import get_session
from ..models import Account, Category, Transaction, TxSplit

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# ---------- LIST ----------


@router.get("/transactions", response_class=HTMLResponse)
async def list_txs(
    request: Request,
    session: AsyncSession = Depends(get_session),
    page: int = 1,
    per: int = 25,
    q: Optional[str] = None,
):
    offset = max(0, (page - 1) * per)

    # Filter only on Transaction fields (fast + simple)
    filters = []
    if q:
        ilike = f"%{q}%"
        filters.append((Transaction.payee.ilike(ilike))
                       | (Transaction.memo.ilike(ilike)))

    # Fetch IDs for the current page
    count_stmt = select(func.count()).select_from(Transaction)
    if filters:
        count_stmt = count_stmt.where(*filters)

    total = int((await session.scalar(count_stmt)) or 0)

    if total == 0:
        return templates.TemplateResponse("transactions_list.html", {
            "request": request,
            "rows": [],
            "q": q or "",
            "page": page,
            "per": per,
            "total": total,
        })

    # Apply filters, ordering, and pagination directly when fetching IDs
    id_stmt = select(Transaction.id).order_by(
        Transaction.ts.desc()).offset(offset).limit(per)
    if filters:
        id_stmt = id_stmt.where(*filters)

    page_ids = (await session.execute(id_stmt)).scalars().all()

    if not page_ids:
        return templates.TemplateResponse("transactions_list.html", {
            "request": request,
            "rows": [],
            "q": q or "",
            "page": page,
            "per": per,
            "total": total,
        })

    # Load display rows + a sample category (min over names)
    rows = (await session.execute(
        select(
            Transaction.id, Transaction.ts, Transaction.amount,
            Transaction.payee, Transaction.memo,
            Account.name.label("account_name"),
            func.min(Category.name).label("category_name")
        )
        .join(Account, Account.id == Transaction.account_id)
        .outerjoin(TxSplit, TxSplit.transaction_id == Transaction.id)
        .outerjoin(Category, Category.id == TxSplit.category_id)
        .where(Transaction.id.in_(page_ids))
        .group_by(Transaction.id, Account.name)
        .order_by(Transaction.ts.desc())
    )).all()

    return templates.TemplateResponse("transactions_list.html", {
        "request": request,
        "rows": rows,
        "q": q or "",
        "page": page, "per": per, "total": total
    })


@router.get("/transactions/new", response_class=HTMLResponse)
async def transactions_new(request: Request, session: AsyncSession = Depends(get_session)):
    accounts_rows = (await session.execute(
        select(Account.id, Account.name).order_by(Account.name)
    )).all()
    categories_rows = (await session.execute(
        select(Category.id, Category.name).order_by(Category.name)
    )).all()

    # Flatten rows for Jinja loops (server-side)
    accounts = [(r[0], r[1]) for r in accounts_rows]
    categories = [(r[0], r[1]) for r in categories_rows]

    # JSON-friendly version for the JS block (client-side)
    categories_js = [[str(r[0]), r[1]] for r in categories_rows]

    today = date.today().isoformat()
    return templates.TemplateResponse(
        "transactions_new.html",
        {
            "request": request,
            "accounts": accounts,
            "categories": categories,
            "categories_js": categories_js,   # <— add this
            "today": today,
        },
    )


@router.post("/transactions")
async def transactions_create(
    tx_date: str = Form(...),
    account_id: str = Form(...),
    kind: str = Form("expense"),           # "expense" or "income"
    payee: str = Form(""),
    memo: str = Form(""),
    # Optional single-amount fallback if no splits were provided in the form
    amount: float = Form(0.0),
    # Split arrays (may be empty). Names end with [] in the form.
    split_category_id: List[str] = Form([]),
    split_memo: List[str] = Form([]),
    split_amount: List[float] = Form([]),
    session: AsyncSession = Depends(get_session),
):
    # Normalize: keep only rows with a category and a non-zero amount
    splits_clean = []
    for i in range(len(split_amount)):
        amt = float(split_amount[i] or 0)
        cat = (split_category_id[i] or "").strip(
        ) if i < len(split_category_id) else ""
        smemo = split_memo[i] if i < len(split_memo) else ""
        if cat and abs(amt) > 0:
            splits_clean.append((cat, smemo, abs(amt)))

    # Compute signed total; splits take precedence if present
    if splits_clean:
        base = sum(a for _, _, a in splits_clean)
    else:
        base = abs(amount)

    signed_total = -abs(base) if kind == "expense" else abs(base)

    tx = Transaction(
        account_id=UUID(account_id),
        date=date.fromisoformat(tx_date),
        amount=signed_total,
        payee=payee.strip()[:80] if payee else None,
        memo=memo.strip()[:200] if memo else None,
    )
    session.add(tx)
    await session.flush()  # get tx.id

    if splits_clean:
        # Store split amounts with the same sign as the transaction
        for cat, smemo, a in splits_clean:
            session.add(TxSplit(
                transaction_id=tx.id,
                category_id=UUID(cat),
                amount=(-abs(a) if kind == "expense" else abs(a)),
                memo=(smemo or "")[:200] or None
            ))
    else:
        # No splits given → create a single split using optional category from the form (if you add one),
        # or leave splits empty and let category be “uncategorized” in reports. Here we leave it empty.
        pass

    await session.commit()
    return RedirectResponse(url="/transactions", status_code=303)


@router.get("/transactions/{tx_id}/edit", response_class=HTMLResponse)
async def edit_tx(
    tx_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    tx = await session.get(Transaction, UUID(tx_id))
    if not tx:
        return RedirectResponse(url="/transactions", status_code=303)

    accounts = (await session.execute(select(Account.id, Account.name))).all()
    categories = (await session.execute(
        select(Category.id, Category.name).where(Category.is_hidden == False)
    )).all()
    splits = (await session.execute(
        select(TxSplit)
        .where(TxSplit.transaction_id == tx.id)
        .order_by(TxSplit.id.asc())   # was: TxSplit.created_at.asc()
    )).scalars().all()

    # infer kind from tx sign (default expense if zero)
    kind = "income" if (tx.amount or 0) > 0 else "expense"
    total_abs = float(abs(tx.amount or 0))

    return templates.TemplateResponse("transactions_edit.html", {
        "request": request,
        "tx": tx,
        "accounts": accounts,
        "categories": categories,
        "splits": splits,
        "kind": kind,
        "total_abs": total_abs,
    })


@router.post("/transactions/{tx_id}/edit")
async def update_tx(
    tx_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    form = await request.form()

    tx = await session.get(Transaction, UUID(tx_id))
    if not tx:
        return RedirectResponse(url="/transactions", status_code=303)

    # basic fields
    tx.account_id = UUID(form["account_id"])
    tx.payee = (form.get("payee") or None)
    tx.memo = (form.get("memo") or None)
    kind = form.get("kind", "expense")  # expense|income

    # remove all existing splits, rebuild from form
    existing = (await session.execute(
        select(TxSplit).where(TxSplit.transaction_id == tx.id)
    )).scalars().all()
    for s in existing:
        await session.delete(s)

    cat_ids = form.getlist("split_category_id")  # multiple
    amts = form.getlist("split_amount")

    total = Decimal("0")
    for cat_id, raw in zip(cat_ids, amts):
        raw = (raw or "").strip()
        if raw == "":
            continue
        try:
            val = Decimal(raw)
        except:
            continue
        signed = -abs(val) if kind == "expense" else abs(val)

        session.add(TxSplit(
            transaction_id=tx.id,
            category_id=UUID(cat_id) if cat_id else None,
            amount=signed
        ))
        total += signed

    # transaction total = sum of splits (keeps everything consistent)
    tx.amount = total

    await session.commit()
    return RedirectResponse(url="/transactions", status_code=303)

# ---------- DELETE ----------


@router.post("/transactions/{tx_id}/delete")
async def delete_tx(tx_id: str, session: AsyncSession = Depends(get_session)):
    tx = await session.get(Transaction, UUID(tx_id))
    if tx:
        await session.delete(tx)  # cascades to splits
        await session.commit()
    return RedirectResponse(url="/transactions", status_code=303)
