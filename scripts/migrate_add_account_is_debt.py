"""Add is_debt flag to accounts."""
# python -m scripts.migrate_add_account_is_debt
import asyncio

from sqlalchemy import text

from app.db import engine

ALTER_SQL = """
ALTER TABLE accounts
    ADD COLUMN IF NOT EXISTS is_debt BOOLEAN NOT NULL DEFAULT FALSE;
"""

BACKFILL_SQL = """
UPDATE accounts
SET is_debt = TRUE
WHERE type IN (
    'credit',
    'mortgage',
    'auto_loan',
    'home_loan',
    'personal_loan',
    'loan'
);
"""


async def main() -> None:
    async with engine.begin() as conn:
        await conn.execute(text(ALTER_SQL))
        await conn.execute(text(BACKFILL_SQL))
    print("accounts.is_debt column ensured and backfilled.")


if __name__ == "__main__":
    asyncio.run(main())
