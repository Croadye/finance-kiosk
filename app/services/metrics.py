# app/services/metrics.py
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Account, Transaction, Asset, TxSplit

DEFAULT_ACCOUNT_TYPES = [
    {"name": "Checking", "is_debt": False},
    {"name": "Savings", "is_debt": False},
    {"name": "Investment", "is_debt": False},
    {"name": "Credit Card", "is_debt": True},
    {"name": "Loan", "is_debt": True},
]


async def _get_account_types(session: AsyncSession) -> dict:
    items = (DEFAULT_ACCOUNT_TYPES)
    return {t["name"].lower(): t for t in items}


async def get_account_balances(session: AsyncSession) -> list[dict]:
    """
    Current balance per account:
    opening_balance + SUM(transactions.amount)
    (archived accounts excluded)
    """
    q = (
        select(
            Account.id,
            Account.name,
            Account.type,
            (Account.opening_balance +
             func.coalesce(func.sum(Transaction.amount), 0)).label("balance"),
        )
        .select_from(Account)
        .outerjoin(Transaction, Transaction.account_id == Account.id)
        .where(Account.is_archived.is_(False))
        .group_by(Account.id)
        .order_by(Account.name)
    )
    res = await session.execute(q)
    return [dict(r._mapping) for r in res]


def _to_decimal(v) -> Decimal:
    if isinstance(v, Decimal):
        return v
    if v is None:
        return Decimal("0")
    return Decimal(str(v))


async def _assets_total(session: AsyncSession) -> Decimal:
    # Sum the manual/estimated values of non-archived assets
    val = (await session.execute(
        select(func.coalesce(func.sum(Asset.estimate_value), 0))
        .where(Asset.is_archived.is_(False))
    )).scalar_one()
    return _to_decimal(val)


async def _spent_this_month(session: AsyncSession) -> float:
    # Use splits if present (negative split = expense)
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    if hasattr(TxSplit, "amount"):
        q = (
            select(func.coalesce(func.sum(-TxSplit.amount), 0.0))
            .select_from(TxSplit)
            .join(Transaction, Transaction.id == TxSplit.transaction_id)
            .where(Transaction.ts >= month_start, TxSplit.amount < 0)
        )
        return float((await session.execute(q)).scalar_one())

    # Fallback if no splits
    q2 = select(func.coalesce(func.sum(-Transaction.amount), 0.0)).where(
        Transaction.ts >= month_start, Transaction.amount < 0
    )
    return float((await session.execute(q2)).scalar_one())


async def calc_dashboard_metrics(session: AsyncSession) -> dict:
    types = await _get_account_types(session)
    balances = await get_account_balances(session)
    assets_total = await _assets_total(session)

    # Totals from accounts
    net_accounts = sum(b["balance"] for b in balances)

    # Debts: sum of amounts owed (positive number)
    current_debts = sum((-b["balance"]) if b["balance"] < 0 else 0
                        for b in balances
                        if types.get(b["type"].lower(), {}).get("is_debt", True))

    # Cash available: positive balances on non-debt accounts
    current_cash = sum(b["balance"] for b in balances
                       if not types.get(b["type"].lower(), {}).get("is_debt", False) and b["balance"] > 0)

    net_worth = net_accounts + assets_total
    spent_this_month = await _spent_this_month(session)

    return {
        "account_balances": balances,
        "assets_total": sum((assets_total,current_cash)),
        "current_debts": current_debts,
        "current_cash": current_cash,
        "net_worth": net_worth,
        "spent_this_month": spent_this_month,
    }
