"""CLI tool to ingest statements from disk for backfills."""
# python -m scripts.ingest_statements --account "Checking" path/to/file.csv

import argparse
import asyncio
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Account
from app.services.statement_ingest import StatementIngestError, StatementIngestor


async def _resolve_account(session, ref: str) -> Account:
    try:
        account = await session.get(Account, UUID(ref))
        if account:
            return account
    except ValueError:
        pass
    row = (
        await session.execute(
            select(Account).where(Account.name.ilike(ref))
        )
    ).scalar_one_or_none()
    if not row:
        raise SystemExit(f"Account '{ref}' not found")
    return row


async def run(account_ref: str, file_path: Path, auto_approve: bool) -> None:
    if not file_path.exists():
        raise SystemExit(f"File {file_path} does not exist")
    content = file_path.read_bytes()
    async with SessionLocal() as session:
        account = await _resolve_account(session, account_ref)
        ingestor = StatementIngestor(session)
        try:
            doc = await ingestor.ingest(
                account,
                filename=file_path.name,
                content=content,
                source="cli",
                source_path=str(file_path),
                auto_approve=auto_approve,
            )
        except StatementIngestError as exc:
            raise SystemExit(f"Failed to ingest: {exc}") from exc
        await session.commit()
    print(f"Created document {doc.id} for {account.name}")
    if auto_approve:
        print("Transactions imported.")
    else:
        print("Review pending at /documents")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest a statement file into Finance Kiosk")
    parser.add_argument("file", type=Path, help="Path to the statement file")
    parser.add_argument("--account", required=True, help="Account id or name")
    parser.add_argument("--auto-approve", action="store_true",
                        help="Automatically post transactions")
    args = parser.parse_args()
    asyncio.run(run(args.account, args.file, args.auto_approve))


if __name__ == "__main__":
    main()
