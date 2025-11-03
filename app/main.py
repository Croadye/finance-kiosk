from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from .routers import health, dashboard, transactions
from .routers import budget, recurring, accounts, assets, transfers

app = FastAPI(title="Money Kiosk")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(health.router, tags=["health"])
app.include_router(dashboard.router, tags=["ui"])
app.include_router(transactions.router, tags=["ui"])
app.include_router(budget.router, tags=["ui"])  
app.include_router(recurring.router, tags=["ui"])
app.include_router(accounts.router, tags=["ui"])
app.include_router(assets.router, tags=["ui"])
app.include_router(transfers.router, tags=["ui"])
