"""Customer 360 demo API with Atlas-backed onboarding conversations."""

import asyncio
import logging
import os
from hashlib import sha256
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator
from uuid import UUID, uuid4

from bson import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .mcp_database import MCPDatabase as Database, MCPBucket, NoFile, DuplicateKeyError, StorageError, tool
from .mongodb_mcp import mongodb_mcp_session

from .demo import customer_scope, _upsert_by_key, conversation_actor, get_database
from .documents import document_response, store_upload, stream_document
from .routers import router
from .onboarding_agent import QUESTIONS, REVIEW, WELCOME, agent_enabled, interpret_answer

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
load_dotenv(Path(__file__).resolve().parents[2] / "database" / ".env")

logger = logging.getLogger(__name__)

QUESTION_COUNT = len(QUESTIONS)


class ConversationPayload(BaseModel):
    id: UUID
    startedAt: datetime
    answers: list[str] = Field(default_factory=list, max_length=QUESTION_COUNT)


class AnswerPayload(BaseModel):
    sequence: int = Field(ge=0, lt=QUESTION_COUNT)
    content: str = Field(min_length=1, max_length=4000)


class ChatPayload(BaseModel):
    id: UUID
    revision: int = Field(ge=0)
    sequence: int = Field(ge=0, lt=QUESTION_COUNT)
    content: str = Field(min_length=1, max_length=4000)


class ChatTurn(BaseModel):
    id: UUID
    sequence: int
    content: str
    clarification: str


class ConversationResponse(BaseModel):
    id: str
    startedAt: str
    answers: list[str]
    fields: list[str]
    prompts: list[str]
    turns: list[ChatTurn]
    revision: int
    agentEnabled: bool
    applicationId: str | None = None


class DocumentResponse(BaseModel):
    id: str
    filename: str
    contentType: str
    sizeBytes: int
    createdAt: str
    source: str


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
app.include_router(router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")).split(",") if origin.strip()],
    allow_methods=["DELETE", "GET", "POST"],
    allow_headers=["Content-Type"],
    expose_headers=["X-Request-ID"],
)


@app.exception_handler(StorageError)
async def storage_error_handler(request: Request, error: StorageError):
    return JSONResponse(status_code=503, content={"detail": "Atlas MCP storage operation failed. Retry the request."})


@app.middleware("http")
async def storage_request(request: Request, call_next):
    database = getattr(request.app.state, "database", None)
    path = request.url.path
    # Persona initialization and pending chat recovery can write during a GET.
    writes = (request.method in {"POST", "DELETE"} and path != "/api/v1/login") or path in {
        "/api/v1/demo/users", "/api/v1/conversations",
    }
    # Legacy document requests can initialize the default customer.
    legacy_documents = path.startswith(("/api/v1/conversations/", "/api/v1/documents/")) and not request.query_params.get("customer_id")
    if database is None or not (writes or legacy_documents):
        response = await call_next(request)
    else:
        async with database.write_lock:
            response = await call_next(request)
    response.headers["X-Request-ID"] = str(uuid4())
    return response


async def create_business_profile(database: Database, client_id: str, started_at: datetime):
    # Stable IDs make retries safe even if the first request stopped halfway.
    customer_id = ObjectId(sha256(f"customer:{client_id}".encode()).digest()[:12])
    user_id = ObjectId(sha256(f"applicant:{client_id}".encode()).digest()[:12])
    customer = await _upsert_by_key(database["customers"], {"_id": customer_id}, {
        "legal_name": "Business name pending", "created_at": started_at,
        "updated_at": started_at, "owners": [], "onboarding_client_id": client_id,
    })
    # The current schema requires created_by to reference a user. This anonymous
    # applicant record is scoped to this application; it is not a login identity.
    user = await _upsert_by_key(database["users"], {"_id": user_id}, {
        "name": "Anonymous business applicant", "email": f"{client_id}@applicant.invalid",
        "role": "customer", "customer_id": customer["_id"],
        "created_at": started_at, "updated_at": started_at,
    })
    return customer["_id"], user["_id"]


