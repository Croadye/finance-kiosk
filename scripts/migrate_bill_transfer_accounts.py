# python -m scripts.migrate_bill_transfer_accounts
import asyncio

from sqlalchemy import text

from app.db import engine

SQL = """
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='bills' AND column_name='from_account_id'
  ) THEN
    ALTER TABLE bills ADD COLUMN from_account_id UUID NULL REFERENCES accounts(id);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='bills' AND column_name='to_account_id'
  ) THEN
    ALTER TABLE bills ADD COLUMN to_account_id UUID NULL REFERENCES accounts(id);
  END IF;

  UPDATE bills
  SET from_account_id = account_id
  WHERE from_account_id IS NULL AND account_id IS NOT NULL AND amount < 0;

  UPDATE bills
  SET to_account_id = account_id
  WHERE to_account_id IS NULL AND account_id IS NOT NULL AND amount >= 0;
END$$;
"""


async def main():
    async with engine.begin() as conn:
        await conn.execute(text(SQL))
    print("Bills: transfer account columns ensured and backfilled.")


if __name__ == "__main__":
    asyncio.run(main())
