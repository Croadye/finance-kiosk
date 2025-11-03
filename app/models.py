import uuid
from datetime import datetime, date
from sqlalchemy import ForeignKey, Text, Boolean, Numeric, Integer, String, Date, func
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

ACCOUNT_TYPES = ('checking', 'savings', 'cash', 'credit')


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    type: Mapped[str] = mapped_column(
        String(20), nullable=False)  # checking/savings/cash/credit
    opening_balance: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0)
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now())

    transactions = relationship("Transaction", back_populates="account")


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    group: Mapped[str] = mapped_column(String(80), nullable=True)
    is_hidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False)


class Budget(Base):
    __tablename__ = "budgets"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), nullable=False)
    month: Mapped[date] = mapped_column(
        Date, nullable=False)  # first day of month for key
    planned: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0)
    rollover_mode: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1)  # 0 none, 1 carry+, 2 carry±
    # 0 none, 1 cap, 2 contrib, 3 date goal
    target_type: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0)
    target_value: Mapped[float] = mapped_column(Numeric(12, 2), nullable=True)
    target_date: Mapped[date] = mapped_column(Date, nullable=True)


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ts: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True)
    payee: Mapped[str | None] = mapped_column(Text, nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False)  # +inflow, -outflow
    cleared: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True)

    account = relationship("Account", back_populates="transactions")
    splits = relationship(
        "TxSplit", back_populates="transaction", cascade="all, delete-orphan")


class TxSplit(Base):
    __tablename__ = "tx_splits"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False, index=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True, index=True)
    amount: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False)  # portion of txn

    transaction = relationship("Transaction", back_populates="splits")


class Bill(Base):
    __tablename__ = "bills"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0)
    cadence: Mapped[str] = mapped_column(
        String(40), nullable=False, default="monthly")
    next_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    autopost: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True)


class Rule(Base):
    __tablename__ = "rules"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    contains_text: Mapped[str | None] = mapped_column(
        String(120), nullable=True)
    payee_regex: Mapped[str | None] = mapped_column(String(240), nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True)
    amount_min: Mapped[float | None] = mapped_column(
        Numeric(12, 2), nullable=True)
    amount_max: Mapped[float | None] = mapped_column(
        Numeric(12, 2), nullable=True)
    day_of_week: Mapped[int | None] = mapped_column(
        Integer, nullable=True)  # 0-6
    account_match: Mapped[str | None] = mapped_column(
        String(80), nullable=True)


class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False, index=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str | None] = mapped_column(String(80), nullable=True)


class Setting(Base):
    __tablename__ = "settings"
    k: Mapped[str] = mapped_column(String(80), primary_key=True)
    v_json = mapped_column(JSONB, nullable=False, default=dict)