async def _read_answers(
    database: Database, conversation_id: ObjectId
) -> list[str]:
    messages = await database["messages"].find(
        {"conversation_id": conversation_id, "role": "user"}, sort=("sequence", 1)
    )
    return [message["content"] for message in messages]


def _conversation_response(document: dict, answers: list[str]) -> ConversationResponse:
    return ConversationResponse(
        id=document["client_id"],
        startedAt=document["created_at"].isoformat(),
        answers=answers,
        fields=[field for field, _ in QUESTIONS],
        prompts=[WELCOME + QUESTIONS[0][1], *[question for _, question in QUESTIONS[1:]], REVIEW],
        turns=document.get("chat_turns", []),
        revision=document.get("chat_revision", 0),
        agentEnabled=agent_enabled(),
        applicationId=str(document["onboarding_id"]) if document.get("application_submitted") else None,
    )


async def _owned_conversation(
    database: Database, customer_id: ObjectId, conversation_id: UUID
) -> dict:
    conversation = await database["conversations"].find_one(
        {"client_id": str(conversation_id), **customer_scope(customer_id)}
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
) -> list[str]:
    onboarding = await database["onboardings"].find_one(
        {"_id": conversation["onboarding_id"], "customer_id": customer_id},
    )
    if onboarding is None or onboarding["status"] != "DRAFT":
        raise HTTPException(409, "This draft has already been submitted.")
    messages = database["messages"]
    query = {"conversation_id": conversation["_id"], "sequence": sequence}
    answers = await _read_answers(database, conversation["_id"])
    if sequence < len(answers):
        if answers[sequence] != content:
            raise HTTPException(409, "This answer sequence was already saved with different content.")
    else:
        if sequence != len(answers):
            raise HTTPException(409, "Answers must be submitted in order.")
        now = datetime.now(timezone.utc)
        try:
            await messages.insert_one(
                {
                    "conversation_id": conversation["_id"],
                    "role": "user",
                    "content": content,
                    "sequence": sequence,
                    "created_at": now,
                },
            )
        except DuplicateKeyError:
            existing = await messages.find_one(query)
            if existing is None or existing["content"] != content:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This answer sequence was already saved with different content.",
                ) from None

        answers.append(content)

    now = datetime.now(timezone.utc)
    fields = ("legal_name", "business_activity", "registration_location", "ownership_description", "banking_needs")
    application = dict(zip(fields, answers))
    if conversation.get("owner_customer_id") and application:
        profile = {field: application[field] for field in fields[:4] if field in application}
        await database["customers"].update_one({"_id": customer_id}, {"$set": {**profile, "updated_at": now}})
    await database["onboardings"].update_one(
        {"_id": conversation["onboarding_id"], "customer_id": customer_id, "status": "DRAFT"},
        {
            "$set": {
                "application": {**application, "answers": answers},
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

    return answers


@app.post("/api/v1/login", response_model=bool)
async def login() -> bool:
    """Always succeed for the customer demo; no credentials are needed."""
    return True


@app.get("/api/v1/conversations", response_model=list[ConversationResponse])
async def list_conversations(request: Request):
    database = get_database(request)
    customer_id, _ = await conversation_actor(database, request.query_params.get("customer_id"))
    conversations = await database["conversations"].find(
        customer_scope(customer_id), sort=("updated_at", -1)
    )
    if not conversations:
        return []

    onboarding_ids = [
        row["onboarding_id"] for row in conversations if not row.get("application_submitted")
    ]
    async def submitted_ids():
        if not onboarding_ids:
            return set()
        rows = await database.onboardings.find(
            {"_id": {"$in": onboarding_ids}, "status": {"$ne": "DRAFT"}},
            projection={"_id": 1},
        )
        return {row["_id"] for row in rows}

    submitted, messages = await asyncio.gather(
        submitted_ids(),
        database.messages.find(
            {"conversation_id": {"$in": [row["_id"] for row in conversations]}, "role": "user"},
            sort=("sequence", 1),
            projection={"conversation_id": 1, "sequence": 1, "content": 1},
        ),
    )
    answers = {}
    for message in messages:
        answers.setdefault(message["conversation_id"], []).append(message["content"])

    responses = {}
    for row in conversations:
        if row["onboarding_id"] in submitted:
            row["application_submitted"] = True
        if row.get("pending_answer") and not row.get("application_submitted"):
            responses[row["_id"]] = await _chat_response(database, row, row["customer_id"])
    return [
        responses[row["_id"]] if row["_id"] in responses
        else _conversation_response(row, answers.get(row["_id"], []))
        for row in conversations
    ]


@app.post(
    "/api/v1/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(payload: ConversationPayload, request: Request):
    database = get_database(request)
    owner_id, owner_user_id = await conversation_actor(database, request.query_params.get("customer_id"))
    client_id = str(payload.id)
    started_at = payload.startedAt
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    started_at = started_at.astimezone(timezone.utc)
    existing = await database.conversations.find_one({"client_id": client_id})
    if existing:
        conversation = await _owned_conversation(database, owner_id, payload.id)
        for sequence, answer in enumerate(payload.answers):
            await _save_answer(database, conversation, conversation["customer_id"], sequence, answer)
        return await _chat_response(database, conversation, conversation["customer_id"])
    # Reserve the draft under the selected persona before provisioning its profile.
    claim = await database.onboardings.upsert({"client_id": client_id}, {
        "client_id": client_id, "customer_id": owner_id, "owner_customer_id": owner_id,
        "created_by": owner_user_id,
        "status": "DRAFT", "created_at": started_at, "updated_at": started_at,
    })
    if claim.get("owner_customer_id", claim["customer_id"]) != owner_id:
        raise HTTPException(404, "Conversation not found.")
    customer_id, user_id = await create_business_profile(database, client_id, started_at)
    await database.onboardings.update_one({"_id": claim["_id"], "status": "DRAFT"}, {"$set": {
        "customer_id": customer_id, "created_by": user_id, "current_step": "question_1",
        "application": {"answers": []}, "requested_products": [],
    }})
    onboarding = claim
    conversation = await _upsert_by_key(
        database["conversations"],
        {"client_id": client_id, "customer_id": customer_id},
        {
            "created_at": started_at,
            "updated_at": started_at,
            "customer_id": customer_id,
            "onboarding_id": onboarding["_id"],
            "owner_customer_id": owner_id,
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
    customer_id, _ = await conversation_actor(database, request.query_params.get("customer_id"))
    conversation = await database["conversations"].find_one(
        {"client_id": str(conversation_id), **customer_scope(customer_id)}
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    customer_id = conversation["customer_id"]
    content = payload.content.strip()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Answer cannot be blank.",
        )
    answers = await _save_answer(database, conversation, customer_id, payload.sequence, content)
    return _conversation_response(conversation, answers)


async def _chat_response(database, conversation, customer_id):
    if not conversation.get("application_submitted"):
        onboarding = await database["onboardings"].find_one({"_id": conversation["onboarding_id"]})
        if onboarding and onboarding["status"] != "DRAFT":
            conversation = {**conversation, "application_submitted": True}
        elif turn := conversation.get("pending_answer"):
            answers = await _save_answer(database, conversation, customer_id, turn["sequence"], turn["answer"])
            await database.conversations.update_one(
                {"_id": conversation["_id"]}, {"$unset": {"pending_answer": ""}},
            )
            return _conversation_response(conversation, answers)
    answers = await _read_answers(database, conversation["_id"])
    return _conversation_response(conversation, answers)


@app.post("/api/v1/conversations/{conversation_id}/chat", response_model=ConversationResponse)
async def send_chat_message(conversation_id: UUID, payload: ChatPayload, request: Request):
    database = get_database(request)
    customer_id, _ = await conversation_actor(database, request.query_params.get("customer_id"))
    conversation = await _owned_conversation(database, customer_id, conversation_id)
    customer_id = conversation["customer_id"]
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Enter a message before sending.")

    turn_id = str(payload.id)

    def current_turn(document: dict, answers: list[str]) -> bool:
        for turn in document.get("chat_turns", []):
            if turn["id"] == turn_id:
                if turn["content"] == content and turn["sequence"] == payload.sequence:
                    return False
                raise HTTPException(status_code=409, detail="This message ID is already in use.")
        if document.get("chat_revision", 0) != payload.revision or len(answers) != payload.sequence:
            raise HTTPException(status_code=409, detail="This conversation changed. Reload it and try again.")
        return True

    response = await _chat_response(database, conversation, customer_id)
    if not current_turn(conversation, response.answers):
        return response
    if response.applicationId:
        raise HTTPException(409, "This draft has already been submitted.")

    recent_turns = [
        {"message": turn["content"], "clarification": turn["clarification"]}
        for turn in conversation.get("chat_turns", [])
        if turn["sequence"] == payload.sequence
    ][-5:]
    try:
        decision = await run_in_threadpool(interpret_answer, payload.sequence, content, recent_turns)
    except Exception as error:
        logger.warning("Onboarding guide failed (%s)", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail="The onboarding guide is unavailable. Your message can be retried.",
        ) from None

    await database.conversations.update_one(
        {"_id": conversation["_id"]},
        {
            "$inc": {"chat_revision": 1},
            "$set": {
                "updated_at": datetime.now(timezone.utc),
                **({"pending_answer": {"answer": decision.answer, "sequence": payload.sequence}}
                   if decision.action == "accept" else {}),
            },
            "$push": {
                "chat_turns": {
                    "$each": [{
                        "id": turn_id,
                        "sequence": payload.sequence,
                        "content": content,
                        "clarification": decision.reply,
                    }],
                    "$slice": -50,
                },
            },
        },
    )
    saved = await database.conversations.find_one({"_id": conversation["_id"]})
    return await _chat_response(database, saved, customer_id)


@app.get(
    "/api/v1/conversations/{conversation_id}/documents",
    response_model=list[DocumentResponse],
)
async def list_documents(conversation_id: UUID, request: Request):
    database = get_database(request)
    customer_id, _ = await conversation_actor(database, request.query_params.get("customer_id"))
    conversation = await _owned_conversation(database, customer_id, conversation_id)
    customer_id = conversation["customer_id"]
    documents = await database["documents"].find(
        {"customer_id": customer_id, "conversation_id": conversation["_id"]}, sort=("created_at", 1)
    )
    return [document_response(document) for document in documents]


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
    customer_id, _ = await conversation_actor(database, request.query_params.get("customer_id"))
    conversation = await _owned_conversation(database, customer_id, conversation_id)
    customer_id = conversation["customer_id"]
    return await store_upload(database, customer_id, conversation["onboarding_id"], file, conversation["_id"])


@app.get("/api/v1/documents/{document_id}/download")
async def download_document(document_id: str, request: Request):
    database = get_database(request)
    customer_id, _ = await conversation_actor(database, request.query_params.get("customer_id"))
    try:
        object_id = ObjectId(document_id)
    except InvalidId:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        ) from None
    document = await database["documents"].find_one(
        {"_id": object_id}
    )
    if document and document["customer_id"] != customer_id:
        owned = await database.onboardings.find_one({"_id": document["onboarding_id"], **customer_scope(customer_id)})
        if not owned:
            document = None
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    return await stream_document(database, document)

@app.delete("/api/v1/conversations/{conversation_id}/documents/{document_id}")
async def delete_document(conversation_id: UUID, document_id: str, request: Request):
    database = get_database(request)
    customer_id, _ = await conversation_actor(database, request.query_params.get("customer_id"))
    conversation = await _owned_conversation(database, customer_id, conversation_id)
    customer_id = conversation["customer_id"]
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
        await MCPBucket(database).delete(document["storage_id"])
    except NoFile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document content not found.",
        ) from None
    await database["documents"].delete_one({"_id": object_id})
    return {"deleted": True}
