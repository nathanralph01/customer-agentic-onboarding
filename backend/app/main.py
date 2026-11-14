"""Customer 360 demo API with Atlas-backed onboarding conversations."""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from mimetypes import guess_type
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import quote
from uuid import UUID

from bson import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.mcp_database import (
    MCPDatabase as Database,
    MCPCollection as Collection,
    MCPBucket,
    NoFile,
    DuplicateKeyError,
    StorageError,
    tool,
)
from app.mongodb_mcp import mongodb_mcp_session

load_dotenv(Path(__file__).resolve().parents[2] / "database" / ".env")

DEMO_CUSTOMER_NAME = "Northstar Test Goods Ltd."
DEMO_USER_EMAIL = "customer.demo@customer360.example"
QUESTION_COUNT = 5
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


class ConversationPayload(BaseModel):
    id: UUID
    startedAt: datetime
    answers: list[str] = Field(default_factory=list, max_length=QUESTION_COUNT)


class AnswerPayload(BaseModel):
    sequence: int = Field(ge=0, lt=QUESTION_COUNT)
    content: str = Field(min_length=1, max_length=4000)


class ConversationResponse(BaseModel):
    id: str
    startedAt: str
    answers: list[str]


class DocumentResponse(BaseModel):
    id: str
    filename: str
    contentType: str
    sizeBytes: int
    createdAt: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.database = None
    database_name = os.getenv("MONGODB_DATABASE")
    project_id = os.getenv("MDB_MCP_PROJECT_ID")
    cluster_name = os.getenv("MDB_MCP_CLUSTER_NAME")
    if not database_name or not project_id or not cluster_name:
        raise RuntimeError("Set MONGODB_DATABASE, MDB_MCP_PROJECT_ID and MDB_MCP_CLUSTER_NAME for Atlas Managed MCP.")
    async with mongodb_mcp_session() as session:
        connected = await tool(session, "remote-atlas-connect", {"projectId": project_id, "clusterName": cluster_name})
        connection_id = connected.get("connectionId")
        if not connection_id:
            raise RuntimeError("Atlas Managed MCP returned no cluster connection ID.")
        app.state.database = Database(session, connection_id, database_name)
        try:
            yield
        finally:
            app.state.database = None


app = FastAPI(title="Customer 360 API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")).split(",") if origin.strip()],
    allow_methods=["DELETE", "GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(StorageError)
async def storage_error_handler(request: Request, error: StorageError):
    return JSONResponse(status_code=503, content={"detail": "Atlas MCP storage operation failed. Retry the request."})


@app.middleware("http")
async def serialize_storage_requests(request: Request, call_next):
    database = getattr(app.state, "database", None)
    if database is None or request.url.path == "/api/v1/login":
        return await call_next(request)
    async with database.write_lock:
        return await call_next(request)


def get_database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Atlas Managed MCP is not connected. Check the server configuration.",
        )
    return database


async def _upsert_by_key(collection: Collection, key: dict, insert_fields: dict) -> dict:
    return await collection.upsert(key, insert_fields)


async def ensure_demo_profile(database: Database) -> tuple[ObjectId, ObjectId]:
    now = datetime.now(timezone.utc)
    customer = await _upsert_by_key(
        database["customers"],
        {"legal_name": DEMO_CUSTOMER_NAME},
        {
            "created_at": now,
            "updated_at": now,
            "legal_name": DEMO_CUSTOMER_NAME,
            "industry": "Retail",
            "contact": {"email": "onboarding.demo@customer360.example"},
            "owners": [],
        },
    )
    user = await _upsert_by_key(
        database["users"],
        {"email": DEMO_USER_EMAIL},
        {
            "created_at": now,
            "updated_at": now,
            "name": "Customer 360 Demo User",
            "email": DEMO_USER_EMAIL,
            "role": "customer",
            "customer_id": customer["_id"],
        },
    )
    if user.get("customer_id") != customer["_id"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The configured demo user is linked to a different customer.",
        )
    return customer["_id"], user["_id"]


