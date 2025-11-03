# python -m scripts.migrate_add_transfer_group
import asyncio
from sqlalchemy import text
from app.db import engine

SQL = """
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='transactions' AND column_name='transfer_group_id'
  ) THEN
    ALTER TABLE transactions ADD COLUMN transfer_group_id UUID NULL;
    CREATE INDEX IF NOT EXISTS ix_transactions_transfer_group_id
      ON transactions(transfer_group_id);
  END IF;
END$$;
"""


async def main():
    async with engine.begin() as conn:
        await conn.execute(text(SQL))
    print("transfer_group_id added (or already present).")

if __name__ == "__main__":
    asyncio.run(main())
