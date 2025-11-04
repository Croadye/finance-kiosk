import asyncio
from decimal import Decimal
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Account, Category


async def main():
    async with SessionLocal() as session:
        # Accounts
        have_accounts = (await session.execute(select(Account))).scalars().first()
        if not have_accounts:
            session.add_all([
                Account(name="Checking", type="checking",
                        opening_balance=Decimal('1500.00'), is_debt=False),
                Account(name="Savings", type="savings",
                        opening_balance=Decimal('5000.00'), is_debt=False),
                Account(name="Cash", type="cash",
                        opening_balance=Decimal('120.00'), is_debt=False),
                Account(name="Credit Card", type="credit",
                        opening_balance=Decimal('0.00'), is_debt=True),
            ])
            print("Seeded accounts.")
        # Categories
        have_cats = (await session.execute(select(Category))).scalars().first()
        if not have_cats:
            session.add_all([
                Category(name="Groceries", group="Essentials"),
                Category(name="Utilities", group="Essentials"),
                Category(name="Rent/Mortgage", group="Essentials"),
                Category(name="Dining Out", group="Discretionary"),
                Category(name="Entertainment", group="Discretionary"),
                Category(name="Emergency Fund", group="Savings"),
                Category(name="Credit Card Payment", group="Debt"),
            ])
            print("Seeded categories.")
        await session.commit()
        print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
