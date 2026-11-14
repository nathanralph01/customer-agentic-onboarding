"""Shared GridFS upload and download operations."""

from datetime import datetime, timezone
from mimetypes import guess_type
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException, UploadFile, status
from fastapi.responses import Response

from .mcp_database import MCPBucket, MCPDatabase as Database, NoFile, StorageError

MAX_DOCUMENT_SIZE = 10 * 1024 * 1024
MAX_DOCUMENTS_PER_CONVERSATION = 10
ALLOWED_DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".txt",
    ".csv",
    ".png",
    ".jpg",
    ".jpeg",
}


def document_response(document: dict):
    return dict(
        id=str(document["_id"]),
        source=document.get("source", "uploaded"),
        filename=document["filename"],
        contentType=document["content_type"],
        sizeBytes=document["size_bytes"],
        createdAt=document["created_at"].isoformat(),
    )


async def store_upload(database: Database, customer_id, onboarding_id, file: UploadFile, conversation_id=None):
    count = await database["documents"].count_documents(
        {"customer_id": customer_id, "onboarding_id": onboarding_id, "source": "uploaded"}
    )
    if count >= MAX_DOCUMENTS_PER_CONVERSATION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A conversation can have at most 10 uploads.",
        )

    filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    extension = Path(filename).suffix.lower()
    if not filename or len(filename) > 255 or extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Choose a PDF, DOCX, TXT, CSV, PNG or JPG file.",
        )
    content = await file.read(MAX_DOCUMENT_SIZE + 1)
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The selected document is empty.",
        )
    if len(content) > MAX_DOCUMENT_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Documents must be 10 MB or smaller.",
        )

    now = datetime.now(timezone.utc)
    content_type = guess_type(filename)[0] or "application/octet-stream"
    bucket = MCPBucket(database)
    storage_id = await bucket.upload_from_stream(
        filename,
        content,
        metadata={
            "customer_id": customer_id,
            "onboarding_id": onboarding_id,
            **({"conversation_id": conversation_id} if conversation_id else {}),
        },
    )
    document = {
        "created_at": now,
        "updated_at": now,
        "customer_id": customer_id,
        "onboarding_id": onboarding_id,
        **({"conversation_id": conversation_id} if conversation_id else {}),
        "filename": filename,
        "content_type": content_type,
        "storage_id": storage_id,
        "size_bytes": len(content),
        "processing_status": "ready",
        "source": "uploaded",
    }
    try:
        result = await database["documents"].insert_one(document)
    except StorageError:
        await bucket.delete(storage_id, missing_ok=True)
        raise
    document["_id"] = result.inserted_id
    return document_response(document)


async def stream_document(database: Database, document):
    try:
        content = await MCPBucket(database).read(document["storage_id"])
    except NoFile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document content not found.",
        ) from None

    return Response(
        content,
        media_type=document["content_type"],
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(document['filename'])}"
        },
    )