async def _read_answers(database: Database, conversation_id: ObjectId) -> list[str]:
    messages = await database["messages"].find(
        {"conversation_id": conversation_id, "role": "user"}, sort=("sequence", 1)
    )
    return [message["content"] for message in messages]


def _conversation_response(document: dict, answers: list[str]) -> ConversationResponse:
    return ConversationResponse(
        id=document["client_id"],
        startedAt=document["created_at"].isoformat(),
        answers=answers,
    )


def _document_response(document: dict) -> DocumentResponse:
    return DocumentResponse(
        id=str(document["_id"]),
        filename=document["filename"],
        contentType=document["content_type"],
        sizeBytes=document["size_bytes"],
        createdAt=document["created_at"].isoformat(),
    )


async def _owned_conversation(
    database: Database, customer_id: ObjectId, conversation_id: UUID
) -> dict:
    conversation = await database["conversations"].find_one(
        {"client_id": str(conversation_id), "customer_id": customer_id}
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    return conversation


async def _save_answer(
    database: Database,
    conversation: dict,
    customer_id: ObjectId,
    sequence: int,
    content: str,
) -> None:
    messages = database["messages"]
    query = {"conversation_id": conversation["_id"], "sequence": sequence}
    existing = await messages.find_one(query)
    if existing is not None:
        if existing["content"] != content:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This answer sequence was already saved with different content.",
            )
    else:
        current_count = await messages.count_documents(
            {"conversation_id": conversation["_id"], "role": "user"}
        )
        if sequence != current_count:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Answers must be submitted in order.",
            )
        now = datetime.now(timezone.utc)
        try:
            await messages.insert_one(
                {
                    "conversation_id": conversation["_id"],
                    "role": "user",
                    "content": content,
                    "sequence": sequence,
                    "created_at": now,
                }
            )
        except DuplicateKeyError:
            existing = await messages.find_one(query)
            if existing is None or existing["content"] != content:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This answer sequence was already saved with different content.",
                ) from None

    answers = await _read_answers(database, conversation["_id"])
    now = datetime.now(timezone.utc)
    await database["onboardings"].update_one(
        {"_id": conversation["onboarding_id"], "customer_id": customer_id},
        {
            "$set": {
                "application": {"answers": answers},
                "current_step": "review" if len(answers) == QUESTION_COUNT
                else f"question_{len(answers) + 1}",
                "updated_at": now,
            }
        },
    )
    await database["conversations"].update_one(
        {"_id": conversation["_id"]},
        {
            "$set": {
                "title": answers[0] if answers else "Business onboarding",
                "updated_at": now,
            }
        },
    )


@app.post("/api/v1/login", response_model=bool)
async def login() -> bool:
    """Always succeed for the customer demo; no credentials are needed."""
    return True


@app.get("/api/v1/conversations", response_model=list[ConversationResponse])
async def list_conversations(request: Request):
    database = get_database(request)
    customer_id, _ = await ensure_demo_profile(database)
    conversations = await database["conversations"].find(
        {"customer_id": customer_id}, sort=("updated_at", -1)
    )
    return [
        _conversation_response(
            conversation, await _read_answers(database, conversation["_id"])
        )
        for conversation in conversations
    ]


