from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote_plus
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Account, StatementDocument
from ..services.dropbox import DropboxSettings, DropboxError, DropboxClient, verify_webhook_signature
from ..services.statement_ingest import StatementIngestError, StatementIngestor

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/documents", response_class=HTMLResponse)
async def documents_list(request: Request, session: AsyncSession = Depends(get_session)):
    docs = (
        await session.execute(
            select(StatementDocument).order_by(
                StatementDocument.uploaded_at.desc())
        )
    ).scalars().all()
    account_rows = (
        await session.execute(
            select(Account.id, Account.name,
                   Account.import_status).order_by(Account.name)
        )
    ).all()
    account_map = {row[0]: row[1] for row in account_rows}

    pending = [doc for doc in docs if doc.status in {"pending", "error"}]
    history = [doc for doc in docs if doc.status not in {"pending", "error"}]
    return templates.TemplateResponse(
        "documents_list.html",
        {
            "request": request,
            "pending": pending,
            "history": history,
            "accounts": account_rows,
            "account_map": account_map,
            "error": request.query_params.get("error"),
        },
    )


@router.post("/documents/upload")
async def documents_upload(
    request: Request,
    account_id: str = Form(...),
    file: UploadFile = File(...),
    auto_approve: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    try:
        account = await session.get(Account, UUID(account_id))
    except ValueError as exc:  # pragma: no cover - invalid UUID path
        raise HTTPException(
            status_code=400, detail="Invalid account id") from exc
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    content = await file.read()
    ingestor = StatementIngestor(session)
    try:
        doc = await ingestor.ingest(
            account,
            filename=file.filename or "statement.csv",
            content=content,
            source="upload",
            source_path=file.filename or "upload",
            auto_approve=auto_approve is not None,
        )
    except StatementIngestError as exc:
        await session.rollback()
        return RedirectResponse(
            url=f"/documents?error={quote_plus(str(exc))}", status_code=303
        )
    await session.commit()
    return RedirectResponse(url=f"/documents/{doc.id}", status_code=303)


@router.get("/documents/{doc_id}", response_class=HTMLResponse)
async def documents_detail(doc_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    try:
        doc_uuid = UUID(doc_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail="Document not found") from exc
    doc = await session.get(StatementDocument, doc_uuid)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    account = await session.get(Account, doc.account_id)
    return templates.TemplateResponse(
        "documents_detail.html",
        {
            "request": request,
            "doc": doc,
            "account": account,
            "rows": doc.parsed_transactions or [],
        },
    )


@router.post("/documents/{doc_id}/approve")
async def documents_approve(doc_id: str, session: AsyncSession = Depends(get_session)):
    doc = await session.get(StatementDocument, UUID(doc_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.status == "approved":
        return RedirectResponse(url=f"/documents/{doc_id}", status_code=303)
    if doc.status == "rejected":
        raise HTTPException(
            status_code=400, detail="Document already rejected")
    ingestor = StatementIngestor(session)
    await ingestor.apply_document(doc)
    await session.commit()
    return RedirectResponse(url=f"/documents/{doc_id}", status_code=303)


@router.post("/documents/{doc_id}/reject")
async def documents_reject(doc_id: str, session: AsyncSession = Depends(get_session)):
    doc = await session.get(StatementDocument, UUID(doc_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.status == "approved":
        raise HTTPException(
            status_code=400, detail="Document already approved")
    doc.status = "rejected"
    doc.mark_processed()
    account = await session.get(Account, doc.account_id)
    if account:
        account.import_status = "idle"
    await session.commit()
    return RedirectResponse(url="/documents", status_code=303)


@router.get("/documents/dropbox/webhook", response_class=PlainTextResponse)
async def dropbox_webhook_verify(challenge: str):
    return PlainTextResponse(challenge)


@router.post("/documents/dropbox/webhook")
async def dropbox_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    settings = DropboxSettings.from_env()
    if not settings:
        # Dropbox not configured for this environment
        return Response(status_code=202)
    body = await request.body()
    signature = request.headers.get("X-Dropbox-Signature")
    if not verify_webhook_signature(body, signature, app_secret=settings.app_secret):
        raise HTTPException(status_code=400, detail="Invalid signature")

    payload = await request.json()
    if not payload.get("list_folder"):
        return Response(status_code=202)

    await _sync_dropbox_documents(session, settings)
    await session.commit()
    return Response(status_code=202)


async def _sync_dropbox_documents(session: AsyncSession, settings: DropboxSettings) -> None:
    accounts = (
        await session.execute(
            select(Account).where(Account.dropbox_folder.is_not(None))
        )
    ).scalars().all()
    if not accounts:
        return
    client = DropboxClient(settings)
    try:
        for account in accounts:
            folder = account.dropbox_folder
            if not folder:
                continue
            try:
                entries, cursor = await client.list_folder(folder, cursor=account.dropbox_cursor)
            except DropboxError:
                account.import_status = "error"
                account.last_webhook_at = datetime.now(timezone.utc)
                continue
            new_docs = await _ingest_dropbox_entries(session, client, account, entries)
            if cursor:
                account.dropbox_cursor = cursor
            account.last_webhook_at = datetime.now(timezone.utc)
            if new_docs:
                account.import_status = "pending"
            elif account.import_status == "pending":
                # no new docs but still pending -> keep
                pass
        await session.flush()
    finally:
        await client.close()


async def _ingest_dropbox_entries(
    session: AsyncSession,
    client: DropboxClient,
    account: Account,
    entries,
) -> list[StatementDocument]:
    documents: list[StatementDocument] = []
    ingestor = StatementIngestor(session)
    for entry in entries:
        if entry.get(".tag") != "file":
            continue
        if not entry.get("name", "").lower().endswith((".csv", ".txt")):
            continue
        rev = entry.get("rev")
        already = await session.execute(
            select(func.count()).select_from(StatementDocument).where(
                (StatementDocument.dropbox_rev == rev)
                | (StatementDocument.source_path == entry.get("path_lower"))
            )
        )
        if already.scalar_one():
            continue
        try:
            content, _ = await client.download_file(entry["path_lower"])
            doc = await ingestor.ingest(
                account,
                filename=entry.get("name", "statement.csv"),
                content=content,
                source="dropbox",
                source_path=entry.get(
                    "path_lower", entry.get("name", "dropbox")),
                dropbox_rev=rev,
            )
        except StatementIngestError:
            account.import_status = "error"
            continue
        documents.append(doc)
    return documents
