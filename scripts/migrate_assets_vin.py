# python -m scripts.migrate_assets_vin
import asyncio
from sqlalchemy import text

from app.db import engine

SQL = """
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='assets' AND column_name='vin'
  ) THEN
    ALTER TABLE assets ADD COLUMN vin VARCHAR(32) NULL;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='assets' AND column_name='estimate_source'
  ) THEN
    ALTER TABLE assets ADD COLUMN estimate_source VARCHAR(32) NULL;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='assets' AND column_name='estimate_at'
  ) THEN
    ALTER TABLE assets ADD COLUMN estimate_at TIMESTAMPTZ NULL;
  END IF;
END$$;
"""


async def main() -> None:
    async with engine.begin() as conn:
        await conn.execute(text(SQL))
    print("Assets: vin/estimate_source/estimate_at ensured.")


if __name__ == "__main__":
    asyncio.run(main())
