"""Statement ingestion service to parse Dropbox/manual statements into transactions."""
from __future__ import annotations
import csv
import io
import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    Account,
    Attachment,
    Bill,
    Category,
    Rule,
    StatementDocument,
    Transaction,
    TxSplit,
)

DATE_FORMATS = [
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%Y%m%d",
]


@dataclass(slots=True)
class ParsedRow:
    tx_date: date
    payee: str | None
    memo: str | None
    amount: Decimal
    duplicate: bool = False
    duplicate_tx_id: str | None = None
    category_id: str | None = None
    category_name: str | None = None
    rule_id: str | None = None
    matched_bill_id: str | None = None
    matched_bill_name: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "date": self.tx_date.isoformat(),
            "payee": self.payee,
            "memo": self.memo,
            "amount": str(self.amount),
            "duplicate": self.duplicate,
            "duplicate_tx_id": self.duplicate_tx_id,
            "category_id": self.category_id,
            "category_name": self.category_name,
            "rule_id": self.rule_id,
            "matched_bill_id": self.matched_bill_id,
            "matched_bill_name": self.matched_bill_name,
        }


class StatementIngestError(Exception):
    pass


class StatementIngestor:
    """Coordinate parsing, duplicate detection, and transaction creation."""

    def __init__(self, session: AsyncSession, storage_dir: str | os.PathLike[str] = "data/statements"):
        self.session = session
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    async def ingest(
        self,
        account: Account,
        *,
        filename: str,
        content: bytes,
        source: str,
        source_path: str,
        dropbox_rev: str | None = None,
        auto_approve: bool = False,
    ) -> StatementDocument:
        parsed_rows = self._parse_content(content, filename)
        if not parsed_rows:
            raise StatementIngestError("No transactions found in statement")

        await self._annotate_duplicates(account, parsed_rows)
        await self._apply_rules(account, parsed_rows)
        await self._match_bills(account, parsed_rows)

        stored_path = self._store_raw_statement(account, filename, content)
        doc = StatementDocument(
            account_id=account.id,
            source=source,
            source_path=source_path,
            dropbox_rev=dropbox_rev,
            total_transactions=len(parsed_rows),
            duplicates=sum(1 for row in parsed_rows if row.duplicate),
            parsed_transactions=[row.as_dict() for row in parsed_rows],
            meta={
                "filename": filename,
                "stored_path": stored_path,
                "mime": self._guess_mime(filename),
            },
        )
        self.session.add(doc)
        account.import_status = "pending"
        account.last_imported_at = datetime.now(timezone.utc)
        await self.session.flush()

        if auto_approve:
            await self.apply_document(doc)
        return doc

    async def apply_document(self, doc: StatementDocument) -> None:
        if not doc.parsed_transactions:
            doc.status = "error"
            doc.meta = {**(doc.meta or {}), "error": "No parsed rows"}
            await self.session.flush()
            return

        account = await self.session.get(Account, doc.account_id)
        if not account:
            raise StatementIngestError("Associated account missing")

        created = 0
        for payload in doc.parsed_transactions:
            if payload.get("duplicate"):
                continue
            tx_date = datetime.fromisoformat(payload["date"]).date()
            ts = datetime.combine(
                tx_date, datetime.min.time(), tzinfo=timezone.utc)
            amount = Decimal(payload["amount"])
            tx = Transaction(
                account_id=doc.account_id,
                ts=ts,
                amount=amount,
                payee=payload.get("payee"),
                memo=payload.get("memo"),
            )
            self.session.add(tx)
            await self.session.flush()

            category_uuid = uuid_from_str(payload.get("category_id"))
            if category_uuid:
                self.session.add(
                    TxSplit(
                        transaction_id=tx.id,
                        category_id=category_uuid,
                        amount=amount,
                    )
                )
            stored_path = (doc.meta or {}).get("stored_path")
            if stored_path:
                self.session.add(
                    Attachment(
                        transaction_id=tx.id,
                        path=stored_path,
                        mime=(doc.meta or {}).get("mime"),
                    )
                )
            created += 1

        doc.status = "approved"
        doc.approved_at = datetime.now(timezone.utc)
        doc.mark_processed()
        doc.meta = {**(doc.meta or {}), "created_transactions": created}
        account.import_status = "ok"
        account.last_imported_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def _annotate_duplicates(self, account: Account, rows: list[ParsedRow]) -> None:
        dates = [row.tx_date for row in rows]
        amounts = list({row.amount for row in rows})
        if not dates:
            return
        span_start = min(dates) - timedelta(days=3)
        span_end = max(dates) + timedelta(days=3)
        existing = (
            await self.session.execute(
                select(Transaction.id, Transaction.ts,
                       Transaction.amount, Transaction.payee)
                .where(
                    and_(
                        Transaction.account_id == account.id,
                        Transaction.ts >= datetime.combine(
                            span_start, datetime.min.time(), tzinfo=timezone.utc),
                        Transaction.ts <= datetime.combine(
                            span_end, datetime.max.time(), tzinfo=timezone.utc),
                        Transaction.amount.in_(amounts),
                    )
                )
            )
        ).all()
        for row in rows:
            for tx_id, ts, amt, payee in existing:
                if Decimal(amt) != row.amount:
                    continue
                if ts.date() != row.tx_date:
                    continue
                if (payee or "").strip().lower() != (row.payee or "").strip().lower():
                    continue
                row.duplicate = True
                row.duplicate_tx_id = str(tx_id)
                break

    async def _apply_rules(self, account: Account, rows: list[ParsedRow]) -> None:
        rules = (
            await self.session.execute(
                select(Rule).order_by(Rule.priority.asc())
            )
        ).scalars().all()
        if not rules:
            return
        categories = await self._category_lookup()
        for row in rows:
            if row.duplicate:
                continue
            for rule in rules:
                if not self._matches_rule(row, account, rule):
                    continue
                row.rule_id = str(rule.id)
                if rule.category_id:
                    row.category_id = str(rule.category_id)
                    row.category_name = categories.get(rule.category_id)
                break

    async def _match_bills(self, account: Account, rows: list[ParsedRow]) -> None:
        bills = (
            await self.session.execute(
                select(Bill).where(
                    (Bill.account_id.is_(None)) | (
                        Bill.account_id == account.id)
                )
            )
        ).scalars().all()
        if not bills:
            return
        for row in rows:
            if row.duplicate:
                continue
            for bill in bills:
                if bill.amount is None:
                    continue
                if abs(Decimal(bill.amount) - row.amount) > Decimal("1.00"):
                    continue
                if bill.next_due and abs((bill.next_due - row.tx_date).days) > 10:
                    continue
                row.matched_bill_id = str(bill.id)
                row.matched_bill_name = bill.name
                if not row.memo:
                    row.memo = f"Matched bill: {bill.name}"
                break

    async def _category_lookup(self) -> dict[uuid.UUID, str]:
        rows = (
            await self.session.execute(
                select(Category.id, Category.name)
            )
        ).all()
        return {row[0]: row[1] for row in rows}

    def _parse_content(self, content: bytes, filename: str) -> list[ParsedRow]:
        text = content.decode("utf-8-sig").strip()
        if not text:
            return []
        first_line = text.splitlines()[0]
        if filename.lower().endswith(".csv") or "," in first_line:
            return self._parse_csv(text)
        return self._parse_simple(text)

    def _parse_csv(self, text: str) -> list[ParsedRow]:
        reader = csv.DictReader(io.StringIO(text))
        rows: list[ParsedRow] = []
        for raw in reader:
            date_value = self._parse_date(
                raw.get("date") or raw.get("Date") or raw.get("DATE"))
            if not date_value:
                continue
            amount_raw = raw.get("amount") or raw.get(
                "Amount") or raw.get("AMOUNT")
            if amount_raw is None:
                continue
            amount = self._parse_amount(str(amount_raw))
            rows.append(
                ParsedRow(
                    tx_date=date_value,
                    payee=(raw.get("payee") or raw.get(
                        "description") or raw.get("Payee")),
                    memo=raw.get("memo") or raw.get("Memo"),
                    amount=amount,
                )
            )
        return rows

    def _parse_simple(self, text: str) -> list[ParsedRow]:
        rows: list[ParsedRow] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3:
                continue
            date_value = self._parse_date(parts[0])
            if not date_value:
                continue
            amount = self._parse_amount(parts[2])
            payee = parts[1]
            memo = parts[3] if len(parts) > 3 else None
            rows.append(ParsedRow(tx_date=date_value,
                        payee=payee, memo=memo, amount=amount))
        return rows

    def _parse_date(self, raw: str | None) -> date | None:
        if not raw:
            return None
        raw = raw.strip()
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
        return None

    def _store_raw_statement(self, account: Account, filename: str, content: bytes) -> str:
        safe_name = filename.replace("/", "_").replace("..", "_")
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        path = self.storage_dir / f"{account.id}_{ts}_{safe_name}"
        path.write_bytes(content)
        return str(path)

    def _guess_mime(self, filename: str) -> str:
        if filename.lower().endswith(".csv"):
            return "text/csv"
        return "application/octet-stream"

    def _parse_amount(self, raw: str) -> Decimal:
        cleaned = raw.strip().replace(",", "")
        sign = Decimal("1")
        if cleaned.startswith("(") and cleaned.endswith(")"):
            cleaned = cleaned[1:-1]
            sign = Decimal("-1")
        if cleaned.startswith("-"):
            return Decimal(cleaned)
        return Decimal(cleaned) * sign

    def _matches_rule(self, row: ParsedRow, account: Account, rule: Rule) -> bool:
        if rule.account_match and rule.account_match.lower() != account.name.lower():
            return False
        if rule.contains_text:
            haystack = (row.payee or "") + " " + (row.memo or "")
            if rule.contains_text.lower() not in haystack.lower():
                return False
        if rule.amount_min and row.amount < Decimal(rule.amount_min):
            return False
        if rule.amount_max and row.amount > Decimal(rule.amount_max):
            return False
        if rule.day_of_week is not None and row.tx_date.weekday() != rule.day_of_week:
            return False
        if rule.payee_regex:
            import re

            if not re.search(rule.payee_regex, row.payee or "", re.IGNORECASE):
                return False
        return True


def uuid_from_str(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    return uuid.UUID(value)
