# python -m scripts.migrate_assets_meta
import asyncio
from sqlalchemy import text
from app.db import engine

SQL = """
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='assets' AND column_name='meta'
  ) THEN
    ALTER TABLE assets ADD COLUMN meta JSONB NULL;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='assets' AND column_name='is_archived'
  ) THEN
    ALTER TABLE assets ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT FALSE;
  END IF;
END$$;
"""


async def main():
  async with engine.begin() as conn:
    await conn.execute(text(SQL))
  print("Assets: meta/is_archived ensured.")

if __name__ == "__main__":
  asyncio.run(main())
