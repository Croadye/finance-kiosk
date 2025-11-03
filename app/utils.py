from __future__ import annotations
from datetime import date
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from .models import Setting

DEFAULT_ACCOUNT_TYPES: List[Dict[str, Any]] = [
    {"name": "checking",      "is_debt": False},
    {"name": "savings",       "is_debt": False},
    {"name": "cash",          "is_debt": False},
    {"name": "credit",        "is_debt": True},
    {"name": "mortgage",      "is_debt": True},
    {"name": "auto_loan",     "is_debt": True},
    {"name": "home_loan",     "is_debt": True},
    {"name": "personal_loan", "is_debt": True},
    {"name": "investment",    "is_debt": False},
]


async def get_account_types(session: AsyncSession) -> List[Dict[str, Any]]:
    row = await session.get(Setting, "account_types")
    v = getattr(row, "v_json", None)
    if not v:
        return DEFAULT_ACCOUNT_TYPES
    # normalize: keep only expected keys
    out = []
    for t in v:
        name = (t.get("name") or "").strip()
        if not name:
            continue
        out.append({"name": name, "is_debt": bool(t.get("is_debt"))})
    return out


def month_start(d: date) -> date:
    return d.replace(day=1)
