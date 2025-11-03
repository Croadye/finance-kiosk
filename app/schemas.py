from pydantic import BaseModel, UUID4
from typing import Optional, Literal
from datetime import datetime


class TransactionCreate(BaseModel):
    account_id: UUID4
    category_id: Optional[UUID4] = None
    payee: Optional[str] = None
    memo: Optional[str] = None
    amount: float  # positive number from UI
    # Part 1: expense/income only
    kind: Literal["expense", "income"] = "expense"


class TransactionOut(BaseModel):
    id: UUID4
    ts: datetime
    account_id: UUID4
    payee: Optional[str]
    memo: Optional[str]
    amount: float
