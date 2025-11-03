# app/services/metrics.py
from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Account, Transaction, Asset

DEFAULT_ACCOUNT_TYPES = [
    {"name": "checking",   "is_debt": False, "is_cash": True},
    {"name": "savings",    "is_debt": False, "is_cash": True},
    {"name": "cash",       "is_debt": False, "is_cash": True},
    {"name": "credit_card", "is_debt": True,  "is_cash": False},
    {"name": "loan",       "is_debt": True,  "is_cash": False},
    {"name": "mortgage",   "is_debt": True,  "is_cash": False},
    {"name": "investment", "is_debt": False, "is_cash": False},
    {"name": "other",      "is_debt": False, "is_cash": False},
]


def _safe_decimal(v: Any) -> Decimal:
    if isinstance(v, Decimal):
        return v
    if v is None:
        return Decimal("0")
    return Decimal(str(v))


async def _load_account_types(session: AsyncSession):
    """Read account_types from settings; fall back to sane defaults."""
   
    types = DEFAULT_ACCOUNT_TYPES

    # normalize
    by_name = {}
    for t in types:
        name = str(t.get("name", "")).strip().lower()
        if not name:
            continue
        by_name[name] = {
            "is_debt": bool(t.get("is_debt", False)),
            "is_cash": bool(t.get("is_cash", False)),
        }
    return by_name


async def _account_balances(session: AsyncSession):
    """Return list of (id, name, type, balance) where balance = sum(transactions)."""
    rows = (await session.execute(
        select(
            Account.id,
            Account.name,
            Account.type,
            func.coalesce(func.sum(Transaction.amount), 0).label("balance"),
        )
        .join(Transaction, Transaction.account_id == Account.id, isouter=True)
        .group_by(Account.id)
        .order_by(Account.name)
    )).all()
    # coerce to simple dicts with Decimal balance
    out = []
    for r in rows:
        # row tuple ordering matches select above
        aid, name, atype, bal = r
        out.append({
            "id": aid,
            "name": name,
            "type": (atype or "").lower(),
            "balance": _safe_decimal(bal),
        })
    return out


async def compute_dashboard_metrics(session: AsyncSession):
    """Core numbers for the dashboard header cards."""
    types = await _load_account_types(session)
    balances = await _account_balances(session)

    debt_types = {n for n, f in types.items() if f.get("is_debt")}
    cash_types = {n for n, f in types.items() if f.get("is_cash")}
    # fallback if user removed flags
    if not cash_types:
        cash_types = {"checking", "savings", "cash"}

    # Accounts-based values
    net_accounts = sum((b["balance"] for b in balances), Decimal("0"))

    debt_by_type = sum((max(Decimal(
        "0"), -b["balance"]) for b in balances if b["type"] in debt_types), Decimal("0"))
    overdraft = sum((max(Decimal("0"), -b["balance"])
                    for b in balances if b["type"] not in debt_types), Decimal("0"))
    current_debts = debt_by_type + overdraft

    cash_available = sum((b["balance"] for b in balances if b["type"]
                         in cash_types and b["balance"] > 0), Decimal("0"))

    # Assets (not archived)
    total_assets_value = _safe_decimal((await session.execute(
        select(func.coalesce(func.sum(Asset.estimate_value), 0)).where(
            Asset.is_archived == False)
    )).scalar_one())

    # Net worth = accounts (assets minus liabilities already baked into balances)
    #           + standalone asset valuations (home/cars/etc.)
    net_worth = net_accounts + total_assets_value

    # Spent this month (simple, transfer-safe): negative amounts this month excluding transfers
    today = date.today()
    month_start = date(today.year, today.month, 1)
    spent_this_month = _safe_decimal((await session.execute(
        select(func.coalesce(-func.sum(Transaction.amount), 0))
        .where(Transaction.ts >= month_start)
        .where(Transaction.amount < 0)
        .where(Transaction.transfer_group_id.is_(None))
    )).scalar_one())

    return {
        "balances": balances,                 # detailed per-account if you want a table
        "net_accounts": net_accounts,
        "total_assets_value": total_assets_value,
        "net_worth": net_worth,
        "current_debts": current_debts,
        "cash_available": cash_available,
        "spent_this_month": spent_this_month,
    }
