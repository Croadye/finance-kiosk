from app import models  # <-- IMPORTANT: registers all tables on Base.metadata
from app.db import engine, Base
import os
import sys
import asyncio
# ensure project root is on path if you run this as a file
sys.path.append(os.path.dirname(os.path.dirname(__file__)))


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database tables created.")

if __name__ == "__main__":
    asyncio.run(main())