@app.post(
    "/api/v1/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(payload: ConversationPayload, request: Request):
    database = get_database(request)
    customer_id, user_id = await ensure_demo_profile(database)
    client_id = str(payload.id)
    started_at = payload.startedAt
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    started_at = started_at.astimezone(timezone.utc)
    onboarding = await _upsert_by_key(
        database["onboardings"],
        {"client_id": client_id, "customer_id": customer_id},
        {
            "created_at": started_at,
            "updated_at": started_at,
            "customer_id": customer_id,
            "created_by": user_id,
            "status": "DRAFT",
            "current_step": "question_1",
            "application": {"answers": []},
            "requested_products": [],
        },
    )
    conversation = await _upsert_by_key(
        database["conversations"],
        {"client_id": client_id, "customer_id": customer_id},
        {
            "created_at": started_at,
            "updated_at": started_at,
            "customer_id": customer_id,
            "onboarding_id": onboarding["_id"],
            "title": "Business onboarding",
            "status": "active",
        },
    )
    for sequence, answer in enumerate(payload.answers):
        await _save_answer(database, conversation, customer_id, sequence, answer)
    return _conversation_response(
        conversation, await _read_answers(database, conversation["_id"])
    )


@app.post(
    "/api/v1/conversations/{conversation_id}/answers",
    response_model=ConversationResponse,
)
async def save_conversation_answer(
    conversation_id: UUID, payload: AnswerPayload, request: Request
):
    database = get_database(request)
    customer_id, _ = await ensure_demo_profile(database)
    conversation = await database["conversations"].find_one(
        {"client_id": str(conversation_id), "customer_id": customer_id}
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    content = payload.content.strip()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Answer cannot be blank.",
        )
    await _save_answer(
        database, conversation, customer_id, payload.sequence, content
    )
    return _conversation_response(
        conversation, await _read_answers(database, conversation["_id"])
    )


@app.get(
    "/api/v1/conversations/{conversation_id}/documents",
    response_model=list[DocumentResponse],
)
async def list_documents(conversation_id: UUID, request: Request):
    database = get_database(request)
    customer_id, _ = await ensure_demo_profile(database)
    conversation = await _owned_conversation(database, customer_id, conversation_id)
    documents = await database["documents"].find(
        {"customer_id": customer_id, "conversation_id": conversation["_id"]}, sort=("created_at", 1)
    )
    return [_document_response(document) for document in documents]


@app.post(
    "/api/v1/conversations/{conversation_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    conversation_id: UUID,
    request: Request,
    file: UploadFile = File(...),
):
    database = get_database(request)
    customer_id, _ = await ensure_demo_profile(database)
    conversation = await _owned_conversation(database, customer_id, conversation_id)
    count = await database["documents"].count_documents(
        {"customer_id": customer_id, "conversation_id": conversation["_id"]}
    )
    if count >= MAX_DOCUMENTS_PER_CONVERSATION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A conversation can have at most 10 documents.",
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
            "onboarding_id": conversation["onboarding_id"],
            "conversation_id": conversation["_id"],
        },
    )
    document = {
        "created_at": now,
        "updated_at": now,
        "customer_id": customer_id,
        "onboarding_id": conversation["onboarding_id"],
        "conversation_id": conversation["_id"],
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
        await bucket.delete(storage_id)
        raise
    document["_id"] = result.inserted_id
    return _document_response(document)


@app.get("/api/v1/documents/{document_id}/download")
async def download_document(document_id: str, request: Request):
    database = get_database(request)
    customer_id, _ = await ensure_demo_profile(database)
    try:
        object_id = ObjectId(document_id)
    except InvalidId:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        ) from None
    document = await database["documents"].find_one(
        {"_id": object_id, "customer_id": customer_id}
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    try:
        content = await MCPBucket(database).read(document["storage_id"])
    except NoFile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document content not found.",
        ) from None

    return StreamingResponse(
        iter([content]),
        media_type=document["content_type"],
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(document['filename'])}"
        },
    )


@app.delete("/api/v1/conversations/{conversation_id}/documents/{document_id}")
async def delete_document(conversation_id: UUID, document_id: str, request: Request):
    database = get_database(request)
    customer_id, _ = await ensure_demo_profile(database)
    conversation = await _owned_conversation(database, customer_id, conversation_id)
    try:
        object_id = ObjectId(document_id)
    except InvalidId:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        ) from None
    document = await database["documents"].find_one(
        {
            "_id": object_id,
            "customer_id": customer_id,
            "conversation_id": conversation["_id"],
        }
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    try:
        await MCPBucket(database).delete(document["storage_id"], missing_ok=True)
    except NoFile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document content not found.",
        ) from None
    await database["documents"].delete_one({"_id": object_id})
    return {"deleted": True}
