# app/services/metrics.py
from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import and_, case, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Account, Transaction, Asset, TxSplit

DEFAULT_ACCOUNT_TYPES = [
    {"name": "Checking", "is_debt": False},
    {"name": "Savings", "is_debt": False},
    {"name": "Investment", "is_debt": False},
    {"name": "Credit Card", "is_debt": True},
    {"name": "Loan", "is_debt": True},
]


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



def _account_running_balance_expr(account_tbl: Account, tx_sum_alias):
    """opening_balance + sum(tx.amount)"""
    return (account_tbl.opening_balance + func.coalesce(tx_sum_alias.c.sum_amt, 0))


def _tx_sum_by_account():
    return (
        select(
            Transaction.account_id.label("account_id"),
            func.coalesce(func.sum(Transaction.amount), 0).label("sum_amt"),
        )
        .group_by(Transaction.account_id)
        .subquery()
    )


async def accounts_net_total(session):
    """
    Sum all account balances, flipping the sign for debt accounts so that
    debts reduce the total and cash increases it.
    """
    tx_sum =  _tx_sum_by_account()

    bal_expr = _account_running_balance_expr(Account, tx_sum)
    signed = case(
        (Account.is_debt.is_(True), -bal_expr),
        else_=bal_expr,
    )

    q = (
        select(func.coalesce(func.sum(signed), 0.0))
        .select_from(Account)
        .join(tx_sum, tx_sum.c.account_id == Account.id, isouter=True)
        .where(Account.is_archived.is_(False))
    )
    return (await session.execute(q)).scalar_one()


async def accounts_cash_total(session):
    tx_sum = _tx_sum_by_account()
    bal_expr = _account_running_balance_expr(Account, tx_sum)
    q = (
        select(func.coalesce(func.sum(bal_expr), 0.0))
        .select_from(Account)
        .join(tx_sum, tx_sum.c.account_id == Account.id, isouter=True)
        .where(and_(Account.is_archived.is_(False), Account.is_debt.is_(False)))
    )
    return (await session.execute(q)).scalar_one()


async def accounts_debt_total(session):
    """Sum of debt balances as positive numbers (what’s owed)."""
    tx_sum = _tx_sum_by_account()
    bal_expr = _account_running_balance_expr(Account, tx_sum)
    q = (
        select(func.coalesce(func.sum(func.greatest(bal_expr, 0)), 0.0))
        .select_from(Account)
        .join(tx_sum, tx_sum.c.account_id == Account.id, isouter=True)
        .where(and_(Account.is_archived.is_(False), Account.is_debt.is_(True)))
    )
    return (await session.execute(q)).scalar_one()

# --- Assets ------------------------------------------------------------------


async def assets_total(session):
    # Sum the tracked estimate value for active assets.
    q = select(
        func.coalesce(func.sum(Asset.estimate_value), 0.0)
    ).where(Asset.is_archived.is_(False))
    return (await session.execute(q)).scalar_one()

# --- Spending this month -----------------------------------------------------


async def spent_this_month(session):
    """
    Outflows from NON-debt accounts in the current month.
    Assumes negative Transaction.amount = money leaving the account.
    If you encode direction differently, adjust the predicate.
    """
    today = datetime.now(timezone.utc)
    first_of_month = today.date().replace(day=1)
    if first_of_month.month == 12:
        first_of_next_month = date(first_of_month.year + 1, 1, 1)
    else:
        first_of_next_month = date(
            first_of_month.year, first_of_month.month + 1, 1)

    first_of_month_dt = datetime.combine(
        first_of_month, datetime.min.time(), tzinfo=today.tzinfo
    )
    first_of_next_month_dt = datetime.combine(
        first_of_next_month, datetime.min.time(), tzinfo=today.tzinfo
    )
    q = (
        # flip to make positive “spent”
        select(func.coalesce(func.sum(-Transaction.amount), 0.0))
        .select_from(Transaction)
        .join(Account, Account.id == Transaction.account_id)
        .where(
            and_(
                Account.is_debt.is_(False),
                Transaction.ts >= first_of_month_dt,
                Transaction.ts < first_of_next_month_dt,
                Transaction.amount < 0,
            )
        )
    )
    return (await session.execute(q)).scalar_one()

# --- Top-level cards ---------------------------------------------------------


async def dashboard_totals(session):
    cash = await accounts_cash_total(session)
    debt = await accounts_debt_total(session)       # positive
    assets = await assets_total(session)
    net_accounts = await accounts_net_total(session)
    spent = await spent_this_month(session)

    # Net worth = net value of all accounts (cash - debt) + assets
    net_worth = net_accounts + assets

    return {
        "net_worth": float(net_worth),
        "cash": float(cash),
        "debts": float(debt),
        "assets": float(assets),
        "spent_this_month": float(spent),
    }
