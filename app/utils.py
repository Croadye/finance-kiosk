from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import List, Dict, Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from .models import Account, Transaction

DEFAULT_ACCOUNT_TYPES: List[Dict[str, Any]] = [
    {"name": "checking",      "is_debt": False},
    {"name": "savings",       "is_debt": False},
    {"name": "cash",          "is_debt": False},
    {"name": "credit",        "is_debt": True},
    {"name": "mortgage",      "is_debt": True},
    {"name": "auto_loan",     "is_debt": True},
    {"name": "home_loan",     "is_debt": True},
    {"name": "personal_loan", "is_debt": True},
    {"name": "investment",    "is_debt": False},
]


async def get_account_types(session: AsyncSession) -> List[Dict[str, Any]]:
    
    return DEFAULT_ACCOUNT_TYPES
    


def month_start(d: date) -> date:
    return d.replace(day=1)


async def calculate_current_networth(session: AsyncSession) -> Decimal:
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

