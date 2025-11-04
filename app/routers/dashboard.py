from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_session
from fastapi.templating import Jinja2Templates
from app.services.metrics import dashboard_totals

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

def currency(val):
    try:
        return f"{float(val):,.2f}"
    except Exception:
        return val
    
templates.env.filters['currency'] = currency


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: AsyncSession = Depends(get_session)):
    totals = await dashboard_totals(session)
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "totals": totals,
    })
