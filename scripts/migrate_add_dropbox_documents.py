"""Add Dropbox fields to accounts and create statement_documents table."""
# python -m scripts.migrate_add_dropbox_documents
import asyncio

from sqlalchemy import text

from app.db import engine

SQL = """
ALTER TABLE accounts
    ADD COLUMN IF NOT EXISTS dropbox_folder TEXT,
    ADD COLUMN IF NOT EXISTS dropbox_cursor TEXT,
    ADD COLUMN IF NOT EXISTS import_status VARCHAR(20) NOT NULL DEFAULT 'idle',
    ADD COLUMN IF NOT EXISTS last_imported_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_webhook_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS statement_documents (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    source VARCHAR(40) NOT NULL,
    source_path TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,
    approved_at TIMESTAMPTZ,
    total_transactions INTEGER NOT NULL DEFAULT 0,
    duplicates INTEGER NOT NULL DEFAULT 0,
    dropbox_rev VARCHAR(120),
    meta JSONB,
    parsed_transactions JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS ix_statement_documents_account_id
    ON statement_documents(account_id);
CREATE INDEX IF NOT EXISTS ix_statement_documents_status
    ON statement_documents(status);
"""


async def main() -> None:
    async with engine.begin() as conn:
        await conn.execute(text(SQL))
    print("Dropbox document schema ensured.")


if __name__ == "__main__":
    asyncio.run(main())
